import { MODES } from "../lib/config.js";
import { getSettings, setSettings } from "../lib/store.js";

const $ = (id) => document.getElementById(id);
const send = (msg) => chrome.runtime.sendMessage(msg);
const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
const VERDICT = { block: "Blocked", nudge: "Asked you", allow: "Let through" };

function el(tag, attrs = {}, text = "") {
  const e = Object.assign(document.createElement(tag), attrs);
  if (text) e.textContent = text;
  return e;
}

async function render() {
  const st = await send({ type: "fg:state", tabId: tab?.id });
  const s = st.settings;

  if (document.activeElement !== $("task")) $("task").value = s.task;
  $("recent").replaceChildren(
    ...s.recentTasks.filter((t) => t !== s.task).slice(0, 4).map((t) => {
      const c = el("button", { className: "chip", type: "button", title: t }, t);
      c.onclick = () => setSettings({ task: t }).then(render);
      return c;
    }),
  );

  $("modes").replaceChildren(
    ...Object.entries(MODES).map(([id, m]) => {
      const b = el("button", { type: "button", role: "radio", title: m.hint }, m.label);
      b.setAttribute("aria-checked", String(s.mode === id));
      b.onclick = () => setSettings({ mode: id }).then(render);
      return b;
    }),
  );
  const mode = MODES[s.mode] || MODES.focus;
  $("modeHint").textContent =
    s.mode === "break" ? mode.hint : `${mode.hint} Blocks at ${Math.round(mode.blockAt * 100)}%, asks from ${Math.round(mode.nudgeAt * 100)}%.`;

  const paused = s.pausedUntil > Date.now();
  $("paused").style.display = paused ? "block" : "none";
  $("paused").textContent = paused ? `Paused until ${new Date(s.pausedUntil).toTimeString().slice(0, 5)}. Nothing is blocked.` : "";
  $("pause").textContent = paused ? "Resume" : "Pause 15 min";
  $("pause").onclick = () => setSettings({ pausedUntil: paused ? 0 : Date.now() + 15 * 60 * 1000 }).then(render);

  const d = st.tab?.decision;
  const page = st.tab?.page;
  const onWeb = /^https?:/.test(tab?.url || "");
  $("verdict").className = `pill ${d?.action || ""}`;
  $("verdict").textContent = d ? VERDICT[d.action] : onWeb ? "Not checked yet" : "Not a web page";
  $("pct").textContent = d?.p != null ? `${Math.round(d.p * 100)}%` : "";
  $("bar").className = d?.action || "";
  $("bar").style.width = d?.p != null ? `${Math.round(d.p * 100)}%` : "0";
  $("pageTitle").textContent = page ? page.title || page.url : onWeb ? "Reload the page to let Floodgate check it." : "Floodgate checks web pages only.";
  $("reason").textContent = d?.reason || "";
  $("source").textContent = d ? `${d.source}${d.ms ? ` · ${d.ms} ms` : ""}${d.cached ? " · cached" : ""}` : "";
  $("labelBtns").style.display = page && s.task ? "flex" : "none";

  $("stats").textContent = `Today: ${st.stats.checked} pages checked · ${st.stats.blocked} blocked · ${st.stats.nudged} asked · ${st.labels} labels saved`;
}

async function renderHealth() {
  const s = await getSettings();
  const h = await send({ type: "fg:health" });
  const status = $("status");
  if (s.provider === "heuristic") {
    status.className = "pill status warn";
    status.lastChild.textContent = "Offline heuristic";
    status.title = "Built-in rules. Connect your River model in Dashboard → Model.";
  } else {
    status.className = `pill status ${h.ok ? "ok" : "bad"}`;
    status.lastChild.textContent = h.ok ? "Your model · online" : /API key/.test(h.detail || "") ? "Add API key" : "Model offline";
    status.title = `${h.name}: ${h.detail}${h.ok ? "" : " (using the offline heuristic meanwhile)"}`;
  }
}

$("taskForm").onsubmit = async (e) => {
  e.preventDefault();
  await setSettings({ task: $("task").value.trim() });
  $("task").blur();
  render();
};

const labelTab = (label) => async () => {
  const r = await send({ type: "fg:labelTab", tabId: tab.id, label });
  if (r?.error) $("reason").textContent = r.error;
  setTimeout(render, 400);
};
$("onTask").onclick = labelTab(0);
$("distraction").onclick = labelTab(1);
$("dash").onclick = (e) => {
  e.preventDefault();
  chrome.runtime.openOptionsPage();
};

await render();
renderHealth();
if (!(await getSettings()).task) $("task").focus();
