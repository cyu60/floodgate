// Any Jev-compatible POST /v1/systemone endpoint. Default: the team's River model (python -m floodgate.open_jev.server,
// shared over ngrok with a bearer token). Also works with TypeSafe's hosted Jev (https://api.typesafe.ai/v1/systemone,
// API key, model "jev-latest") as a baseline.
import { DEFAULT_MODEL_URL, QUESTION } from "../lib/config.js";
import { getJson, postJson } from "./http.js";

// ngrok's free tier answers browser-looking requests with an HTML warning page unless this header is present.
const NGROK = { "ngrok-skip-browser-warning": "true" };

// The exact text line the River models were trained on (prep_gate_dataset.py, lib/rows.js, gate_server.py).
export function stateLine(page, ctx) {
  return `URL: ${page.url.slice(0, 200)} Title: ${(page.title || "").slice(0, 120)}. Time: ${ctx.time}. Stated task: ${ctx.task || "deep work on the current project"}.`;
}

export default {
  id: "systemone",
  name: "River model (Jev-compatible /v1/systemone)",
  description: "The team's model trained on River, shared over ngrok. Paste the token as the API key. Also works with TypeSafe's hosted Jev.",
  settings: [
    { key: "endpoint", label: "Endpoint", default: DEFAULT_MODEL_URL },
    { key: "apiKey", label: "API key / bearer token", default: "", type: "password" },
    { key: "model", label: "Model (blank for the River model; jev-latest for TypeSafe)", default: "" },
    { key: "timeoutMs", label: "Timeout (ms)", default: 20000, type: "number" },
  ],

  async classify(page, ctx, cfg) {
    const body = { state: stateLine(page, ctx), questions: { distraction: { type: "noul", instructions: QUESTION } } };
    if (cfg.model) body.model = cfg.model;
    const headers = { ...NGROK, ...(cfg.apiKey ? { Authorization: `Bearer ${cfg.apiKey}` } : {}) };
    let d;
    try {
      d = await postJson(cfg.endpoint, body, { timeoutMs: Number(cfg.timeoutMs) || 20000, headers });
    } catch (e) {
      if (/HTTP 401/.test(e.message)) throw new Error(cfg.apiKey ? "the model rejected the API key" : "add the API key in Dashboard → Model");
      if (/HTTP 404/.test(e.message)) throw new Error("model address not found (the ngrok link may have changed)");
      throw e;
    }
    return { p: Number(d.answers?.distraction?.noul), model: d.model ? `River model (${d.model})` : "River model", serverMs: d.usage?.latency_ms };
  },

  async health(cfg) {
    const base = cfg.endpoint.replace(/\/v1\/systemone\/?$/, "");
    const headers = { ...NGROK, ...(cfg.apiKey ? { Authorization: `Bearer ${cfg.apiKey}` } : {}) };
    const s = await getJson(base || cfg.endpoint, { headers, timeoutMs: 8000 }).catch((e) => {
      if (/HTTP \d/.test(e.message)) return {}; // reachable, just no GET route (hosted APIs)
      throw e;
    });
    const m = s.models?.[0];
    const what = m ? `${m.name}${m.checkpoint ? " · trained checkpoint" : ""}` : "reachable";
    if (!cfg.apiKey) return { ok: false, detail: `${what}, but no API key yet: paste the token` };
    return { ok: true, detail: what, info: s };
  },

  async describe(cfg) {
    const s = await getJson(cfg.endpoint.replace(/\/v1\/systemone\/?$/, ""), { headers: NGROK }).catch(() => ({}));
    const m = s.models?.[0] || {};
    return { provider: "systemone", checkpoint: m.checkpoint || null, temperature: m.temperature ?? null, model: cfg.model || m.name || null };
  },
};
