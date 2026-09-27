// chrome.storage wrappers. Settings, labels, the decision log and today's stats all live in storage.local,
// so the popup, the dashboard and the service worker share one source of truth (and react to onChanged).
import { DEFAULT_SETTINGS } from "./config.js";
import { canonicalUrl, domainOf } from "./text.js";

const LOG_MAX = 300;

// Read-modify-write calls in one context run one at a time, so two tabs deciding at once cannot drop a log entry.
let chain = Promise.resolve();
const serial = (fn) => (...args) => {
  const run = chain.then(() => fn(...args));
  chain = run.catch(() => {});
  return run;
};

export async function getSettings() {
  const { settings } = await chrome.storage.local.get("settings");
  return { ...DEFAULT_SETTINGS, ...(settings || {}) };
}

export const setSettings = serial(async (patch) => {
  const next = { ...(await getSettings()), ...patch };
  if (patch.task !== undefined && patch.task.trim()) {
    next.recentTasks = [patch.task.trim(), ...next.recentTasks.filter((t) => t !== patch.task.trim())].slice(0, 6);
  }
  await chrome.storage.local.set({ settings: next });
  return next;
});

export async function getLabels() {
  const { labels } = await chrome.storage.local.get("labels");
  return labels || [];
}

/** Save one label. label: 0 = on task, 1 = distraction, 0.5 = it depends. */
export const addLabel = serial(async ({ page, label, task, profile, mode, kind, scope = "url", model_p = null, source }) => {
  const labels = await getLabels();
  const l = {
    id: crypto.randomUUID(),
    ts: Date.now(),
    url: canonicalUrl(page.url),
    domain: domainOf(page.url),
    title: page.title || "",
    task: task || "",
    profile: profile || "",
    mode,
    label,
    kind,
    scope,
    model_p,
    ...(source ? { source } : {}),
  };
  labels.push(l);
  await chrome.storage.local.set({ labels });
  await bumpStatNow("labels");
  return l;
});

export async function setLabels(labels) {
  await chrome.storage.local.set({ labels });
}

export async function getLog() {
  const { log } = await chrome.storage.local.get("log");
  return log || [];
}

export const appendLog = serial(async (entry) => {
  const log = await getLog();
  log.push(entry);
  await chrome.storage.local.set({ log: log.slice(-LOG_MAX) });
});

const today = () => new Date().toISOString().slice(0, 10);

export async function getStats() {
  const { stats } = await chrome.storage.local.get("stats");
  return stats?.day === today() ? stats : { day: today(), checked: 0, blocked: 0, nudged: 0, labels: 0 };
}

async function bumpStatNow(key) {
  const stats = await getStats();
  stats[key] = (stats[key] || 0) + 1;
  await chrome.storage.local.set({ stats });
}

export const bumpStat = serial(bumpStatNow);

export function download(filename, text, type = "application/json") {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([text], { type }));
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}
