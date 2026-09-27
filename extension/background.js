// One local server owns one personal brain. Requests never select another user.
const GATE = "http://127.0.0.1:8790";
const seen = new Map();
const navigation = new Map();
const openOnce = new Map();
let taskVersion = 0;
let changingTask = false;

async function gate(path, body) {
  const response = await fetch(`${GATE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(30000),
  });
  const result = await response.json();
  if (!response.ok) throw new Error(result.error || "Gate unavailable");
  return result;
}

chrome.webNavigation.onCommitted.addListener(async ({ tabId, url, frameId }) => {
  if (frameId !== 0) return;
  const visit = (navigation.get(tabId) || 0) + 1;
  navigation.set(tabId, visit);
  const version = taskVersion;
  if (!/^https?:/.test(url)) {
    seen.delete(tabId);
    return;
  }
  if (changingTask) return;
  const permit = openOnce.get(tabId);
  openOnce.delete(tabId);
  if (permit && permit.url === url && permit.version === version && permit.expires > Date.now()) {
    seen.delete(tabId); // The next visit must be judged again, even for this URL.
    return;
  }
  seen.set(tabId, url);
  let title = "";
  try { title = (await chrome.tabs.get(tabId)).title || ""; } catch { return; }
  let decision;
  try { decision = await gate("/", { url, title }); }
  catch (error) { seen.delete(tabId); console.warn("Gate unavailable", error.message); return; }
  // River may reply after a later navigation or a task change. Never redirect it.
  if (navigation.get(tabId) !== visit || taskVersion !== version || seen.get(tabId) !== url) return;
  let current;
  try { current = await chrome.tabs.get(tabId); } catch { return; }
  if (current.url !== url || (current.pendingUrl && current.pendingUrl !== url)) return;
  await chrome.storage.local.set({ last: { url, title, ...decision, at: Date.now() } });
  if (navigation.get(tabId) !== visit || taskVersion !== version) return;
  if (decision.lock) {
    try { current = await chrome.tabs.get(tabId); } catch { return; }
    if (navigation.get(tabId) !== visit || taskVersion !== version || current.url !== url
      || (current.pendingUrl && current.pendingUrl !== url)) return;
    const query = new URLSearchParams({ p: decision.p, u: url, t: title, task: decision.task });
    await chrome.tabs.update(tabId, { url: chrome.runtime.getURL(`lock.html?${query}`) });
  }
});

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (!["setTask", "override"].includes(message.type)) return;
  (async () => {
    if (message.type === "setTask") {
      taskVersion += 1;
      seen.clear();
      openOnce.clear();
      changingTask = true;
      try {
        const result = await gate("/task", { task: message.task });
        await chrome.storage.local.remove("last");
        return { ok: true, ...result };
      } finally { changingTask = false; }
    }
    if (!sender.tab || !sender.url?.startsWith(chrome.runtime.getURL("lock.html?"))) {
      throw new Error("Open the page from its Floodgate lock screen");
    }
    const target = new URL(message.url);
    if (!["http:", "https:"].includes(target.protocol)) throw new Error("Invalid page URL");
    const version = taskVersion;
    const result = await gate("/override", {
      url: message.url, title: message.title, task: message.task,
      label: 0.0, model_p: message.p,
    });
    if (version !== taskVersion) throw new Error("Task changed; reopen the page for your new task");
    const current = await chrome.tabs.get(sender.tab.id);
    if (current.url !== sender.url) throw new Error("Page changed before the correction was saved");
    openOnce.set(sender.tab.id, { url: message.url, version, expires: Date.now() + 15000 });
    seen.delete(sender.tab.id);
    await chrome.tabs.update(sender.tab.id, { url: message.url });
    return { ok: true, ...result };
  })().then(respond).catch(error => respond({ ok: false, error: error.message }));
  return true;
});

chrome.tabs.onRemoved.addListener(tabId => {
  seen.delete(tabId);
  navigation.delete(tabId);
  openOnce.delete(tabId);
});
