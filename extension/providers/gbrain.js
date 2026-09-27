// GBrain memory for Floodgate (hosted gbrain.io, or any GBrain MCP server).
// Hosted gbrain.io speaks OAuth 2.1 only: click "Sign in with GBrain" in Dashboard -> Model -> Context providers
// (PKCE + dynamic client registration, scopes memory:read memory:full). A self-hosted `gbrain serve --http` also
// accepts a legacy bearer token (`gbrain auth create <name> --scopes read,write`): paste it into "Token" instead.
//
// What it does in Floodgate (enable it under Dashboard -> Model -> context providers):
//   onLabel : every correction ("It's on task", "Distraction", "It depends") is saved with `remember`,
//             scoped to the task, so the judgment survives restarts and any agent on your GBrain can use it.
//   recall  : reads those corrections back with `recall`, so a page you corrected anywhere is decided by your memory.
//   enrich  : before a page is judged, recalls what GBrain knows about the current task (ctx.extra.gbrain).
//   health  : initialize + tools/list, shows which memory tools the workspace exposes.
//
// Talks plain MCP over streamable HTTP (JSON-RPC: initialize, tools/list, tools/call).
import { labelWord } from "../lib/memory.js";
import { canonicalUrl, taskSimilarity } from "../lib/text.js";
import { accessToken, signIn, signOut, status } from "./oauth.js";

const SCOPE = "memory:read memory:full"; // search + save
const PROVENANCE = "Floodgate Chrome extension: a correction the user made while browsing";

const PROTOCOL = "2025-06-18";
const recallCache = new Map(); // "task|url" -> {at, hit}

// Reads back the notes onLabel writes: Floodgate correction (<iso>): while working on "<task>", the page "<title>" (<url>) is <VERDICT>.
const NOTE = /Floodgate correction \(([^)]*)\): while working on "(.*?)", the page "(.*?)" \((https?:\/\/\S+?)\) is (ON TASK|a DISTRACTION|IT DEPENDS)/g;
const VERDICT = { "ON TASK": 0, "a DISTRACTION": 1, "IT DEPENDS": 0.5 };
export function parseCorrections(text) {
  return [...String(text || "").matchAll(NOTE)].map(([, ts, task, title, url, v]) => ({ ts: Date.parse(ts) || 0, task, title, url, label: VERDICT[v] }));
}
let session = { key: "", id: null, tools: null, nextId: 1, bearer: "" };
const cache = new Map(); // task -> {at, text}

// A pasted token (self-hosted GBrain) wins; otherwise the OAuth access token from "Sign in with GBrain".
async function bearer(cfg, { force = false } = {}) {
  if (cfg.token) return cfg.token;
  const t = await accessToken("gbrain", cfg.endpoint, { force });
  if (!t) throw new Error("Not signed in: click “Sign in with GBrain” (Dashboard → Model → Context providers).");
  return t;
}
const signedIn = async (cfg) => !!cfg.token || (await status("gbrain", cfg.endpoint)).signedIn;

async function rpc(cfg, method, params, { notify = false } = {}) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
    "MCP-Protocol-Version": PROTOCOL,
  };
  if (session.bearer) headers.Authorization = `Bearer ${session.bearer}`;
  if (session.id) headers["Mcp-Session-Id"] = session.id;
  const body = notify ? { jsonrpc: "2.0", method, params } : { jsonrpc: "2.0", id: session.nextId++, method, params };
  const res = await fetch(cfg.endpoint, { method: "POST", headers, body: JSON.stringify(body) });
  const sid = res.headers.get("Mcp-Session-Id");
  if (sid) session.id = sid;
  if (notify) return null;
  if (res.status === 401 || res.status === 403) {
    session.tools = null; // reconnect next time, with a refreshed token
    session.refresh = !cfg.token;
    throw new Error(
      cfg.token
        ? `GBrain rejected the pasted token (${res.status}). Hosted gbrain.io only takes “Sign in with GBrain”; clear the Token field.`
        : `GBrain rejected the sign-in (${res.status}). Click “Sign in with GBrain” again.`,
    );
  }
  if (!res.ok) throw new Error(`GBrain ${method} failed: HTTP ${res.status}`);
  const text = await res.text();
  let msg = null;
  if ((res.headers.get("Content-Type") || "").includes("text/event-stream")) {
    for (const line of text.split("\n")) {
      if (!line.startsWith("data:")) continue;
      try { const m = JSON.parse(line.slice(5).trim()); if (m.id !== undefined) msg = m; } catch {}
    }
  } else {
    msg = JSON.parse(text);
  }
  if (!msg) throw new Error(`GBrain ${method}: empty response`);
  if (msg.error) throw new Error(`GBrain ${method}: ${msg.error.message || JSON.stringify(msg.error)}`);
  return msg.result;
}

async function connect(cfg) {
  const token = await bearer(cfg, { force: !!session.refresh });
  session.refresh = false;
  if (session.key === `${cfg.endpoint}|${token}` && session.tools) return session.tools;
  session = { key: `${cfg.endpoint}|${token}`, id: null, tools: null, nextId: 1, bearer: token };
  await rpc(cfg, "initialize", { protocolVersion: PROTOCOL, capabilities: {}, clientInfo: { name: "floodgate", version: "0.2" } });
  await rpc(cfg, "notifications/initialized", {}, { notify: true }).catch(() => {});
  const r = await rpc(cfg, "tools/list", {});
  session.tools = r?.tools || [];
  return session.tools;
}

// Hosted GBrain names them `recall` (search) and `remember` (save); other servers are matched by pattern.
const pick = (tools, re, override, preferred) =>
  (override && tools.find((t) => t.name === override)) || tools.find((t) => t.name === preferred) || tools.find((t) => re.test(t.name)) || null;
const SEARCH = [/search|recall|query|find/i, "recall"];
const WRITE = [/remember|write|save|add|note/i, "remember"];

// Put the text in the tool's main text argument, and fill required bookkeeping ones (`remember` needs a provenance).
export function argsFor(tool, text) {
  const props = tool?.inputSchema?.properties || {};
  const req = tool?.inputSchema?.required || [];
  const meta = /provenance|source|entity|limit|scope|id$/i;
  const main =
    ["query", "content", "text", "fact", "note", "memory", "statement", "value", "body"].find((k) => k in props) ||
    req.find((k) => !meta.test(k)) ||
    Object.keys(props).find((k) => props[k]?.type === "string" && !meta.test(k)) ||
    "query";
  const args = { [main]: text };
  for (const k of new Set([...req, ...Object.keys(props)])) if (/provenance|source/i.test(k) && !(k in args)) args[k] = PROVENANCE;
  return args;
}

function textOf(result) {
  return (result?.content || []).filter((c) => c.type === "text").map((c) => c.text).join("\n").trim();
}

export default {
  id: "gbrain",
  name: "GBrain memory",
  description: "Remembers your corrections in GBrain (per task) and recalls what GBrain knows about the task you're on.",
  settings: [
    { key: "endpoint", label: "GBrain MCP endpoint", default: "https://gbrain.io/mcp" },
    { key: "token", label: "Token (only for self-hosted gbrain serve; leave blank for gbrain.io and use Sign in)", default: "", type: "password" },
    { key: "searchTool", label: "Search tool (blank = auto, recall on gbrain.io)", default: "" },
    { key: "rememberTool", label: "Remember tool (blank = auto, remember on gbrain.io)", default: "" },
  ],

  // Buttons in Dashboard -> Model. Sign-in has to start from a click on an extension page (chrome.identity).
  actions: [
    {
      label: "Sign in with GBrain",
      async run(cfg) {
        const rec = await signIn("gbrain", { resource: cfg.endpoint, scope: SCOPE, clientName: "Floodgate (Chrome extension)" });
        session.tools = null;
        return `Signed in to GBrain (${rec.scope}).`;
      },
    },
    {
      label: "Sign out",
      async run() {
        await signOut("gbrain");
        session = { key: "", id: null, tools: null, nextId: 1, bearer: "" };
        return "Signed out of GBrain.";
      },
    },
  ],

  async health(cfg) {
    const tools = await connect(cfg);
    const s = pick(tools, ...SEARCH, cfg.searchTool);
    const w = pick(tools, ...WRITE, cfg.rememberTool);
    return { ok: !!(s || w), detail: `${tools.length} tools · search: ${s?.name || "none"} · remember: ${w?.name || "none (read-only access?)"}` };
  },

  async enrich(page, ctx, cfg) {
    if (!ctx.task) return {};
    const hit = cache.get(ctx.task);
    if (hit && Date.now() - hit.at < 60_000) return hit.text ? { gbrain: hit.text } : {};
    const tools = await connect(cfg);
    const s = pick(tools, ...SEARCH, cfg.searchTool);
    if (!s) return {};
    const r = await rpc(cfg, "tools/call", { name: s.name, arguments: argsFor(s, `What am I working on, and what counts as on task for: ${ctx.task}`) });
    const text = textOf(r).slice(0, 400);
    cache.set(ctx.task, { at: Date.now(), text });
    return text ? { gbrain: text } : {};
  },

  // Memory: a correction you made on any device (or any agent wrote to your GBrain) decides this page for the same task.
  async recall(page, ctx, cfg) {
    if (!ctx.task || !(await signedIn(cfg))) return null;
    const url = canonicalUrl(page.url);
    const key = `${ctx.task}|${url}`;
    const cached = recallCache.get(key);
    if (cached && Date.now() - cached.at < 60_000) return cached.hit;
    const tools = await connect(cfg);
    const s = pick(tools, ...SEARCH, cfg.searchTool);
    if (!s) return null;
    const r = await rpc(cfg, "tools/call", { name: s.name, arguments: argsFor(s, `Floodgate correction ${url}`) });
    const h = parseCorrections(textOf(r))
      .filter((c) => canonicalUrl(c.url) === url && taskSimilarity(c.task, ctx.task) >= 0.5)
      .sort((a, b) => a.ts - b.ts)
      .at(-1);
    const hit = h ? { p: h.label, reason: `GBrain remembers: this page is ${labelWord(h.label)} for “${h.task}”`, source: "GBrain memory" } : null;
    recallCache.set(key, { at: Date.now(), hit });
    return hit;
  },

  async onLabel(l, ctx, cfg) {
    recallCache.clear();
    const tools = await connect(cfg);
    const w = pick(tools, ...WRITE, cfg.rememberTool);
    if (!w) throw new Error("GBrain has no remember tool on this connection (sign in with memory:full).");
    const verdict = l.label === 0 ? "ON TASK" : l.label === 1 ? "a DISTRACTION" : "IT DEPENDS (50/50)";
    const note =
      `Floodgate correction (${new Date(l.ts || Date.now()).toISOString()}): while working on "${l.task || ctx.task}", ` +
      `the page "${l.title || ""}" (${l.url}) is ${verdict} for me. The model had said ${typeof l.model_p === "number" ? Math.round(l.model_p * 100) + "%" : "?"} distraction.`;
    await rpc(cfg, "tools/call", { name: w.name, arguments: argsFor(w, note) });
  },
};
