// Memorable procedural memory for Floodgate (https://memorable.sh, or any Memorable MCP server).
// Memorable stores *procedures* — how a task was actually carried out, step by step — rather than facts.
// GBrain remembers what you know; Memorable remembers what you were in the middle of doing.
//
// What it does in Floodgate (enable it under Dashboard -> Model -> context providers):
//   recall : if the procedure you are working through literally names this page's site, the page IS the work,
//            so it votes "on task" and says which step. It only ever rescues a page, never blocks one: when the
//            procedure says nothing about this site it returns null and the model decides as usual.
//   enrich : passes the whole procedure along as ctx.extra.memorable, so the model judges the page against what
//            you are actually doing right now, not just the task sentence you typed.
//   health : initialize + tools/list, shows which recall tools the server exposes.
//
// Recall-only by design: Memorable records procedures from your agent sessions through its own CLI hooks
// (`memorable install-hooks`), so Floodgate never writes to it and cannot corrupt your procedure graph.
//
// Talks plain MCP over streamable HTTP (JSON-RPC: initialize, tools/list, tools/call), the same transport the
// GBrain provider uses. The transport is duplicated here on purpose: sharing it would mean editing gbrain.js.
// Offline: python3 tools/mock_memorable.py  (endpoint http://127.0.0.1:8798/mcp, any token)

const PROTOCOL = "2025-06-18";
let session = { key: "", id: null, tools: null, nextId: 1 };
const cache = new Map(); // task -> {at, text}

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
  if (res.status === 401 || res.status === 403) throw new Error(`Memorable rejected the token (${res.status}). Run \`memorable login\` and paste the key from memorable.sh/dash.`);
  if (!res.ok) throw new Error(`Memorable ${method} failed: HTTP ${res.status}`);
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
  if (!msg) throw new Error(`Memorable ${method}: empty response`);
  if (msg.error) throw new Error(`Memorable ${method}: ${msg.error.message || JSON.stringify(msg.error)}`);
  return msg.result;
}

async function connect(cfg) {
  if (session.key === `${cfg.endpoint}|${cfg.token}` && session.tools) return session.tools;
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

/** The procedure text for this task, cached for a minute. "" when there is nothing to recall.
 *  Keyed by connection as well as task: editing the endpoint or token must not serve the old server's answer. */
async function procedureFor(ctx, cfg) {
  const key = `${cfg.endpoint}|${cfg.token}|${ctx.task}`;
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < 60_000) return hit.text;
  const tools = await connect(cfg);
  const r = pick(tools, /recall|inject|procedure|workflow|search|find/i, cfg.recallTool);
  if (!r) return "";
  const out = await rpc(cfg, "tools/call", { name: r.name, arguments: argsFor(r, ctx.task) });
  const text = textOf(out).slice(0, 400);
  cache.set(key, { at: Date.now(), text });
  return text;
}

function hostOf(url) {
  try { return new URL(url).hostname.replace(/^www\./, ""); } catch { return ""; }
}

/** The line of the procedure that names this host, if any. */
function stepMentioning(procedure, host) {
  if (!host) return null;
  return procedure.split("\n").find((line) => line.toLowerCase().includes(host.toLowerCase())) || null;
}

export default {
  id: "memorable",
  name: "Memorable procedures",
  description: "Recalls the procedure you're working through, so a page is judged against what you're actually doing.",
  settings: [
    { key: "endpoint", label: "Memorable MCP endpoint", default: "http://127.0.0.1:8798/mcp" },
    { key: "token", label: "API key (blank for a local server)", default: "", type: "password" },
    { key: "recallTool", label: "Recall tool (blank = auto)", default: "" },
  ],

  async health(cfg) {
    const tools = await connect(cfg);
    const r = pick(tools, /recall|inject|procedure|workflow|search|find/i, cfg.recallTool);
    return { ok: !!r, detail: `${tools.length} tools · recall: ${r?.name || "none"}` };
  },

  async recall(page, ctx, cfg) {
    if (!ctx.task) return null;
    const step = stepMentioning(await procedureFor(ctx, cfg), hostOf(page.url));
    if (!step) return null;
    return { p: 0.1, reason: `Memorable: this is a step in what you're doing — ${step.trim()}`, source: "Memorable procedure" };
  },

  async enrich(page, ctx, cfg) {
    if (!ctx.task) return {};
    const text = await procedureFor(ctx, cfg);
    return text ? { memorable: text } : {};
  },
};
