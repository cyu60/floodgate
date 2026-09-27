// Any Jev-compatible POST /v1/systemone endpoint: our River server (python -m floodgate.open_jev.server, :8791)
// or TypeSafe's hosted Jev (https://api.typesafe.ai/v1/systemone with an API key and model "jev-latest").
import { QUESTION } from "../lib/config.js";
import { getJson, postJson } from "./http.js";

export default {
  id: "systemone",
  name: "Jev-compatible endpoint (/v1/systemone)",
  description: "open_jev.server on :8791 (River), or TypeSafe's hosted Jev as a baseline to compare against.",
  settings: [
    { key: "endpoint", label: "Endpoint", default: "http://127.0.0.1:8791/v1/systemone" },
    { key: "apiKey", label: "API key (TypeSafe only)", default: "", type: "password" },
    { key: "model", label: "Model (e.g. jev-latest; blank for our server)", default: "" },
    { key: "timeoutMs", label: "Timeout (ms)", default: 15000, type: "number" },
  ],

  async classify(page, ctx, cfg) {
    // Same state keys as floodgate/gate_server.py, plus whatever enrichers added.
    const state = { url: page.url.slice(0, 300), title: (page.title || "").slice(0, 160), time: ctx.time, stated_task: ctx.task };
    if (ctx.aboutMe) state.about_me = ctx.aboutMe;
    if (page.description) state.description = page.description.slice(0, 300);
    if (page.channel) state.channel = page.channel;
    Object.assign(state, ctx.extra);
    const body = { state, questions: { distraction: { type: "noul", instructions: QUESTION } } };
    if (cfg.model) body.model = cfg.model;
    const headers = cfg.apiKey ? { Authorization: `Bearer ${cfg.apiKey}` } : {};
    const d = await postJson(cfg.endpoint, body, { timeoutMs: Number(cfg.timeoutMs) || 15000, headers });
    return { p: Number(d.answers?.distraction?.noul), model: d.model || "Jev endpoint", serverMs: d.usage?.latency_ms };
  },

  async health(cfg) {
    const base = cfg.endpoint.replace(/\/v1\/systemone\/?$/, "");
    const headers = cfg.apiKey ? { Authorization: `Bearer ${cfg.apiKey}` } : {};
    const s = await getJson(base || cfg.endpoint, { headers }).catch((e) => {
      if (/HTTP \d/.test(e.message)) return {}; // reachable, just no GET route (hosted APIs)
      throw e;
    });
    const m = s.models?.[0];
    return { ok: true, detail: m ? `${m.name}${m.checkpoint ? " · trained" : ""}` : "reachable", info: s };
  },

  async describe(cfg) {
    const s = await getJson(cfg.endpoint.replace(/\/v1\/systemone\/?$/, "")).catch(() => ({}));
    const m = s.models?.[0] || {};
    return { provider: "systemone", checkpoint: m.checkpoint || null, temperature: m.temperature ?? null, model: cfg.model || m.name || null };
  },
};
