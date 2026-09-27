// Built-in, offline. Always available, and the fallback whenever the chosen provider is unreachable.
import { heuristicScore } from "../lib/heuristic.js";

export default {
  id: "heuristic",
  name: "Offline heuristic",
  description: "Built in, no server. Compares the page with your task, with domain and title cues. Good for demos and as the fallback.",
  settings: [],
  async classify(page, ctx) {
    const { p, reason } = heuristicScore(page, ctx);
    return { p, reason, model: "offline heuristic" };
  },
  async health() {
    return { ok: true, detail: "built in" };
  },
};
