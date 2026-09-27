// GBrain memory for Floodgate (hosted gbrain.io, or any GBrain MCP server).
// Docs: https://gbrain.io/docs/workspace/memory-anywhere  ·  endpoint https://gbrain.io/mcp, Bearer token from
// the workspace's "Add a connection" page. "Read" access = search/recall; "Full" access also lets it remember.
//
// What it does in Floodgate (enable it under Dashboard -> Model -> context providers):
//   onLabel : every correction ("It's on task", "Distraction", "It depends") is remembered in GBrain,
//             scoped to the task, so the judgment survives restarts and any agent on your GBrain can use it.
//   enrich  : before a page is judged, searches GBrain for what it knows about the current task and passes the
//             top snippet along as ctx.extra.gbrain (the gate logs it; the model's state stays in its trained format).
//   health  : initialize + tools/list, shows which memory tools the workspace exposes.
//
// Talks plain MCP over streamable HTTP (JSON-RPC: initialize, tools/list, tools/call). Tool names are discovered
// from tools/list (anything matching remember/write/save/add for writes, search/recall/query/find for reads).

import { labelWord } from "../lib/memory.js";
import { canonicalUrl, taskSimilarity } from "../lib/text.js";

const PROTOCOL = "2025-06-18";
const recallCache = new Map(); // "task|url" -> {at, hit}

// Reads back the notes onLabel writes: Floodgate correction (<iso>): while working on "<task>", the page "<title>" (<url>) is <VERDICT>.
const NOTE = /Floodgate correction \(([^)]*)\): while working on "(.*?)", the page "(.*?)" \((https?:\/\/\S+?)\) is (ON TASK|a DISTRACTION|IT DEPENDS)/g;
const VERDICT = { "ON TASK": 0, "a DISTRACTION": 1, "IT DEPENDS": 0.5 };
export function parseCorrections(text) {
  return [...String(text || "").matchAll(NOTE)].map(([, ts, task, title, url, v]) => ({ ts: Date.parse(ts) || 0, task, title, url, label: VERDICT[v] }));
}
let session = { key: "", id: null, tools: null, nextId: 1 };
const cache = new Map(); // task -> {at, text}

function sameCfg(cfg) {
  return session.key === `${cfg.endpoint}|${cfg.token}`;
}

async function rpc(cfg, method, params, { notify = false } = {}) {
  const headers = {
    "Content-Type": "application/json",
    Accept: "application/json, text/event-stream",
    "MCP-Protocol-Version": PROTOCOL,
  };
  if (cfg.token) headers.Authorization = `Bearer ${cfg.token}`;
  if (session.id) headers["Mcp-Session-Id"] = session.id;
  const body = notify ? { jsonrpc: "2.0", method, params } : { jsonrpc: "2.0", id: session.nextId++, method, params };
  const res = await fetch(cfg.endpoint, { method: "POST", headers, body: JSON.stringify(body) });
  const sid = res.headers.get("Mcp-Session-Id");
  if (sid) session.id = sid;
  if (notify) return null;
  if (res.status === 401 || res.status === 403) throw new Error(`GBrain rejected the token (${res.status}). Create a connection token with Read or Full access.`);
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
  if (!cfg.token) throw new Error("Add your GBrain connection token (gbrain.io -> your workspace -> Add a connection).");
  if (sameCfg(cfg) && session.tools) return session.tools;
  session = { key: `${cfg.endpoint}|${cfg.token}`, id: null, tools: null, nextId: 1 };
  await rpc(cfg, "initialize", { protocolVersion: PROTOCOL, capabilities: {}, clientInfo: { name: "floodgate", version: "0.2" } });
  await rpc(cfg, "notifications/initialized", {}, { notify: true }).catch(() => {});
  const r = await rpc(cfg, "tools/list", {});
  session.tools = r?.tools || [];
  return session.tools;
}

const pick = (tools, re, override) =>
  (override && tools.find((t) => t.name === override)) || tools.find((t) => re.test(t.name)) || null;

function argsFor(tool, text) {
  const props = tool?.inputSchema?.properties || {};
  const req = tool?.inputSchema?.required || [];
  const key = req.find((k) => props[k]?.type === "string") || Object.keys(props).find((k) => props[k]?.type === "string") || "query";
  return { [key]: text };
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
    { key: "token", label: "Connection token", default: "", type: "password" },
    { key: "searchTool", label: "Search tool (blank = auto)", default: "" },
    { key: "rememberTool", label: "Remember tool (blank = auto, needs Full access)", default: "" },
  ],

  async health(cfg) {
    const tools = await connect(cfg);
    const s = pick(tools, /search|recall|query|find/i, cfg.searchTool);
    const w = pick(tools, /remember|write|save|add|note/i, cfg.rememberTool);
    return { ok: !!(s || w), detail: `${tools.length} tools · search: ${s?.name || "none"} · remember: ${w?.name || "none (Read access?)"}` };
  },

  async enrich(page, ctx, cfg) {
    if (!ctx.task) return {};
    const hit = cache.get(ctx.task);
    if (hit && Date.now() - hit.at < 60_000) return hit.text ? { gbrain: hit.text } : {};
    const tools = await connect(cfg);
    const s = pick(tools, /search|recall|query|find/i, cfg.searchTool);
    if (!s) return {};
    const r = await rpc(cfg, "tools/call", { name: s.name, arguments: argsFor(s, `What am I working on, and what counts as on task for: ${ctx.task}`) });
    const text = textOf(r).slice(0, 400);
    cache.set(ctx.task, { at: Date.now(), text });
    return text ? { gbrain: text } : {};
  },

  // Memory: a correction you made on any device (or any agent wrote to your GBrain) decides this page for the same task.
  async recall(page, ctx, cfg) {
    if (!ctx.task || !cfg.token) return null;
    const url = canonicalUrl(page.url);
    const key = `${ctx.task}|${url}`;
    const cached = recallCache.get(key);
    if (cached && Date.now() - cached.at < 60_000) return cached.hit;
    const tools = await connect(cfg);
    const s = pick(tools, /search|recall|query|find/i, cfg.searchTool);
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
    const w = pick(tools, /remember|write|save|add|note/i, cfg.rememberTool);
    if (!w) throw new Error("GBrain has no remember tool on this connection (needs Full access).");
    const verdict = l.label === 0 ? "ON TASK" : l.label === 1 ? "a DISTRACTION" : "IT DEPENDS (50/50)";
    const note =
      `Floodgate correction (${new Date(l.ts || Date.now()).toISOString()}): while working on "${l.task || ctx.task}", ` +
      `the page "${l.title || ""}" (${l.url}) is ${verdict} for me. The model had said ${typeof l.model_p === "number" ? Math.round(l.model_p * 100) + "%" : "?"} distraction.`;
    await rpc(cfg, "tools/call", { name: w.name, arguments: argsFor(w, note) });
  },
};
