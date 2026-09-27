// One decision per page: your rules -> your labels -> the chosen provider (falls back to the offline heuristic)
// -> the mode's thresholds. Runs in the service worker.
import { byId, PROVIDERS, providerConfig } from "../providers/index.js";
import { ALWAYS_ALLOW, MODES } from "./config.js";
import { heuristicScore } from "./heuristic.js";
import { recall } from "./memory.js";
import { domainOf, matchesDomain } from "./text.js";

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];
const pad = (n) => String(n).padStart(2, "0");
const round = (p) => Math.round(p * 1000) / 1000;

export function makeContext(settings) {
  const mode = MODES[settings.mode] || MODES.focus;
  const t = new Date();
  return {
    task: (settings.task || "").trim(),
    profile: settings.profile || "",
    aboutMe: [settings.profile, mode.profile].filter(Boolean).join(" "),
    mode: settings.mode,
    time: `${pad(t.getHours())}:${pad(t.getMinutes())} ${DAYS[t.getDay()]}`,
    extra: {},
  };
}

/** A site's front page ("/", "/index.html", YouTube's home) with no page-specific query. */
export function isLaunchPad(url) {
  try {
    const u = new URL(url);
    return /^\/(index\.html?)?$/i.test(u.pathname) && ![...u.searchParams.keys()].some((k) => /^(q|v|search_query|query|p|id)$/.test(k));
  } catch {
    return false;
  }
}

export const actionFor = (p, mode) => (p >= mode.blockAt ? "block" : p >= mode.nudgeAt ? "nudge" : "allow");

function withTimeout(promise, ms, what) {
  let timer;
  return Promise.race([promise, new Promise((_, reject) => (timer = setTimeout(() => reject(new Error(`${what} timed out`)), ms)))]).finally(() =>
    clearTimeout(timer),
  );
}

async function enrich(page, ctx, settings) {
  const on = PROVIDERS.filter((p) => p.enrich && settings.enrichers?.[p.id]);
  const parts = await Promise.allSettled(on.map((p) => withTimeout(p.enrich(page, ctx, providerConfig(p, settings)), 2000, p.name)));
  return Object.assign({}, ...parts.filter((r) => r.status === "fulfilled" && r.value).map((r) => r.value));
}

// Memory providers (GBrain, Memorable, ...): corrections remembered outside this browser. First confident hit wins.
async function remoteRecall(page, ctx, settings) {
  for (const p of PROVIDERS.filter((x) => x.recall && settings.enrichers?.[x.id])) {
    try {
      const r = await withTimeout(p.recall(page, ctx, providerConfig(p, settings)), 2500, p.name);
      if (r && typeof r.p === "number") return { ...r, source: r.source || p.name };
    } catch {
      // a memory that can't be reached just doesn't vote
    }
  }
  return null;
}

/**
 * @returns {Promise<{action:"allow"|"nudge"|"block", p:number|null, reason:string, source:string, ms:number, heuristic_p?:number, providerError?:string}>}
 */
export async function classify(page, settings, labels, { onPending } = {}) {
  const t0 = Date.now();
  const ctx = makeContext(settings);
  const mode = MODES[settings.mode] || MODES.focus;
  const domain = domainOf(page.url);
  const done = (d) => ({ url: page.url, domain, task: ctx.task, mode: settings.mode, ...d, ms: Date.now() - t0 });

  if (!/^https?:/.test(page.url)) return done({ action: "allow", p: null, source: "rules", reason: "Not a web page" });
  if (matchesDomain(domain, [...ALWAYS_ALLOW, ...settings.allowDomains])) return done({ action: "allow", p: 0, source: "your rules", reason: `${domain} is on your allow list` });
  if (settings.pausedUntil > Date.now()) {
    const until = new Date(settings.pausedUntil);
    return done({ action: "allow", p: null, source: "paused", reason: `Paused until ${pad(until.getHours())}:${pad(until.getMinutes())}` });
  }
  if (matchesDomain(domain, settings.blockDomains)) return done({ action: "block", p: 1, source: "your rules", reason: `${domain} is on your block list` });

  const heur = heuristicScore(page, ctx);
  const mem = recall(page, ctx, labels);
  let p = heur.p;
  let reason = heur.reason;
  let source = "offline heuristic";
  let error;

  const localHit = mem && mem.confidence >= 0.95;
  const launchPad = isLaunchPad(page.url);
  const remote = !localHit && !launchPad && ctx.task && settings.mode !== "break" ? await remoteRecall(page, ctx, settings) : null;

  if (localHit) {
    [p, reason, source] = [mem.p, mem.reason, "your labels"];
  } else if (launchPad) {
    // A site's home page is where you search for the thing you need (YouTube's home, a search box); judge what you open next.
    return done({ action: "allow", p: null, source: "rules", reason: "Home page: open so you can search. Floodgate checks what you open next." });
  } else if (remote) {
    [p, reason, source] = [remote.p, remote.reason, remote.source];
  } else {
    const provider = byId(settings.provider) || byId("heuristic");
    // Break mode and "no task yet" never block, so they never spend a model call.
    if (provider.id !== "heuristic" && settings.mode !== "break" && ctx.task) {
      if (heur.p >= mode.nudgeAt) onPending?.(); // hold likely distractions behind a veil while the model thinks
      try {
        const cfg = providerConfig(provider, settings);
        ctx.extra = await enrich(page, ctx, settings);
        const r = await withTimeout(provider.classify(page, ctx, cfg), (Number(cfg.timeoutMs) || 15000) + 500, provider.name);
        if (typeof r?.p !== "number" || Number.isNaN(r.p)) throw new Error(`${provider.name} returned no probability`);
        p = r.p;
        reason = r.reason || heur.reason;
        source = r.model || provider.name;
      } catch (e) {
        error = String(e?.message || e);
        source = `offline heuristic (${provider.name} unreachable)`;
      }
    }
    if (mem) {
      const w = mem.confidence * 0.6;
      p = (1 - w) * p + w * mem.p;
      reason = `${mem.reason} · ${reason}`;
    }
  }

  let action = actionFor(p, mode);
  if (settings.mode === "break") reason = `Break mode, nothing is blocked · ${reason}`;
  else if (!ctx.task && action !== "allow") {
    action = "allow";
    reason = "No task set, so nothing is blocked. Set one in the Floodgate popup.";
  }
  return done({ action, p: round(p), reason, source, heuristic_p: heur.p, ...(error ? { providerError: error } : {}) });
}

const listeners = (settings, method) => PROVIDERS.filter((p) => p[method] && (p.id === settings.provider || settings.enrichers?.[p.id]));

/** Tell the active provider (and enabled context providers) about a new label, e.g. POST /override on the gate. */
export async function broadcastLabel(label, settings) {
  if (!settings.sendLabels) return [];
  const ctx = makeContext(settings);
  return Promise.allSettled(listeners(settings, "onLabel").map((p) => p.onLabel(label, ctx, providerConfig(p, settings))));
}

export async function broadcastContext(settings) {
  const ctx = makeContext(settings);
  return Promise.allSettled(listeners(settings, "onContext").map((p) => p.onContext(ctx, providerConfig(p, settings))));
}

export async function providerHealth(settings) {
  const provider = byId(settings.provider) || byId("heuristic");
  try {
    const h = await withTimeout(provider.health ? provider.health(providerConfig(provider, settings)) : Promise.resolve({ ok: true, detail: "" }), 3000, provider.name);
    return { id: provider.id, name: provider.name, ...h };
  } catch (e) {
    return { id: provider.id, name: provider.name, ok: false, detail: String(e?.message || e) };
  }
}
