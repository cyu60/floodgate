// Personal memory: your labels act on the very next visit, before any retraining.
// Exact page or domain labels decide outright; pages with similar titles nudge the model's score.
import { canonicalUrl, domainOf, jaccard, keywords } from "./text.js";

export const labelWord = (p) => (p <= 0.3 ? "on task" : p >= 0.7 ? "a distraction" : "“it depends”");

/**
 * @param {{url:string,title?:string}} page
 * @param {{task?:string}} ctx
 * @param {Array<{url:string,domain:string,title?:string,task?:string,label:number,scope?:string,source?:string}>} labels oldest first
 * @returns {null | {p:number, confidence:number, reason:string}}
 */
export function recall(page, ctx, labels) {
  if (!labels?.length) return null;
  const key = canonicalUrl(page.url);
  const domain = domainOf(page.url);
  const taskKw = keywords(ctx.task);
  const titleKw = keywords(page.title);
  let exact = null;
  let dom = null;
  const near = [];
  for (const l of labels) {
    if (jaccard(keywords(l.task), taskKw) < 0.5) continue; // a label only counts for the same (or a very similar) task
    if (l.url === key) exact = l;
    else if (l.scope === "domain" && l.domain === domain) dom = l;
    else if (titleKw.size >= 2) {
      const s = jaccard(keywords(l.title), titleKw);
      if (s >= 0.5) near.push({ l, s });
    }
  }
  const who = (l) => (l.source?.startsWith("import:") ? `“${l.source.slice(7)}” (shared model) labelled` : "You labelled");
  if (exact) return { p: exact.label, confidence: 1, reason: `${who(exact)} this page ${labelWord(exact.label)}` };
  if (dom) return { p: dom.label, confidence: 0.95, reason: `${who(dom)} ${domain} ${labelWord(dom.label)}` };
  if (!near.length) return null;
  const w = near.reduce((a, n) => a + n.s, 0);
  const p = near.reduce((a, n) => a + n.s * n.l.label, 0) / w;
  const top = near.sort((a, b) => b.s - a.s)[0];
  return { p, confidence: Math.min(0.8, top.s * 0.8), reason: `Similar to “${(top.l.title || top.l.url).slice(0, 60)}”, labelled ${labelWord(top.l.label)}` };
}
