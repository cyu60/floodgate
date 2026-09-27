// Share your model: a small JSON "model card" = your River checkpoint + calibration temperature (the trained model),
// your rules and mode, and optionally your labelled examples. A teammate imports it and gets your judgment.
import { QUESTION } from "./config.js";

export const CARD_VERSION = 1;

export function buildCard({ name, author, description, settings, labels, includeExamples, backend }) {
  const own = labels.filter((l) => !l.source);
  return {
    floodgate_model_card: CARD_VERSION,
    // Top level too, so `python -m floodgate.gate_server --run <this card>` serves the same model.
    ...(backend?.checkpoint ? { checkpoint: backend.checkpoint, temperature: backend.temperature ?? 1.0 } : {}),
    name: name || "My Floodgate model",
    author: author || "",
    description: description || "",
    created: new Date().toISOString(),
    question: QUESTION,
    backend: backend || { provider: settings.provider },
    mode: settings.mode,
    profile: settings.profile,
    tasks: [...new Set(own.map((l) => l.task).filter(Boolean))],
    rules: { allow: settings.allowDomains, block: settings.blockDomains },
    examples: includeExamples ? own.map(({ url, domain, title, task, label, scope, ts }) => ({ url, domain, title, task, label, scope, ts })) : [],
    stats: { labels: own.length },
  };
}

export function parseCard(text) {
  let card;
  try {
    card = JSON.parse(text);
  } catch {
    throw new Error("That file is not JSON.");
  }
  if (card?.floodgate_model_card === undefined && typeof card?.checkpoint === "string") card = fromRunCard(card);
  if (card?.floodgate_model_card !== CARD_VERSION) throw new Error("Not a Floodgate model card (missing floodgate_model_card: 1, or a River run with a checkpoint).");
  card.name = String(card.name || "Shared model").slice(0, 80);
  card.examples = Array.isArray(card.examples) ? card.examples.filter((e) => e && typeof e.url === "string" && typeof e.label === "number") : [];
  card.rules = { allow: [].concat(card.rules?.allow || []).map(String), block: [].concat(card.rules?.block || []).map(String) };
  return card;
}

// A River training run / model card from the repo (models/*.json, data/runs/*.json): checkpoint + temperature + evals.
function fromRunCard(run) {
  const acc = run.eval?.trained?.test_cal?.accuracy ?? run.eval?.trained?.test?.accuracy;
  return {
    floodgate_model_card: CARD_VERSION,
    name: run.name || "River model",
    author: run.author || "",
    description: acc != null ? `River-trained open Jev, ${Math.round(acc * 1000) / 10}% on Open-Jev test` : "River-trained open Jev",
    backend: { provider: "floodgate-gate", checkpoint: run.checkpoint, temperature: run.temperature ?? 1.0, base_model: run.base || null },
    rules: {},
    examples: [],
  };
}

/** Examples from a card, as labels tagged with their source so they can be removed again. */
export function cardLabels(card) {
  return card.examples.map((e) => ({
    id: crypto.randomUUID(),
    ts: e.ts || Date.now(),
    url: e.url,
    domain: e.domain || "",
    title: e.title || "",
    task: e.task || "",
    label: Math.min(1, Math.max(0, e.label)),
    scope: e.scope === "domain" ? "domain" : "url",
    kind: "import",
    source: `import:${card.name}`,
  }));
}
