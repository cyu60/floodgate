// node --test extension/test     (pure modules only: no Chrome needed)
import assert from "node:assert/strict";
import { test } from "node:test";
import { MODES } from "../lib/config.js";
import { actionFor } from "../lib/classifier.js";
import { heuristicScore } from "../lib/heuristic.js";
import { recall } from "../lib/memory.js";
import { buildCard, cardLabels, parseCard } from "../lib/modelcard.js";
import { labelToRow, stateText } from "../lib/rows.js";
import { canonicalUrl, keywords, searchQuery } from "../lib/text.js";

const yt = (title, v = "abc") => ({ url: `https://www.youtube.com/watch?v=${v}`, title });
const decide = (page, ctx) => actionFor(heuristicScore(page, ctx).p, MODES[ctx.mode || "focus"]);

test("same site, different answer: on-task video passes, informative off-task video is blocked", () => {
  const ctx = { task: "research TypeSafe's Jev model for the hackathon", mode: "focus" };
  assert.equal(decide(yt("Jev in 100 Seconds"), ctx), "allow");
  assert.equal(decide(yt("How SpaceX launches satellites, explained"), ctx), "block");
  assert.equal(decide(yt("GTA 6 gameplay walkthrough part 1"), ctx), "block");
  assert.equal(decide({ url: "https://docs.typesafe.ai/noul", title: "Noul — TypeSafe Docs" }, ctx), "allow");
});

test("the task decides: the satellite video is on task when the task is about launches", () => {
  const ctx = { task: "report on launch failures", mode: "focus" };
  assert.equal(decide(yt("How SpaceX launches satellites, explained"), ctx), "allow");
});

test("creator mode: memes are work, unrelated explainers become ambiguous (asks instead of blocking)", () => {
  const ctx = { task: "plan this week's TikTok", mode: "creator" };
  assert.equal(decide(yt("Try not to laugh compilation #shorts"), ctx), "allow");
  assert.equal(decide(yt("How SpaceX launches satellites, explained"), ctx), "nudge");
  // the same meme video in focus mode is blocked
  assert.equal(decide(yt("Try not to laugh compilation #shorts"), { ...ctx, mode: "focus" }), "block");
});

test("an influencer profile works without picking creator mode", () => {
  const r = heuristicScore(yt("Viral dance challenge"), { task: "edit my next reel", profile: "I'm an influencer", mode: "focus" });
  assert.ok(r.signals.creator);
  assert.equal(actionFor(r.p, MODES.focus), "allow");
});

test("unknown sites and off-task searches are ambiguous, not blocked", () => {
  const ctx = { task: "finish the Floodgate chrome extension", mode: "focus" };
  assert.equal(decide({ url: "https://someblog.net/post/why-sourdough-rises", title: "Why sourdough rises" }, ctx), "nudge");
  assert.equal(decide({ url: "https://www.google.com/search?q=gta+6+release+date", title: "gta 6 release date - Google Search" }, ctx), "nudge");
  assert.equal(decide({ url: "https://developer.chrome.com/docs/extensions/mv3", title: "Chrome extensions Manifest V3" }, ctx), "allow");
});

test("research mode is lenient on off-task learning material", () => {
  const ctx = { task: "research Jev", mode: "research" };
  assert.equal(decide(yt("How SpaceX launches satellites, explained"), ctx), "nudge");
});

test("work tools stay open even when off topic", () => {
  assert.equal(decide({ url: "https://github.com/some/repo", title: "some/repo: a thing" }, { task: "write slides", mode: "focus" }), "allow");
});

test("text helpers", () => {
  assert.deepEqual([...keywords("Finishing the hackathons' demos")], ["hackathon", "demo"]);
  assert.equal(canonicalUrl("https://www.youtube.com/watch?v=xyz&t=42s&list=abc#c"), "https://www.youtube.com/watch?v=xyz");
  assert.equal(canonicalUrl("https://example.com/a?utm_source=x&id=3#top"), "https://example.com/a?id=3");
  assert.equal(searchQuery("https://www.google.com/search?q=river+ai&oq=r"), "river ai");
});

test("memory: an exact label decides, only for the same task; similar titles nudge", () => {
  const labels = [
    { url: canonicalUrl("https://www.youtube.com/watch?v=abc"), domain: "youtube.com", title: "Satellite launch explained", task: "research Jev", label: 0 },
    { url: "https://www.youtube.com/watch?v=zzz", domain: "youtube.com", title: "Rust borrow checker crash course", task: "research Jev", label: 1 },
  ];
  const exact = recall(yt("Satellite launch explained", "abc"), { task: "research Jev" }, labels);
  assert.equal(exact.p, 0);
  assert.equal(exact.confidence, 1);
  assert.equal(recall(yt("Satellite launch explained", "abc"), { task: "bake bread" }, labels), null);
  const near = recall(yt("Rust borrow checker crash course part 2", "qqq"), { task: "research Jev" }, labels);
  assert.ok(near.p > 0.9 && near.confidence < 0.95);
});

test("rows: same format as prep_gate_dataset.py", () => {
  const ts = new Date(2026, 8, 27, 14, 5).getTime(); // Sunday
  const row = labelToRow({ url: "https://www.youtube.com/watch?v=abc", domain: "youtube.com", title: "Jev in 100 Seconds", task: "research Jev", label: 0, ts, kind: "override" });
  assert.equal(row.state, "URL: https://www.youtube.com/watch?v=abc Title: Jev in 100 Seconds. Time: 14:05 Sunday. Stated task: research Jev.");
  assert.equal(row.question, "Is this page a distraction from the stated task?");
  assert.deepEqual(row.options, ["no", "yes"]);
  assert.deepEqual(row.target, [1, 0]);
  assert.equal(row.metadata.target_basis, "hand");
  assert.match(stateText({ url: "u", title: "t", ts, task: "x", profile: "I'm a creator" }), /About me: I'm a creator\.$/);
});

test("model cards round-trip, and examples are private unless opted in", () => {
  const settings = { provider: "floodgate-gate", mode: "creator", profile: "creator", allowDomains: ["figma.com"], blockDomains: ["netflix.com"] };
  const labels = [
    { url: "https://a.com/", domain: "a.com", title: "A", task: "t", label: 1, ts: 1 },
    { url: "https://b.com/", domain: "b.com", title: "B", task: "t", label: 0, ts: 2, source: "import:someone" },
  ];
  const backend = { provider: "floodgate-gate", checkpoint: "river://ckpt/1", temperature: 1.3 };
  const priv = buildCard({ name: "Mine", settings, labels, includeExamples: false, backend });
  assert.equal(priv.examples.length, 0);
  const card = parseCard(JSON.stringify(buildCard({ name: "Mine", settings, labels, includeExamples: true, backend })));
  assert.equal(card.examples.length, 1, "imported labels are not re-shared");
  assert.equal(card.backend.checkpoint, "river://ckpt/1");
  assert.equal(cardLabels(card)[0].source, "import:Mine");
  assert.throws(() => parseCard('{"hello": 1}'), /Not a Floodgate model card/);
});
