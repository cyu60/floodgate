// TEMPLATE: copy this file to add your piece of Floodgate (GBrain memory, QM, a second River model, ...).
//
//   1. cp providers/_template.js providers/my-thing.js   and fill in the parts you need (delete the rest)
//   2. add it to PROVIDERS in providers/index.js
//   3. chrome://extensions -> Floodgate -> reload. It shows up in Dashboard -> Model.
//
// A provider can do any mix of four jobs. Floodgate calls only the methods you define:
//
//   classify(page, ctx, cfg) -> { p, reason?, model? }   DECIDE: P(distraction) for this page (0..1). Throw to fall back.
//   enrich(page, ctx, cfg)   -> { key: "text", ... }      CONTEXT: extra facts merged into the state the model sees
//                                                          (e.g. what GBrain knows you are working on). 2 s budget.
//   onLabel(label, ctx, cfg)                              LEARN: the user labelled a page (overrides, nudges, Teach tab).
//   onContext(ctx, cfg)                                   The task, mode or "about me" changed.
//   health(cfg) -> { ok, detail }                         Status dot + "Test connection" in the dashboard.
//
// page:  { url, title, description?, channel?, siteName?, keywords?, query? }   (query = search box text on search pages)
// ctx:   { task, profile, aboutMe, mode, time, extra }   aboutMe = profile + the mode's preset (creator mode adds one)
// label: { url, domain, title, task, label (0 on task, 1 distraction, 0.5 it depends), kind, scope, model_p, ts }
// cfg:   the values of `settings` below, as edited by the user in Dashboard -> Model
//
// Everything runs in the extension's service worker: use fetch(), no DOM. Host permissions already allow any URL.

export default {
  id: "my-provider", // unique, kebab-case; used as the storage key
  name: "My provider",
  description: "One line shown in Dashboard -> Model.",
  settings: [
    { key: "endpoint", label: "Endpoint", default: "http://127.0.0.1:9000" },
    { key: "apiKey", label: "API key", default: "", type: "password" },
  ],

  async classify(page, ctx, cfg) {
    const r = await fetch(`${cfg.endpoint}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ url: page.url, title: page.title, task: ctx.task, about_me: ctx.aboutMe }),
      signal: AbortSignal.timeout(10000),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const d = await r.json();
    return { p: d.p, reason: d.reason, model: "my model" };
  },

  async enrich(page, ctx, cfg) {
    return { current_project: "…" };
  },

  async onLabel(label, ctx, cfg) {},

  async health(cfg) {
    const r = await fetch(cfg.endpoint, { signal: AbortSignal.timeout(2500) });
    return { ok: r.ok, detail: `HTTP ${r.status}` };
  },
};
