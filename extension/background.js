// Service worker. content.js reports every page (full loads and YouTube-style in-app navigations) with its real
// title; we decide, cache, log, badge the icon, and answer with allow / nudge / block for content.js to enforce.
import { broadcastContext, broadcastLabel, classify, providerHealth } from "./lib/classifier.js";
import { MODES } from "./lib/config.js";
import { addLabel, appendLog, bumpStat, getLabels, getSettings, getStats, setSettings } from "./lib/store.js";
import { canonicalUrl } from "./lib/text.js";

const CACHE_MS = 10 * 60 * 1000;
const cache = new Map(); // "provider|mode|task|profile|url" -> {d, at}
const inflight = new Map(); // same key -> Promise, so a double report costs one model call

const cacheKey = (s, url) => [s.provider, s.mode, s.task, s.profile, canonicalUrl(url)].join("|");

// ---- per-tab state and temporary passes, in storage.session so they survive service-worker restarts ----
const tabKey = (tabId) => `tab:${tabId}`;
async function getTab(tabId) {
  return (await chrome.storage.session.get(tabKey(tabId)))[tabKey(tabId)] || null;
}
const setTab = (tabId, v) => chrome.storage.session.set({ [tabKey(tabId)]: v });

async function passFor(url) {
  const { passes = {} } = await chrome.storage.session.get("passes");
  return passes[canonicalUrl(url)] > Date.now() ? passes[canonicalUrl(url)] : 0;
}
async function addPass(url, minutes) {
  const { passes = {} } = await chrome.storage.session.get("passes");
  const now = Date.now();
  for (const k of Object.keys(passes)) if (passes[k] < now) delete passes[k];
  passes[canonicalUrl(url)] = now + minutes * 60 * 1000;
  await chrome.storage.session.set({ passes });
}

// ---- badge: the percent on the toolbar icon, colored by the action ----
const COLORS = { block: "#e11d48", nudge: "#d97706", allow: "#059669", off: "#64748b" };
function setBadge(tabId, d, settings) {
  const off = settings.mode === "break" || settings.pausedUntil > Date.now() || d.p == null;
  const text = d.p == null ? "" : String(Math.round(d.p * 100));
  chrome.action.setBadgeText({ tabId, text }).catch(() => {});
  chrome.action.setBadgeBackgroundColor({ tabId, color: off ? COLORS.off : COLORS[d.action] }).catch(() => {});
}

async function decide(tabId, page) {
  const settings = await getSettings();
  const pass = await passFor(page.url);
  if (pass) {
    const until = new Date(pass).toTimeString().slice(0, 5);
    const d = { url: page.url, action: "allow", p: null, source: "pass", reason: `You let this page through until ${until}`, ms: 0 };
    await setTab(tabId, { page, decision: d });
    setBadge(tabId, d, settings);
    return d;
  }
  const key = cacheKey(settings, page.url);
  const hit = cache.get(key);
  let d;
  if (hit && Date.now() - hit.at < CACHE_MS) d = { ...hit.d, cached: true, ms: 0 };
  else {
    if (!inflight.has(key)) {
      const pending = () => chrome.tabs.sendMessage(tabId, { type: "fg:pending", url: page.url }).catch(() => {});
      const run = async () => {
        const d = await classify(page, settings, await getLabels(), { onPending: pending });
        // Offline fallbacks are not cached, so the model gets asked again as soon as it is back.
        if (!d.providerError) cache.set(key, { d, at: Date.now() });
        await appendLog({ ts: Date.now(), title: page.title, ...d });
        await bumpStat("checked");
        if (d.action === "block") await bumpStat("blocked");
        if (d.action === "nudge") await bumpStat("nudged");
        return d;
      };
      inflight.set(key, run().finally(() => inflight.delete(key)));
    }
    d = await inflight.get(key);
  }
  await setTab(tabId, { page, decision: d });
  setBadge(tabId, d, settings);
  return d;
}

async function recheckTabs({ all = false } = {}) {
  const tabs = await chrome.tabs.query({});
  for (const t of tabs) {
    const state = all || t.active ? null : await getTab(t.id);
    if (all || t.active || (state && state.decision?.action !== "allow")) chrome.tabs.sendMessage(t.id, { type: "fg:recheck" }).catch(() => {});
  }
}

// `task` is passed when labelling a past visit (dashboard log, Teach tab); otherwise the current task applies.
async function label({ page, label, kind, scope, decision, task }) {
  const settings = await getSettings();
  const l = await addLabel({
    page,
    label,
    kind,
    scope,
    task: task ?? settings.task,
    profile: settings.profile,
    mode: settings.mode,
    model_p: decision?.p ?? null,
  });
  cache.clear();
  broadcastLabel(l, settings).catch(() => {});
  return l;
}

const HANDLERS = {
  // from content.js
  "fg:classify": ({ page }, sender) => decide(sender.tab.id, page),
  "fg:label": async (msg) => ({ ok: true, label: await label(msg) }),
  "fg:allow": async ({ page, minutes }) => (await addPass(page.url, minutes), { ok: true }),
  "fg:setTask": async ({ task }) => (await setSettings({ task }), cache.clear(), { ok: true }),
  "fg:leave": async (_, sender) => {
    try {
      await chrome.tabs.goBack(sender.tab.id);
    } catch {
      await chrome.tabs.update(sender.tab.id, { url: "chrome://newtab/" });
    }
    return { ok: true };
  },
  "fg:openDashboard": async ({ hash = "" }) => (await chrome.tabs.create({ url: chrome.runtime.getURL(`pages/dashboard.html${hash}`) }), { ok: true }),

  // from the popup and dashboard
  "fg:state": async ({ tabId }) => {
    const settings = await getSettings();
    return { settings, stats: await getStats(), tab: tabId ? await getTab(tabId) : null, labels: (await getLabels()).length };
  },
  "fg:health": async () => providerHealth(await getSettings()),
  "fg:labelTab": async ({ tabId, label: value, scope }) => {
    const state = await getTab(tabId);
    if (!state?.page) throw new Error("No page decided in this tab yet");
    const l = await label({ page: state.page, label: value, kind: "popup", scope, decision: state.decision });
    chrome.tabs.sendMessage(tabId, { type: "fg:recheck" }).catch(() => {});
    return { ok: true, label: l };
  },
  "fg:recheck": async () => (cache.clear(), await recheckTabs({ all: true }), { ok: true }),
};

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  const handler = HANDLERS[msg?.type];
  if (!handler) return false;
  Promise.resolve(handler(msg, sender)).then(sendResponse, (e) => sendResponse({ error: String(e?.message || e) }));
  return true; // async response
});

// Settings are written by the popup, dashboard and overlay; react to any change in one place.
chrome.storage.onChanged.addListener((changes, area) => {
  if (area !== "local") return;
  if (changes.labels) cache.clear();
  if (!changes.settings) return;
  const before = changes.settings.oldValue || {};
  const after = changes.settings.newValue || {};
  const changed = (k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]);
  const decisive = ["task", "mode", "profile", "provider", "providerSettings", "enrichers", "allowDomains", "blockDomains", "pausedUntil"];
  if (!decisive.some(changed)) return;
  cache.clear();
  if (["task", "profile", "mode", "provider"].some(changed)) getSettings().then(broadcastContext).catch(() => {});
  recheckTabs({ all: changed("mode") || changed("pausedUntil") }).catch(() => {});
});

chrome.tabs.onRemoved.addListener((tabId) => chrome.storage.session.remove(tabKey(tabId)));

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "toggle-pause") return;
  const s = await getSettings();
  await setSettings({ pausedUntil: s.pausedUntil > Date.now() ? 0 : Date.now() + 15 * 60 * 1000 });
});

// When a pause ends, re-check open tabs so blocked pages lock again.
chrome.alarms.onAlarm.addListener((a) => a.name === "pause-end" && recheckTabs({ all: true }));
chrome.storage.onChanged.addListener((changes) => {
  const until = changes.settings?.newValue?.pausedUntil;
  if (until && until > Date.now()) chrome.alarms.create("pause-end", { when: until + 500 });
});

chrome.runtime.onInstalled.addListener(async ({ reason }) => {
  // Content scripts only arrive in tabs opened after install; inject them into the tabs already open.
  for (const t of await chrome.tabs.query({ url: ["http://*/*", "https://*/*"] })) {
    chrome.scripting.executeScript({ target: { tabId: t.id }, files: ["content.js"] }).catch(() => {});
  }
  if (reason === "install") chrome.tabs.create({ url: chrome.runtime.getURL("pages/dashboard.html#welcome") });
});

// Exposed for tests and the console: `await floodgate.decide(...)` in the service worker devtools.
globalThis.floodgate = { decide, cache, MODES };
