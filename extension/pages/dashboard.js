import { ALWAYS_ALLOW, MODES } from "../lib/config.js";
import { heuristicScore } from "../lib/heuristic.js";
import { labelWord } from "../lib/memory.js";
import { buildCard, cardLabels, parseCard } from "../lib/modelcard.js";
import { labelToRow, toJsonl } from "../lib/rows.js";
import { download, getLabels, getLog, getSettings, getStats, setLabels, setSettings } from "../lib/store.js";
import { canonicalUrl, domainOf, matchesDomain, taskSimilarity } from "../lib/text.js";
import { byId, PROVIDERS, providerConfig } from "../providers/index.js";

const $ = (id) => document.getElementById(id);
const send = (msg) => chrome.runtime.sendMessage(msg);

function el(tag, props = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(props)) {
    if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (k in e) e[k] = v;
    else e.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null && kid !== false) e.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return e;
}
const hhmm = (ts) => new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const when = (ts) => new Date(ts).toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
const pct = (p) => (p == null ? "–" : `${Math.round(p * 100)}%`);
const VERDICT = { block: "Blocked", nudge: "Asked", allow: "Allowed" };
function flash(id, text, ok = true) {
  $(id).textContent = text;
  $(id).className = `msg ${ok ? "ok" : "bad"}`;
}

// ---------------- routing ----------------
const SECTIONS = ["overview", "teach", "model", "share"];
let section = "overview";
function route() {
  const h = location.hash.slice(1) || "overview";
  section = SECTIONS.includes(h) ? h : "overview";
  for (const s of SECTIONS) $(s).classList.toggle("on", s === section);
  document.querySelectorAll("nav a").forEach((a) => (a.getAttribute("href") === `#${section}` ? a.setAttribute("aria-current", "page") : a.removeAttribute("aria-current")));
  if (h === "welcome") $("welcome").hidden = false;
}
window.addEventListener("hashchange", route);

// ---------------- status pill ----------------
async function renderStatus() {
  const s = await getSettings();
  const h = await send({ type: "fg:health" });
  const st = $("status");
  st.className = `pill status ${s.provider === "heuristic" ? "warn" : h.ok ? "ok" : "bad"}`;
  st.lastChild.textContent = s.provider === "heuristic" ? "Offline heuristic" : h.ok ? `${h.name} · online` : `${h.name} · offline`;
  st.title = h.detail || "";
}

// ---------------- overview ----------------
function modeButtons(container, hint, current) {
  container.replaceChildren(
    ...Object.entries(MODES).map(([id, m]) =>
      el("button", { type: "button", role: "radio", "aria-checked": String(current === id), onclick: () => setSettings({ mode: id }).then(renderAll) }, m.label),
    ),
  );
  hint.textContent = MODES[current]?.hint || "";
}

async function renderOverview() {
  const [s, stats, log, labels] = await Promise.all([getSettings(), getStats(), getLog(), getLabels()]);
  if (!s.onboarded) $("welcome").hidden = false;
  if (document.activeElement !== $("wTask")) $("wTask").value = s.task;
  modeButtons($("wModes"), $("wModeHint"), s.mode);
  $("sChecked").textContent = stats.checked;
  $("sBlocked").textContent = stats.blocked;
  $("sNudged").textContent = stats.nudged;
  $("sLabels").textContent = labels.length;

  const rows = log.slice(-60).reverse();
  $("logEmpty").hidden = rows.length > 0;
  $("log").replaceChildren(
    ...rows.map((e) => {
      const relabel = (label) => async (ev) => {
        await send({ type: "fg:label", page: { url: e.url, title: e.title }, label, kind: "review", task: e.task, decision: e });
        ev.target.closest("td").replaceChildren(el("span", { className: "tiny faint" }, `labelled ${labelWord(label)}`));
      };
      return el(
        "tr",
        {},
        el("td", { className: "tiny dim" }, hhmm(e.ts)),
        el("td", { className: "page" }, el("b", { title: e.title || e.url }, e.title || e.url), el("span", { className: "tiny faint", title: e.reason || "" }, `${e.domain} · ${e.reason || ""}`)),
        el("td", { className: "num" }, pct(e.p)),
        el("td", {}, el("span", { className: `pill ${e.action}` }, VERDICT[e.action] || e.action)),
        el("td", { className: "tiny dim" }, e.source, e.ms ? ` · ${e.ms} ms` : ""),
        el(
          "td",
          { className: "acts" },
          e.task && e.p != null
            ? [el("button", { className: "good", title: "On task", onclick: relabel(0) }, "✓"), " ", el("button", { className: "bad", title: "Distraction", onclick: relabel(1) }, "✗")]
            : null,
        ),
      );
    }),
  );
}

$("wTaskForm").onsubmit = async (e) => {
  e.preventDefault();
  if ($("wTask").value.trim()) await setSettings({ task: $("wTask").value.trim() });
  renderAll();
};
$("wDone").onclick = async () => {
  await setSettings({ onboarded: true });
  $("welcome").hidden = true;
  history.replaceState(null, "", "#overview");
};

// ---------------- teach ----------------
let queue = [];
let qi = 0;
const undo = [];
let taught = 0;

async function loadHistory() {
  const task = $("tTask").value.trim();
  if (!task) {
    $("tQueue").replaceChildren(el("div", { className: "empty" }, "Type the task these visits should be judged against first."));
    return $("tTask").focus();
  }
  const [s, labels] = await Promise.all([getSettings(), getLabels()]);
  const days = Number($("tRange").value);
  const items = await chrome.history.search({ text: "", startTime: Date.now() - days * 864e5, maxResults: 10000 });
  const done = new Set(labels.filter((l) => taskSimilarity(l.task, task) >= 0.5).map((l) => l.url));
  const seen = new Map();
  for (const it of items) {
    if (!/^https?:/.test(it.url) || !it.title) continue;
    const domain = domainOf(it.url);
    if (matchesDomain(domain, [...ALWAYS_ALLOW, ...s.allowDomains])) continue;
    const key = canonicalUrl(it.url);
    if (done.has(key)) continue;
    if (seen.has(key)) {
      seen.get(key).visits += it.visitCount || 1;
      continue;
    }
    const { p, reason } = heuristicScore({ url: it.url, title: it.title }, { task, profile: s.profile, mode: s.mode });
    seen.set(key, { url: it.url, title: it.title, domain, visits: it.visitCount || 1, last: it.lastVisitTime, p, reason });
  }
  // Least certain first: those labels teach the model the most.
  queue = [...seen.values()].sort((a, b) => Math.abs(a.p - 0.5) - Math.abs(b.p - 0.5)).slice(0, 400);
  qi = 0;
  renderQueue();
}

function renderQueue() {
  const box = $("tQueue");
  if (!queue.length) return box.replaceChildren(el("div", { className: "empty" }, "No unlabelled pages in that range. Try a longer range or another task."));
  if (qi >= queue.length) return box.replaceChildren(el("div", { className: "empty" }, `All done: ${taught} labelled. Download them under Share → Training data.`));
  const it = queue[qi];
  const cls = it.p >= 0.7 ? "block" : it.p >= 0.5 ? "nudge" : "allow";
  box.replaceChildren(
    el(
      "div",
      { className: "spread" },
      el("span", { className: `pill ${cls}` }, `Floodgate guesses ${pct(it.p)} distraction`),
      el("span", { className: "tiny faint" }, `${qi + 1} of ${queue.length} · ${taught} labelled`),
    ),
    el("div", { className: "t" }, it.title),
    el("a", { className: "u", href: it.url, target: "_blank", rel: "noreferrer" }, it.url.slice(0, 160)),
    el("div", { className: "small dim", style: "margin-top:8px" }, `${it.visits} visit${it.visits === 1 ? "" : "s"} · last ${when(it.last)} · ${it.reason}`),
    el(
      "div",
      { className: "answers" },
      el("button", { className: "good", onclick: () => answer(0) }, el("kbd", {}, "1"), "On task"),
      el("button", { className: "bad", onclick: () => answer(1) }, el("kbd", {}, "2"), "Distraction"),
      el("button", { onclick: () => answer(0.5) }, el("kbd", {}, "3"), "It depends"),
      el("button", { className: "ghost", onclick: () => skip() }, el("kbd", {}, "Space"), "Skip"),
    ),
  );
}

async function answer(label) {
  const it = queue[qi];
  if (!it) return;
  const r = await send({ type: "fg:label", page: { url: it.url, title: it.title }, label, kind: "teach", task: $("tTask").value.trim(), decision: { p: it.p } });
  undo.push({ qi, id: r?.label?.id });
  taught++;
  qi++;
  renderQueue();
  renderLabels();
}
function skip() {
  undo.push({ qi, id: null });
  qi++;
  renderQueue();
}
async function undoLast() {
  const u = undo.pop();
  if (!u) return;
  if (u.id) {
    await setLabels((await getLabels()).filter((l) => l.id !== u.id));
    taught--;
  }
  qi = u.qi;
  renderQueue();
  renderLabels();
}

document.addEventListener("keydown", (e) => {
  if (section !== "teach" || e.metaKey || e.ctrlKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target.tagName)) return;
  const k = e.key.toLowerCase();
  if (k === "1") answer(0);
  else if (k === "2") answer(1);
  else if (k === "3") answer(0.5);
  else if (k === " ") {
    e.preventDefault();
    skip();
  } else if (k === "z" || k === "backspace") undoLast();
});
$("tLoad").onclick = loadHistory;

async function renderLabels() {
  const labels = await getLabels();
  $("lCount").textContent = `${labels.length} total · ${new Set(labels.map((l) => l.task)).size} tasks`;
  $("labelsEmpty").hidden = labels.length > 0;
  $("labels").replaceChildren(
    ...labels
      .slice(-50)
      .reverse()
      .map((l) =>
        el(
          "tr",
          {},
          el("td", { className: "tiny dim" }, when(l.ts)),
          el("td", { className: "page" }, el("b", { title: l.title || l.url }, l.title || l.url), el("span", { className: "tiny faint" }, l.scope === "domain" ? `all of ${l.domain}` : l.domain)),
          el("td", { className: "small dim" }, l.task || "–"),
          el("td", {}, el("span", { className: `pill ${l.label <= 0.3 ? "allow" : l.label >= 0.7 ? "block" : "nudge"}` }, labelWord(l.label)), l.source ? el("div", { className: "tiny faint" }, l.source) : null),
          el(
            "td",
            { className: "acts" },
            el(
              "button",
              {
                className: "ghost",
                title: "Delete label",
                onclick: async () => {
                  await setLabels((await getLabels()).filter((x) => x.id !== l.id));
                  renderLabels();
                },
              },
              "×",
            ),
          ),
        ),
      ),
  );
}

// ---------------- model ----------------
async function renderModel() {
  const s = await getSettings();
  $("providers").replaceChildren(
    ...PROVIDERS.filter((p) => p.classify).map((p) => {
      const cfg = providerConfig(p, s);
      const msg = el("div", { className: "msg" });
      const inputs = (p.settings || []).map((f) =>
        el(
          "label",
          {},
          f.label,
          el("input", {
            type: f.type || "text",
            value: cfg[f.key] ?? "",
            onchange: async (e) => {
              const cur = await getSettings();
              const ps = { ...cur.providerSettings, [p.id]: { ...(cur.providerSettings[p.id] || {}), [f.key]: f.type === "number" ? Number(e.target.value) : e.target.value } };
              await setSettings({ providerSettings: ps });
              msg.textContent = "Saved.";
              msg.className = "msg ok";
            },
          }),
        ),
      );
      const test = el(
        "button",
        {
          onclick: async () => {
            msg.textContent = "Testing…";
            msg.className = "msg";
            try {
              const h = await p.health(providerConfig(p, await getSettings()));
              msg.textContent = `${h.ok ? "Connected" : "Problem"}: ${h.detail}`;
              msg.className = `msg ${h.ok ? "ok" : "bad"}`;
            } catch (e) {
              msg.textContent = `Can't reach it: ${e.message}`;
              msg.className = "msg bad";
            }
          },
        },
        "Test connection",
      );
      return el(
        "div",
        { className: `card provider ${s.provider === p.id ? "on" : ""}` },
        el("input", { type: "radio", name: "provider", id: `p-${p.id}`, checked: s.provider === p.id, onchange: () => setSettings({ provider: p.id }).then(renderAll) }),
        el("label", { htmlFor: `p-${p.id}` }, el("b", {}, p.name), el("div", { className: "small dim" }, p.description)),
        p.settings?.length ? el("div", { className: "fields" }, inputs, p.health ? el("div", { className: "inline" }, test) : null, msg) : null,
      );
    }),
  );

  const enrichers = PROVIDERS.filter((p) => p.enrich);
  $("enrichers").replaceChildren(
    ...(enrichers.length
      ? enrichers.map((p) =>
          el(
            "label",
            { className: "inline", style: "margin-top:6px" },
            el("input", { type: "checkbox", checked: !!s.enrichers[p.id], onchange: async (e) => setSettings({ enrichers: { ...(await getSettings()).enrichers, [p.id]: e.target.checked } }) }),
            el("span", {}, el("b", {}, p.name), " ", el("span", { className: "small dim" }, p.description)),
          ),
        )
      : [el("div", { className: "small faint" }, "None installed yet.")]),
  );

  if (document.activeElement !== $("profile")) $("profile").value = s.profile;
  $("sendLabels").checked = s.sendLabels;
  $("allow").value = s.allowDomains.join("\n");
  $("block").value = s.blockDomains.join("\n");
  $("modesTable").replaceChildren(
    ...Object.entries(MODES).map(([id, m]) =>
      el(
        "tr",
        {},
        el("td", {}, el("b", {}, m.label), el("div", { className: "tiny faint" }, m.hint)),
        el("td", {}, m.blockAt === Infinity ? "never" : pct(m.blockAt)),
        el("td", {}, m.nudgeAt === Infinity ? "never" : pct(m.nudgeAt)),
        el("td", {}, s.mode === id ? el("span", { className: "pill allow" }, "on") : el("button", { onclick: () => setSettings({ mode: id }).then(renderAll) }, "Use")),
      ),
    ),
  );
}

const domains = (text) =>
  [...new Set(text.split(/[\s,]+/).map((d) => d.trim().toLowerCase().replace(/^https?:\/\//, "").replace(/^www\./, "").replace(/\/.*$/, "")).filter(Boolean))];
$("saveRules").onclick = async () => {
  await setSettings({ allowDomains: domains($("allow").value), blockDomains: domains($("block").value) });
  flash("rulesMsg", "Saved. Open tabs were re-checked.");
  renderModel();
};
$("saveProfile").onclick = async () => {
  await setSettings({ profile: $("profile").value.trim(), sendLabels: $("sendLabels").checked });
  flash("profileMsg", "Saved.");
};

// ---------------- share ----------------
async function backendInfo(s) {
  const p = byId(s.provider);
  if (!p?.describe) return { provider: s.provider };
  try {
    return await p.describe(providerConfig(p, s));
  } catch {
    return { provider: s.provider };
  }
}

$("cExport").onclick = async () => {
  const [s, labels] = await Promise.all([getSettings(), getLabels()]);
  const card = buildCard({
    name: $("cName").value.trim(),
    author: $("cAuthor").value.trim(),
    description: $("cDesc").value.trim(),
    settings: s,
    labels,
    includeExamples: $("cExamples").checked,
    backend: await backendInfo(s),
  });
  const slug = card.name.toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "model";
  download(`floodgate-model-${slug}.json`, JSON.stringify(card, null, 2));
  flash("cMsg", `Downloaded: ${card.stats.labels} labels${card.examples.length ? " included" : " (not included)"}, ${card.backend.checkpoint ? "with your River checkpoint" : "no River checkpoint (connect your gate server to include it)"}.`);
};

let pendingCard = null;
$("cFile").onchange = async (e) => {
  const f = e.target.files[0];
  if (!f) return;
  try {
    pendingCard = parseCard(await f.text());
    const c = pendingCard;
    $("cPreviewText").textContent = [
      `${c.name}${c.author ? ` by ${c.author}` : ""}`,
      c.description,
      `model: ${c.backend?.checkpoint ? `${c.backend.checkpoint} (T=${c.backend.temperature})` : "no checkpoint (rules and examples only)"}`,
      `examples: ${c.examples.length}   tasks: ${(c.tasks || []).join(" | ") || "–"}`,
      `mode: ${c.mode || "–"}   about me: ${c.profile || "–"}`,
      `always allow: ${c.rules.allow.join(", ") || "–"}`,
      `always block: ${c.rules.block.join(", ") || "–"}`,
    ]
      .filter(Boolean)
      .join("\n");
    $("cUseModel").parentElement.hidden = !c.backend?.checkpoint;
    $("cPreview").hidden = false;
    $("cImportMsg").textContent = "";
  } catch (err) {
    pendingCard = null;
    $("cPreview").hidden = true;
    flash("cImportMsg", err.message, false);
  }
};

$("cApply").onclick = async () => {
  const c = pendingCard;
  if (!c) return;
  const [s, labels, { cards = [] }] = await Promise.all([getSettings(), getLabels(), chrome.storage.local.get("cards")]);
  const source = `import:${c.name}`;
  await setLabels([...labels.filter((l) => l.source !== source), ...cardLabels(c)]);
  const patch = {
    allowDomains: [...new Set([...s.allowDomains, ...c.rules.allow])],
    blockDomains: [...new Set([...s.blockDomains, ...c.rules.block])],
  };
  if ($("cUseMode").checked) Object.assign(patch, { mode: MODES[c.mode] ? c.mode : s.mode, profile: c.profile || s.profile });
  await setSettings(patch);
  let note = "";
  if (c.backend?.checkpoint && $("cUseModel").checked) {
    const gate = byId("floodgate-gate");
    try {
      await gate.applyModel(c.backend, providerConfig(gate, await getSettings()));
      if (s.provider !== "floodgate-gate") await setSettings({ provider: "floodgate-gate" });
      note = " Your gate server now runs their checkpoint.";
    } catch (err) {
      note = ` Could not load the checkpoint into the gate server (${err.message}). Start it with --checkpoint ${c.backend.checkpoint} --temperature ${c.backend.temperature}.`;
    }
  }
  await chrome.storage.local.set({ cards: [...cards.filter((x) => x.name !== c.name), { name: c.name, author: c.author, examples: c.examples.length, backend: c.backend, at: Date.now() }] });
  flash("cImportMsg", `Added “${c.name}”: ${c.examples.length} examples, ${c.rules.allow.length + c.rules.block.length} rules.${note}`, !note.includes("Could not"));
  $("cPreview").hidden = true;
  $("cFile").value = "";
  renderAll();
};

async function renderImported() {
  const { cards = [] } = await chrome.storage.local.get("cards");
  $("imported").replaceChildren(
    ...(cards.length
      ? cards.map((c) =>
          el(
            "div",
            { className: "spread", style: "padding:6px 0;border-bottom:1px solid var(--line)" },
            el("span", {}, el("b", {}, c.name), c.author ? ` by ${c.author}` : "", ` · ${c.examples} examples${c.backend?.checkpoint ? " · checkpoint" : ""}`),
            el(
              "button",
              {
                className: "ghost",
                onclick: async () => {
                  await setLabels((await getLabels()).filter((l) => l.source !== `import:${c.name}`));
                  await chrome.storage.local.set({ cards: cards.filter((x) => x.name !== c.name) });
                  renderAll();
                },
              },
              "Remove",
            ),
          ),
        )
      : ["None yet."]),
  );
}

$("dRows").onclick = async () => {
  const labels = (await getLabels()).filter((l) => $("dShared").checked || !l.source);
  if (!labels.length) return flash("dMsg", "No labels yet. Label pages from the block screen, the popup, or the Teach tab.", false);
  download("floodgate-labels.jsonl", toJsonl(labels.map(labelToRow)), "application/x-ndjson");
  flash("dMsg", `Downloaded ${labels.length} rows.`);
};
$("dHistory").onclick = async () => {
  const items = await chrome.history.search({ text: "", startTime: Date.now() - 30 * 864e5, maxResults: 20000 });
  const rows = items.filter((i) => /^https?:/.test(i.url)).map(({ url, title, lastVisitTime, visitCount }) => ({ url, title, lastVisitTime, visitCount }));
  download("floodgate-history.json", JSON.stringify(rows, null, 1));
  flash("dMsg", `Downloaded ${rows.length} history entries (last 30 days). Unlabelled; label them in Teach first for training.`);
};
$("rLog").onclick = async () => {
  if (!confirm("Clear the decision log?")) return;
  await chrome.storage.local.set({ log: [] });
  renderAll();
};
$("rLabels").onclick = async () => {
  if (!confirm("Delete all labels? Download them first if you want to train on them.")) return;
  await setLabels([]);
  renderAll();
};

// ---------------- boot ----------------
async function renderAll() {
  await Promise.all([renderOverview(), renderLabels(), renderModel(), renderImported(), renderStatus()]);
}
chrome.storage.onChanged.addListener((changes) => {
  if (changes.log || changes.stats) renderOverview();
  if (changes.settings) renderStatus();
});

route();
const s0 = await getSettings();
$("tTask").value = s0.task;
await renderAll();
