// Every completed top-frame navigation -> POST {url,title} to the local gate -> redirect to lock.html if locked.
const GATE = "http://127.0.0.1:8790";
const seen = new Map(); // tabId -> last url decided

chrome.webNavigation.onCommitted.addListener(async ({ tabId, url, frameId }) => {
  if (frameId !== 0 || !/^https?:/.test(url) || seen.get(tabId) === url) return;
  seen.set(tabId, url);
  let title = "";
  try { title = (await chrome.tabs.get(tabId)).title || ""; } catch {}
  let d;
  try {
    const r = await fetch(GATE, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ url, title }) });
    d = await r.json();
  } catch (e) { console.warn("gate offline", e); return; }
  chrome.storage.local.set({ last: { url, title, ...d, at: Date.now() } });
  if (d.lock) {
    const lock = chrome.runtime.getURL(`lock.html?p=${d.p}&u=${encodeURIComponent(url)}&t=${encodeURIComponent(title)}&task=${encodeURIComponent(d.task)}`);
    chrome.tabs.update(tabId, { url: lock });
  }
});
