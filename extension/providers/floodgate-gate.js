// The River-trained open Jev behind floodgate/gate_server.py (python -m floodgate.gate_server --run data/runs/…json).
// Contract (also served by tools/mock_gate.py for offline dev):
//   POST /          {url, title, task, about_me, mode, description, channel, query} -> {p, lock, task, ms}
//   POST /task      {task, profile}                                               (older servers read the task only from here)
//   POST /override  {url, title, label, model_p, task, ...}                       -> appended to data/gate_log.jsonl
//   POST /model     {checkpoint, temperature}                                      hot-swap to a shared model card
//   GET  /          {ok, task, threshold, checkpoint, temperature, ...}
// The server's own `lock` is ignored: Floodgate applies the thresholds of the mode you picked.
import { getJson, postJson, trimSlash } from "./http.js";

export default {
  id: "floodgate-gate",
  name: "River open Jev (gate server)",
  description: "Your own model, trained on River. Run: python -m floodgate.gate_server --run data/runs/<run>.json",
  settings: [
    { key: "endpoint", label: "Gate server URL", default: "http://127.0.0.1:8790" },
    { key: "timeoutMs", label: "Timeout (ms)", default: 15000, type: "number" },
  ],

  async classify(page, ctx, cfg) {
    const d = await postJson(
      trimSlash(cfg.endpoint) + "/",
      {
        url: page.url,
        title: page.title,
        task: ctx.task,
        about_me: ctx.aboutMe,
        mode: ctx.mode,
        description: page.description,
        channel: page.channel,
        query: page.query,
        extra: ctx.extra,
      },
      { timeoutMs: Number(cfg.timeoutMs) || 15000 },
    );
    return { p: Number(d.p), reason: d.reason, model: d.model || "River open Jev", serverMs: d.ms };
  },

  async onContext(ctx, cfg) {
    await postJson(trimSlash(cfg.endpoint) + "/task", { task: ctx.task || "deep work", profile: ctx.aboutMe }, { timeoutMs: 3000 });
  },

  async onLabel(l, ctx, cfg) {
    await postJson(
      trimSlash(cfg.endpoint) + "/override",
      { url: l.url, title: l.title, label: l.label, model_p: l.model_p, task: l.task, mode: l.mode, kind: l.kind, scope: l.scope, about_me: ctx.aboutMe },
      { timeoutMs: 5000 },
    );
  },

  async health(cfg) {
    const s = await getJson(trimSlash(cfg.endpoint) + "/");
    return { ok: true, detail: s.checkpoint ? `trained checkpoint · T=${s.temperature}` : s.mock ? "mock gate (no River)" : "base model (untrained)", info: s };
  },

  // For model cards: what to publish, and how to load someone else's.
  async describe(cfg) {
    const s = await getJson(trimSlash(cfg.endpoint) + "/");
    return { provider: "floodgate-gate", checkpoint: s.checkpoint || null, temperature: s.temperature ?? null, base_model: s.base_model || null };
  },

  async applyModel(backend, cfg) {
    return postJson(trimSlash(cfg.endpoint) + "/model", { checkpoint: backend.checkpoint, temperature: backend.temperature ?? 1.0 }, { timeoutMs: 5000 });
  },
};
