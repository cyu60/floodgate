// Runs in every page (top frame). Reports the page with its settled title, including in-app navigations
// (YouTube, X, Reddit change the URL without reloading), and enforces the decision:
//   block -> full-screen shield, media paused     nudge -> "is this on task?" card     allow -> nothing
// All UI lives in a closed shadow root so page CSS cannot touch it; page text is only ever set via textContent.
(() => {
  const alive = () => {
    try {
      return !!chrome.runtime?.id;
    } catch {
      return false;
    }
  };
  if (window.top !== window || window.__floodgateAlive?.()) return;
  window.__floodgateAlive = alive;

  const GENERIC_TITLE = /^(youtube|x|twitter|reddit|instagram|tiktok|facebook|twitch|loading.*|untitled|new tab)?$/i;
  let lastUrl = null;
  let lastTitle = "";
  let seq = 0;
  let current = null; // {page, d}
  let ui = null;
  let recheckTimer = null;
  let awaiting = null; // URL whose decision is in flight; the "checking" veil is only shown for it

  const send = async (msg) => {
    if (!alive()) return null;
    try {
      return await chrome.runtime.sendMessage(msg);
    } catch {
      return null;
    }
  };
  const cleanTitle = (t) => (t || "").replace(/^\(\d+\+?\)\s*/, "").trim();
  const sameUrl = (a, b) => {
    try {
      const x = new URL(a, location.href), y = new URL(b, location.href);
      return x.origin + x.pathname + x.search === y.origin + y.pathname + y.search;
    } catch {
      return false;
    }
  };

  // ---- page facts ----
  function waitForTitle(prev, immediate) {
    return new Promise((resolve) => {
      const start = Date.now();
      const tick = () => {
        const t = cleanTitle(document.title);
        if (((immediate || t !== prev) && !GENERIC_TITLE.test(t)) || Date.now() - start > 2500) return resolve();
        setTimeout(tick, 150);
      };
      setTimeout(tick, immediate ? 0 : 300);
    });
  }

  function collect(firstLoad) {
    const meta = (k) => document.querySelector(`meta[name="${k}"],meta[property="${k}"]`)?.content?.trim() || "";
    const page = { url: location.href, title: cleanTitle(document.title) };
    // After an in-app navigation most sites leave the old <meta> tags in place; trust them only if og:url agrees.
    const og = meta("og:url");
    if (firstLoad || (og && sameUrl(og, location.href))) {
      page.description = (meta("description") || meta("og:description")).slice(0, 300);
      page.siteName = meta("og:site_name");
      page.keywords = meta("keywords").slice(0, 200);
    }
    if (location.hostname.endsWith("youtube.com")) {
      page.title = page.title.replace(/ - YouTube$/, "");
      const ch = document.querySelector("ytd-watch-metadata ytd-channel-name a, #owner ytd-channel-name a");
      if (ch && location.pathname === "/watch") page.channel = ch.textContent.trim();
    }
    return page;
  }

  async function check(force = false) {
    if (!alive()) return teardown();
    const url = location.href;
    if (!force && url === lastUrl) return;
    const firstLoad = lastUrl === null;
    lastUrl = url;
    const my = ++seq;
    await waitForTitle(lastTitle, firstLoad || force);
    if (my !== seq || location.href !== url) return;
    lastTitle = cleanTitle(document.title);
    const page = collect(firstLoad);
    awaiting = url;
    const d = await send({ type: "fg:classify", page });
    if (awaiting === url) awaiting = null;
    if (my !== seq || location.href !== url) return;
    if (!d || d.error) return clear();
    current = { page, d };
    render();
  }

  // ---- UI ----
  const CSS = `
    :host { all: initial; }
    * { box-sizing: border-box; font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }
    .shield { position: fixed; inset: 0; display: grid; place-items: center; padding: 24px; overflow: auto;
      background: rgba(4, 10, 24, .72); backdrop-filter: blur(18px) saturate(.6); -webkit-backdrop-filter: blur(18px) saturate(.6);
      animation: in .18s ease-out; }
    @keyframes in { from { opacity: 0 } to { opacity: 1 } }
    .card { width: min(600px, 100%); background: #fff; color: #0f172a; border-radius: 20px; padding: 32px 32px 24px;
      box-shadow: 0 30px 80px rgba(0,0,0,.45); }
    .brand { display: flex; align-items: center; gap: 8px; font-size: 13px; font-weight: 600; letter-spacing: .02em; color: #475569; }
    .logo { width: 18px; height: 18px; border-radius: 5px; background: linear-gradient(160deg, #2563eb, #0d9488); position: relative; }
    .logo::after { content: ""; position: absolute; left: 4px; right: 4px; top: 4px; bottom: 6px; border: 2px solid #fff; border-bottom: 0; border-radius: 1px; }
    h1 { font-size: 34px; line-height: 1.1; margin: 18px 0 6px; letter-spacing: -.02em; }
    .task { margin: 0 0 18px; color: #334155; font-size: 15px; line-height: 1.45; }
    .task b { color: #0f172a; }
    .meter { display: grid; grid-template-columns: auto 1fr; gap: 4px 14px; align-items: center; padding: 14px 16px; border-radius: 14px; background: #f1f5f9; }
    .pct { font-size: 36px; font-weight: 750; font-variant-numeric: tabular-nums; color: #e11d48; grid-row: span 2; }
    .lbl { font-size: 13px; color: #475569; }
    .bar { height: 8px; border-radius: 99px; background: #e2e8f0; overflow: hidden; }
    .bar i { display: block; height: 100%; background: linear-gradient(90deg, #f59e0b, #e11d48); border-radius: 99px; }
    .page { margin: 16px 0 4px; font-size: 14px; color: #0f172a; font-weight: 600; overflow-wrap: anywhere; }
    .dom { font-weight: 400; color: #64748b; }
    .why { margin: 0 0 20px; font-size: 13px; color: #475569; line-height: 1.5; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    button { font-family: inherit; font-size: 14px; font-weight: 600; line-height: 1.2; padding: 11px 14px; border-radius: 10px; border: 1px solid #cbd5e1;
      background: #fff; color: #0f172a; cursor: pointer; }
    button:hover { background: #f8fafc; border-color: #94a3b8; }
    button:focus-visible { outline: 3px solid #93c5fd; outline-offset: 1px; }
    button.primary { background: #0f172a; border-color: #0f172a; color: #fff; }
    button.primary:hover { background: #1e293b; }
    button.good { border-color: #059669; color: #047857; }
    .row { display: flex; gap: 8px; margin-top: 14px; }
    .row input { flex: 1; font-family: inherit; font-size: 14px; padding: 10px 12px; border: 1px solid #cbd5e1; border-radius: 10px; color: #0f172a; background: #fff; }
    .links { display: flex; flex-wrap: wrap; gap: 6px 18px; }
    .link { background: none; border: 0; padding: 0; margin-top: 14px; color: #2563eb; font-weight: 500; font-size: 13px; }
    .link:hover { background: none; text-decoration: underline; }
    .foot { margin: 18px 0 0; padding-top: 14px; border-top: 1px solid #e2e8f0; font-size: 12px; color: #64748b; line-height: 1.5; }
    .spinner { width: 34px; height: 34px; border-radius: 50%; border: 3px solid rgba(255,255,255,.25); border-top-color: #fff; animation: spin .8s linear infinite; margin: 0 auto 14px; }
    @keyframes spin { to { transform: rotate(360deg) } }
    .pending { color: #e2e8f0; text-align: center; font-size: 15px; }
    .nudge { position: fixed; right: 20px; bottom: 20px; width: min(360px, calc(100vw - 32px)); background: #fff; color: #0f172a;
      border-radius: 16px; padding: 16px 16px 14px; box-shadow: 0 18px 50px rgba(0,0,0,.28); border: 1px solid #e2e8f0; animation: up .2s ease-out; }
    @keyframes up { from { transform: translateY(12px); opacity: 0 } to { transform: none; opacity: 1 } }
    .nudge .top { display: flex; justify-content: space-between; align-items: center; }
    .nudge .p { font-size: 12px; font-weight: 700; color: #b45309; background: #fef3c7; padding: 3px 8px; border-radius: 99px; }
    .nudge h2 { font-size: 16px; margin: 10px 0 4px; line-height: 1.3; }
    .nudge .why { margin-bottom: 12px; }
    .nudge button { padding: 9px 11px; font-size: 13px; }
    .x { border: 0; background: none; font-size: 18px; line-height: 1; padding: 2px 6px; color: #64748b; }
    .toast { position: fixed; right: 20px; bottom: 20px; background: #0f172a; color: #fff; font-size: 13px; padding: 10px 14px;
      border-radius: 10px; box-shadow: 0 10px 30px rgba(0,0,0,.3); animation: up .2s ease-out; max-width: calc(100vw - 40px); }
    @media (prefers-color-scheme: dark) {
      .card, .nudge { background: #0f172a; color: #e2e8f0; border-color: #1e293b; }
      h1, .page, .task b, .nudge h2 { color: #f8fafc; }
      .task, .why, .lbl { color: #94a3b8; }
      .meter { background: #1e293b; } .bar { background: #334155; }
      button { background: #1e293b; color: #e2e8f0; border-color: #334155; } button:hover { background: #273449; border-color: #475569; }
      button.primary { background: #f8fafc; color: #0f172a; border-color: #f8fafc; } button.primary:hover { background: #e2e8f0; }
      button.good { color: #34d399; border-color: #059669; }
      .row input { background: #1e293b; color: #f8fafc; border-color: #334155; }
      .foot { border-color: #1e293b; } .link { color: #60a5fa; }
      .toast { background: #f8fafc; color: #0f172a; }
    }`;

  function h(tag, attrs = {}, ...kids) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "on") for (const [ev, fn] of Object.entries(v)) el.addEventListener(ev, fn);
      else if (k === "style") el.style.cssText = v;
      else el.setAttribute(k, v);
    }
    for (const kid of kids.flat()) if (kid != null && kid !== false) el.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
    return el;
  }

  function mount() {
    if (ui?.host.isConnected) return ui;
    const host = document.createElement("floodgate-ui");
    host.style.cssText = "all:initial;position:fixed;top:0;left:0;width:0;height:0;z-index:2147483647;";
    const root = host.attachShadow({ mode: "closed" });
    root.append(h("style", {}, CSS));
    const slot = h("div");
    root.append(slot);
    document.documentElement.append(host);
    ui = { host, root, slot };
    return ui;
  }

  // While blocked: media stays paused, the page does not scroll, and keys do not reach the page (YouTube's "k").
  const onPlay = (e) => e.target instanceof HTMLMediaElement && e.target.pause();
  const onKey = (e) => {
    if (ui && !e.composedPath().includes(ui.host)) e.stopImmediatePropagation();
  };
  let held = false;
  let prevOverflow = "";
  function hold(on) {
    if (on) document.querySelectorAll("video, audio").forEach((m) => m.pause());
    if (on === held) return;
    held = on;
    const verb = on ? "addEventListener" : "removeEventListener";
    document[verb]("play", onPlay, true);
    window[verb]("keydown", onKey, true);
    window[verb]("keypress", onKey, true);
    if (on) {
      prevOverflow = document.documentElement.style.overflow;
      document.documentElement.style.setProperty("overflow", "hidden", "important");
    } else document.documentElement.style.overflow = prevOverflow;
  }

  function clear() {
    ui?.slot.replaceChildren();
    hold(false);
  }

  function teardown() {
    clear();
    ui?.host.remove();
    clearInterval(poll);
  }

  function toast(text) {
    const { slot } = mount();
    const t = h("div", { class: "toast", role: "status" }, text);
    slot.replaceChildren(t);
    setTimeout(() => t.isConnected && t.remove(), 2600);
  }

  const pct = (p) => (p == null ? "–" : `${Math.round(p * 100)}%`);
  const domain = () => location.hostname.replace(/^www\./, "");

  async function teach(label, kind, scope = "url") {
    const { page, d } = current;
    await send({ type: "fg:label", page, label, kind, scope, decision: d });
  }

  function renderPending() {
    const { slot } = mount();
    hold(true);
    slot.replaceChildren(h("div", { class: "shield" }, h("div", { class: "pending" }, h("div", { class: "spinner" }), "Floodgate is checking this page against your task…")));
  }

  function renderBlock() {
    const { page, d } = current;
    const { slot } = mount();
    hold(true);
    const taskInput = h("input", { type: "text", placeholder: "What are you working on now?", value: d.task || "" });
    const change = h(
      "form",
      {
        class: "row",
        style: "display:none",
        on: {
          submit: async (e) => {
            e.preventDefault();
            if (!taskInput.value.trim()) return;
            await send({ type: "fg:setTask", task: taskInput.value.trim() });
            check(true);
          },
        },
      },
      taskInput,
      h("button", { type: "submit" }, "Update task"),
    );
    const card = h(
      "div",
      { class: "card", role: "dialog", "aria-modal": "true", "aria-labelledby": "fg-h" },
      h("div", { class: "brand" }, h("span", { class: "logo" }), "Floodgate"),
      h("h1", { id: "fg-h" }, "Not now."),
      h("p", { class: "task" }, d.task ? ["You said you're working on ", h("b", {}, d.task), "."] : "This page is on your block list."),
      h(
        "div",
        { class: "meter" },
        h("div", { class: "pct" }, pct(d.p)),
        h("div", { class: "lbl" }, "chance this is a distraction from your task"),
        h("div", { class: "bar" }, h("i", { style: `width:${Math.round((d.p ?? 1) * 100)}%` })),
      ),
      h("p", { class: "page" }, page.title || page.url, " ", h("span", { class: "dom" }, `— ${domain()}`)),
      h("p", { class: "why" }, d.reason || ""),
      h(
        "div",
        { class: "actions" },
        h("button", { class: "primary", on: { click: () => send({ type: "fg:leave" }) } }, "Take me back"),
        h(
          "button",
          {
            class: "good",
            title: "Saves a training row: this page is on task for this task",
            on: {
              click: async () => {
                await teach(0, "override");
                clear();
                toast(`Learned: on task for “${d.task}”. Saved as a training row.`);
              },
            },
          },
          "It's on task (teach Floodgate)",
        ),
      ),
      h(
        "div",
        { class: "links" },
        h(
          "button",
          {
            class: "link",
            on: {
              click: async () => {
                await send({ type: "fg:allow", page, minutes: 5 });
                clear();
                toast("Open for 5 minutes.");
                clearTimeout(recheckTimer);
                recheckTimer = setTimeout(() => check(true), 5 * 60 * 1000 + 1000);
              },
            },
          },
          "Give me 5 minutes",
        ),
        h(
          "button",
          {
            class: "link",
            on: {
              click: (e) => {
                change.style.display = "flex";
                e.target.remove();
                taskInput.focus();
              },
            },
          },
          "Working on something else? Change task",
        ),
      ),
      change,
      h("p", { class: "foot" }, `Decided by ${d.source}${d.ms ? ` in ${d.ms} ms` : ""}${d.cached ? " (cached)" : ""}. Your answers become training rows for your own model.`),
    );
    slot.replaceChildren(h("div", { class: "shield" }, card));
    card.querySelector("button.primary").focus({ preventScroll: true });
  }

  function renderNudge() {
    const { d } = current;
    const { slot } = mount();
    hold(false);
    const answer = (label, msg) => async () => {
      await teach(label, "nudge");
      if (label === 1) return check(true); // your own "distraction" answer locks the page right away
      clear();
      toast(msg);
    };
    slot.replaceChildren(
      h(
        "div",
        { class: "nudge", role: "dialog", "aria-label": "Floodgate: is this on task?" },
        h(
          "div",
          { class: "top" },
          h("div", { class: "brand" }, h("span", { class: "logo" }), "Floodgate"),
          h("div", { class: "brand" }, h("span", { class: "p" }, `${pct(d.p)} distraction`), h("button", { class: "x", title: "Dismiss", "aria-label": "Dismiss", on: { click: clear } }, "×")),
        ),
        h("h2", {}, `Is this on task for “${d.task}”?`),
        h("p", { class: "why" }, d.reason || "Floodgate isn't sure about this one."),
        h(
          "div",
          { class: "actions" },
          h("button", { class: "good", on: { click: answer(0, "Thanks. Saved as on task.") } }, "On task"),
          h("button", { on: { click: answer(1) } }, "Distraction"),
          h("button", { on: { click: answer(0.5, "Saved as “it depends”.") } }, "It depends"),
        ),
      ),
    );
  }

  function render() {
    if (!current) return clear();
    const { action } = current.d;
    if (action === "block") renderBlock();
    else if (action === "nudge") renderNudge();
    else clear();
  }

  // ---- wiring ----
  chrome.runtime.onMessage.addListener((msg) => {
    if (msg?.type === "fg:recheck") check(true);
    // The veil message can arrive after the decision (fast failures); only show it while still waiting.
    if (msg?.type === "fg:pending" && awaiting && sameUrl(msg.url, awaiting)) renderPending();
  });
  // In-app navigations: YouTube fires yt-navigate-finish; everything else is caught by the URL poll.
  window.addEventListener("yt-navigate-finish", () => check());
  window.addEventListener("popstate", () => check());
  window.addEventListener("pageshow", (e) => e.persisted && check(true));
  const poll = setInterval(() => {
    if (!alive()) return teardown();
    if (location.href !== lastUrl) check();
  }, 500);
  check();
})();
