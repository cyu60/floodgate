// Export labels as Open-Jev noul rows, byte-for-byte the format of floodgate/prep_gate_dataset.py, so the
// River team can train on them directly:  python -m floodgate.open_jev.train --extra floodgate-labels.jsonl
import { QUESTION } from "./config.js";

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const pad = (n) => String(n).padStart(2, "0");

export function stateText({ url, title, ts, task, profile }) {
  const t = new Date(ts);
  let s = `URL: ${String(url).slice(0, 200)} Title: ${String(title || "").slice(0, 120)}. Time: ${pad(t.getHours())}:${pad(t.getMinutes())} ${DAYS[t.getDay()]}. Stated task: ${task || "deep work on the current project"}.`;
  if (profile) s += ` About me: ${profile}.`;
  return s;
}

export function labelToRow(l) {
  const p = Math.min(1, Math.max(0, Number(l.label)));
  return {
    state: stateText(l),
    question: QUESTION,
    kind: "noul",
    options: ["no", "yes"],
    target: [Math.round((1 - p) * 1000) / 1000, Math.round(p * 1000) / 1000],
    metadata: {
      url: l.url,
      domain: l.domain,
      scope: l.scope || "url",
      target_basis: l.source?.startsWith("import:") ? "shared" : "hand",
      label_kind: l.kind,
      mode: l.mode,
      model_p: l.model_p ?? null,
      visited: new Date(l.ts).toISOString(),
      source: l.source || "floodgate-extension",
    },
  };
}

export const toJsonl = (rows) => rows.map((r) => JSON.stringify(r)).join("\n") + (rows.length ? "\n" : "");
