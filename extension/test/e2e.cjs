// End-to-end smoke test: loads the unpacked extension into Chromium and clicks through the real flows
// (block, nudge, in-app navigation, overrides, modes, popup, dashboard, Teach, exports, gate server, model cards).
//
//   cd extension && npm run e2e
//
// Needs Node 18+, Python 3 and Playwright's Chromium (npm i -g playwright && npx playwright install chromium).
// Starts its own test site and a mock gate server (tools/mock_gate.py) on free ports; touches nothing else.
const fs = require("fs");
const os = require("os");
const path = require("path");
const http = require("http");
const { execSync, spawn } = require("child_process");

function loadPlaywright() {
  try {
    return require("playwright");
  } catch {
    return require(path.join(execSync("npm root -g").toString().trim(), "playwright"));
  }
}
const { chromium } = loadPlaywright();
const EXT = path.resolve(__dirname, "..");
const TMP = fs.mkdtempSync(path.join(os.tmpdir(), "floodgate-e2e-"));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let failures = 0;
const check = (ok, msg) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${msg}`);
  if (!ok) failures++;
};

// Test site: /page?t=<title> is a page with that title; its "next" button does a YouTube-style pushState + late title change.
const site = http.createServer((req, res) => {
  const t = (new URL(req.url, "http://x").searchParams.get("t") || "Untitled page").replace(/</g, "&lt;");
  res.writeHead(200, { "Content-Type": "text/html" });
  res.end(`<!doctype html><title>${t}</title><meta name="description" content="desc for ${t}"><h1>${t}</h1><video muted loop></video>
  <button id="nav" onclick="history.pushState({}, '', '/watch?v=' + Math.random().toString(36).slice(2)); setTimeout(() => document.title = 'GTA 6 gameplay funny moments compilation', 400)">next</button>`);
});
const listen = (srv) => new Promise((r) => srv.listen(0, "127.0.0.1", () => r(srv.address().port)));
const freePort = async () => {
  const s = http.createServer();
  const p = await listen(s);
  s.close();
  return p;
};

(async () => {
  const PORT = await listen(site);
  const GATE_PORT = await freePort();
  const GATE = `http://127.0.0.1:${GATE_PORT}`;
  const GATE_LOG = path.join(TMP, "gate_log.jsonl");
  const gate = spawn("python3", [path.join(EXT, "..", "tools", "mock_gate.py"), "--port", String(GATE_PORT), "--latency", "1.5", "--log", GATE_LOG], { stdio: "ignore" });
  process.on("exit", () => gate.kill());
  const SITE = (host, title) => `http://${host}:${PORT}/page?t=${encodeURIComponent(title)}`;

  const ctx = await chromium.launchPersistentContext(path.join(TMP, "profile"), {
    headless: true,
    channel: "chromium",
    args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`, "--no-proxy-server", "--host-resolver-rules=MAP *.fgtest 127.0.0.1"],
  });
  const errors = [];
  let [sw] = ctx.serviceWorkers();
  if (!sw) sw = await ctx.waitForEvent("serviceworker");
  sw.on("console", (m) => m.type() === "error" && errors.push(`sw: ${m.text()}`));
  await sleep(1000);
  const id = new URL(sw.url()).host;
  console.log("extension id", id);
  await sleep(800);
  const pages = ctx.pages().map((p) => p.url());
  check(pages.some((u) => u.includes("dashboard.html#welcome")), "install opens the welcome dashboard");

  const set = (settings) => sw.evaluate(async (s) => {
    const { settings: cur = {} } = await chrome.storage.local.get("settings");
    await chrome.storage.local.set({ settings: { ...cur, ...s } });
  }, settings);
  const firstRun = await sw.evaluate(async () => (await chrome.storage.local.get("settings")).settings);
  check(!firstRun || (firstRun.provider ?? "systemone") === "systemone", "the River model is the default provider");
  await set({ task: "research the Jev model for the hackathon", mode: "focus", onboarded: true, provider: "heuristic" });

  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(`page: ${m.text()}`));
  page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
  const shield = () => page.evaluate(() => {
    const host = document.querySelector("floodgate-ui");
    return host ? host.getBoundingClientRect() && document.documentElement.style.overflow : null;
  });
  // closed shadow root: look for it through the accessibility tree instead
  const ui = async () => {
    const snap = await page.accessibility.snapshot({ interestingOnly: false }).catch(() => null);
    const txt = JSON.stringify(snap || {});
    return { block: txt.includes("Not now."), nudge: txt.includes("Is this on task"), pending: txt.includes("checking this page"), txt };
  };


  // The shield lives in a closed shadow root (pages can't script it), so drive it with the keyboard like a user.
  const focused = (n) => (n?.focused ? n : (n?.children || []).map(focused).find(Boolean));
  const press = async (name) => {
    for (let i = 0; i < 20; i++) {
      const f = focused(await page.accessibility.snapshot({ interestingOnly: false }));
      if (f && name.test(f.name || "")) return page.keyboard.press("Enter");
      await page.keyboard.press("Tab");
    }
    throw new Error(`could not focus ${name}`);
  };

  // 1. on-task page -> allowed
  await page.goto(SITE("tube.fgtest", "Jev in 100 Seconds"));
  await sleep(1500);
  let u = await ui();
  check(!u.block && !u.nudge, "on-task page is let through");

  // 1b. a site's home page stays open so you can search (YouTube's home used to get blocked)
  await page.goto(`http://tube.fgtest:${PORT}/`);
  await sleep(1500);
  u = await ui();
  const homeLog = (await sw.evaluate(async () => (await chrome.storage.local.get("log")).log || [])).at(-1);
  check(!u.block && !u.nudge && /Home page/.test(homeLog?.reason || ""), `home page is not blocked (${homeLog?.reason})`);

  // 2. off-task entertainment -> block, video paused, scroll locked
  await page.goto(SITE("tube.fgtest", "GTA 6 gameplay funny moments compilation"));
  await sleep(1500);
  u = await ui();
  check(u.block, "off-task entertainment page is blocked");
  check((await shield()) === "hidden", "page scroll is locked while blocked");
  await page.screenshot({ path: path.join(TMP, "blocked.png") });

  // 3. ambiguous page -> nudge card, page still usable
  await page.goto(SITE("blog.fgtest", "Why sourdough rises"));
  await sleep(1500);
  u = await ui();
  check(u.nudge && !u.block, "ambiguous page gets the 'is this on task?' card");
  await page.screenshot({ path: path.join(TMP, "nudge.png") });

  // 4. in-app navigation (pushState + late title change, like YouTube) -> re-checked and blocked
  await page.goto(SITE("tube.fgtest", "Jev explained for the hackathon"));
  await sleep(1200);
  check(!(await ui()).block, "SPA start page allowed");
  await page.click("#nav");
  await sleep(2500);
  u = await ui();
  check(u.block, "in-app navigation to an off-task title is blocked");

  // 5. override -> label saved, page opens, and stays open on reload (personal memory)
  await press(/It's on task/);
  await sleep(800);
  u = await ui();
  check(!u.block, "override removes the shield");
  const labels = await sw.evaluate(async () => (await chrome.storage.local.get("labels")).labels || []);
  check(labels.length === 1 && labels[0].label === 0 && labels[0].kind === "override", `override stored as a label (${labels.length})`);
  await page.reload();
  await sleep(1500);
  u = await ui();
  check(!u.block, "overridden page stays open after reload (your labels)");
  const log = await sw.evaluate(async () => (await chrome.storage.local.get("log")).log || []);
  check(log.at(-1)?.source === "your labels", `decision source after override: ${log.at(-1)?.source}`);

  // 6. nudge 'Distraction' answer locks the page
  await page.goto(SITE("blog.fgtest", "Why sourdough rises"));
  await sleep(1500);
  await press(/^Distraction$/);
  await sleep(1200);
  check((await ui()).block, "answering 'Distraction' on the nudge locks the page");

  // 7. break mode lifts the shield on open tabs
  await set({ mode: "break" });
  await sleep(1500);
  check(!(await ui()).block, "switching to Break mode unblocks open tabs");
  await set({ mode: "creator" });
  await page.goto(SITE("tube.fgtest", "Try not to laugh compilation"));
  await sleep(1500);
  check(!(await ui()).block, "creator mode: entertainment on an unknown site is not blocked outright");
  await set({ mode: "focus" });

  // 8. popup and dashboard render without errors
  const pop = await ctx.newPage();
  pop.on("pageerror", (e) => errors.push(`popup: ${e.message}`));
  await pop.setViewportSize({ width: 360, height: 620 });
  await pop.goto(`chrome-extension://${id}/pages/popup.html`);
  await sleep(1000);
  check((await pop.inputValue("#task")).includes("Jev"), "popup shows the current task");
  await pop.screenshot({ path: path.join(TMP, "popup.png") });
  const dash = await ctx.newPage();
  dash.on("pageerror", (e) => errors.push(`dashboard: ${e.message}`));
  await dash.setViewportSize({ width: 1200, height: 900 });
  await dash.goto(`chrome-extension://${id}/pages/dashboard.html#overview`);
  await sleep(1200);
  const rows = await dash.locator("#log tr").count();
  check(rows >= 5, `dashboard lists recent decisions (${rows})`);
  await dash.screenshot({ path: path.join(TMP, "dashboard.png"), fullPage: true });
  await dash.goto(`chrome-extension://${id}/pages/dashboard.html#teach`);
  await sleep(500);
  await dash.fill("#tTask", "bake sourdough bread");
  await dash.click("#tLoad");
  await sleep(800);
  const q = await dash.locator("#tQueue").innerText();
  check(/guesses/.test(q), "Teach tab loads browsing history into the label queue");
  await dash.keyboard.press("1");
  await sleep(400);
  const n = await sw.evaluate(async () => ((await chrome.storage.local.get("labels")).labels || []).length);
  check(n === 3, `keyboard label in Teach saved (${n} labels)`);
  await dash.screenshot({ path: path.join(TMP, "teach.png"), fullPage: true });

  // 9. export training rows through the real download path
  await dash.goto(`chrome-extension://${id}/pages/dashboard.html#share`);
  const [dl] = await Promise.all([dash.waitForEvent("download"), dash.click("#dRows")]);
  const text = fs.readFileSync(await dl.path(), "utf8").trim().split("\n");
  const row = JSON.parse(text[0]);
  check(text.length === 3 && row.kind === "noul" && row.state.startsWith("URL: ") && row.question.includes("distraction"), `training rows export (${text.length} rows)`);
  const [card] = await Promise.all([dash.waitForEvent("download"), dash.click("#cExport")]);
  const cardJson = JSON.parse(fs.readFileSync(await card.path(), "utf8"));
  check(cardJson.floodgate_model_card === 1 && cardJson.examples.length === 0, "model card export (examples private by default)");

  // 10. River gate provider via the mock server: pending veil, then model decision, override POSTed
  await set({ provider: "floodgate-gate", providerSettings: { "floodgate-gate": { endpoint: GATE } } });
  await sleep(300);
  await page.goto(SITE("tube.fgtest", "Minecraft speedrun world record"));
  await sleep(700);
  check((await ui()).pending, "risky page is held behind the 'checking' veil while the model thinks");
  await sleep(2500);
  u = await ui();
  const last = (await sw.evaluate(async () => (await chrome.storage.local.get("log")).log || [])).at(-1);
  check(u.block && last.source === "mock gate", `model decision from the gate server (source: ${last.source}, ${last.ms} ms)`);
  await press(/It's on task/);
  await sleep(800);
  const gateLog = fs.readFileSync(GATE_LOG, "utf8").trim().split("\n").map(JSON.parse);
  check(gateLog.some((r) => r.kind === "override" && r.title?.includes("Minecraft")), "override reached the gate server (/override)");

  // 11. gate offline -> heuristic fallback, clearly labelled
  const DEAD = `http://127.0.0.1:${await freePort()}`;
  await set({ providerSettings: { "floodgate-gate": { endpoint: DEAD } } });
  await sleep(300);
  await page.goto(SITE("tube.fgtest", "Fortnite live stream highlights"));
  await sleep(2500);
  const last2 = (await sw.evaluate(async () => (await chrome.storage.local.get("log")).log || [])).at(-1);
  const u2 = await ui();
    check(u2.block && /unreachable/.test(last2.source), `offline fallback: ${last2.source}`);

  // 12. import a teammate's model card: examples become labels, their checkpoint is loaded into the gate server
  await set({ providerSettings: { "floodgate-gate": { endpoint: GATE } } });
  const friend = { floodgate_model_card: 1, name: "Chinat focus", author: "cyu60", backend: { provider: "floodgate-gate", checkpoint: "river://floodgate/ckpt-42", temperature: 1.7 },
    mode: "focus", profile: "", rules: { allow: ["docs.river.ai"], block: ["netflix.com"] },
    examples: [{ url: SITE("tube.fgtest", "Lofi beats"), domain: "tube.fgtest", title: "Lofi beats", task: "research the Jev model for the hackathon", label: 0, scope: "url", ts: Date.now() }] };
  const cardFile = path.join(TMP, "friend-card.json");
  fs.writeFileSync(cardFile, JSON.stringify(friend));
  await dash.goto(`chrome-extension://${id}/pages/dashboard.html#share`);
  await sleep(500);
  await dash.setInputFiles("#cFile", cardFile);
  await sleep(300);
  check(/river:\/\/floodgate\/ckpt-42/.test(await dash.locator("#cPreviewText").innerText()), "card preview shows the shared checkpoint");
  await dash.click("#cApply");
  await sleep(1000);
  const gateState = await (await fetch(`${GATE}/`)).json();
  check(gateState.checkpoint === "river://floodgate/ckpt-42" && gateState.temperature === 1.7, "their checkpoint was hot-swapped into the gate server (POST /model)");
  await page.goto(SITE("tube.fgtest", "Lofi beats"));
  await sleep(1500);
  const last3 = (await sw.evaluate(async () => (await chrome.storage.local.get("log")).log || [])).at(-1);
  check(!(await ui()).block && /Chinat focus/.test(last3.reason), `their example applies to me: ${last3.reason}`);
  const s3 = await sw.evaluate(async () => (await chrome.storage.local.get("settings")).settings);
  check(s3.blockDomains.includes("netflix.com") && s3.allowDomains.includes("docs.river.ai"), "their rules were merged");

  // 13. GBrain context provider against tools/mock_gbrain_mcp.py: settings show up, health works, corrections are remembered
  const gbrainMock = spawn("python3", [path.join(EXT, "..", "tools", "mock_gbrain_mcp.py")], { stdio: "ignore" });
  process.on("exit", () => gbrainMock.kill());
  await sleep(800);
  await set({ enrichers: { gbrain: true }, providerSettings: { "floodgate-gate": { endpoint: GATE }, gbrain: { endpoint: "http://127.0.0.1:8799/mcp", token: "test" } } });
  await dash.goto(`chrome-extension://${id}/pages/dashboard.html#model`);
  await sleep(800);
  check((await dash.locator("#enrichers input[type=password]").count()) === 1, "GBrain token field is shown under Context providers");
  await dash.locator("#enrichers button", { hasText: "Test connection" }).click();
  await sleep(1200);
  const gmsg = await dash.locator("#enrichers .msg").innerText();
  check(/Connected.*search_memory.*remember/.test(gmsg), `GBrain health: ${gmsg}`);
  await page.goto(SITE("tube.fgtest", "Minecraft speedrun any percent"));
  await sleep(3500);
  await press(/It's on task/);
  await sleep(1500);
  const recall = await fetch("http://127.0.0.1:8799/mcp", {
    method: "POST",
    headers: { "Content-Type": "application/json", Authorization: "Bearer t" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "tools/call", params: { name: "search_memory", arguments: { query: "x" } } }),
  }).then((r) => r.text());
  check(/Floodgate correction.*Minecraft speedrun any percent.*ON TASK/.test(recall), "override was remembered in GBrain (onLabel)");
  const lastG = (await sw.evaluate(async () => (await chrome.storage.local.get("log")).log || [])).find((e) => /Minecraft speedrun any/.test(e.title));
  check(lastG && !lastG.providerError, "decision still works with GBrain enrichment on");
  await set({ enrichers: {} });

  // 13b. the default provider: a Jev-compatible /v1/systemone with a bearer token (stand-in for the ngrok River model)
  const seen = [];
  const jev = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c) => (body += c));
    req.on("end", () => {
      res.setHeader("Content-Type", "application/json");
      if (req.method === "GET") return res.end(JSON.stringify({ models: [{ name: "floodgate-personal-v1", checkpoint: "river://x", temperature: 1 }] }));
      if (req.headers.authorization !== "Bearer s3cret") return (res.statusCode = 401), res.end('{"detail":"missing or wrong bearer token"}');
      const b = JSON.parse(body);
      seen.push({ state: b.state, ngrok: req.headers["ngrok-skip-browser-warning"] });
      const p = /speedrun|gameplay|funny/i.test(b.state) ? 0.93 : 0.08;
      setTimeout(() => res.end(JSON.stringify({ answers: { distraction: { type: "noul", noul: p } }, model: "floodgate-personal-v1" })), 800);
    });
  });
  const JEV = `http://127.0.0.1:${await listen(jev)}/v1/systemone`;
  await set({ provider: "systemone", providerSettings: { systemone: { endpoint: JEV } } });
  await page.goto(SITE("tube.fgtest", "Roblox obby funny fails"));
  await sleep(2500);
  const noKey = (await sw.evaluate(async () => (await chrome.storage.local.get("log")).log || [])).at(-1);
  check(/unreachable/.test(noKey.source) && /API key/.test(noKey.providerError || ""), `without a token: falls back and says why (${noKey.providerError})`);
  await set({ providerSettings: { systemone: { endpoint: JEV, apiKey: "s3cret" } } });
  await page.goto(SITE("tube.fgtest", "Skibidi toilet speedrun reaction"));
  await sleep(3000);
  const withKey = (await sw.evaluate(async () => (await chrome.storage.local.get("log")).log || [])).at(-1);
  check((await ui()).block && /River model/.test(withKey.source) && withKey.p === 0.93, `with the token: River model decides (${withKey.source}, p=${withKey.p})`);
  check(/^URL: http:\/\/tube\.fgtest:\d+\/page\?t=Skibidi\S* Title: Skibidi toilet speedrun reaction\. Time: \d\d:\d\d \w+day\. Stated task: research the Jev model for the hackathon\.$/.test(seen.at(-1)?.state || ""), `sent the training-format text line: ${seen.at(-1)?.state}`);
  check(seen.at(-1)?.ngrok === "true", "sends ngrok-skip-browser-warning");
  await page.goto(SITE("tube.fgtest", "Jev explained by the TypeSafe team"));
  await sleep(3000);
  check(!(await ui()).block, "with the token: on-task page passes");
  jev.close();
  await set({ provider: "heuristic" });

  // 14. Optional: the real gate server (e.g. an ngrok URL):  FLOODGATE_GATE=https://… npm run e2e
  if (process.env.FLOODGATE_GATE) {
    const REAL = process.env.FLOODGATE_GATE.replace(/\/+$/, "");
    await set({ provider: "floodgate-gate", mode: "focus", task: "build the Floodgate hackathon demo", providerSettings: { "floodgate-gate": { endpoint: REAL, timeoutMs: 30000 } } });
    await dash.goto(`chrome-extension://${id}/pages/dashboard.html#model`);
    await sleep(600);
    await dash.locator("#providers .provider.on button", { hasText: "Test connection" }).click();
    await sleep(4000);
    console.log(`REAL gate health: ${await dash.locator("#providers .provider.on .msg").innerText()}`);
    for (const title of ["Chrome extension Manifest V3 service worker docs", "Funny cat compilation 2026", "xkcd: Standards"]) {
      await page.goto(SITE("real.fgtest", title));
      await sleep(15000);
      const e = (await sw.evaluate(async () => (await chrome.storage.local.get("log")).log || [])).at(-1);
      console.log(`REAL ${e.action.padEnd(5)} p=${e.p} ${e.ms} ms  ${title}  [${e.source}]`);
      check(!e.providerError, `real gate answered for "${title}"${e.providerError ? `: ${e.providerError}` : ""}`);
    }
    await set({ mode: "break" });
    await sleep(1500);
    check(!(await ui()).block, "real gate: Break mode unblocks");
  }

  console.log(errors.length ? `ERRORS:\n${errors.join("\n")}` : "no console errors");
  console.log(`screenshots: ${TMP}`);
  await ctx.close();
  site.close();
  process.exit(failures || errors.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(2); });
