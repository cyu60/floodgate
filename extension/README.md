# Floodgate: the Chrome extension

You tell Floodgate what you're working on. It checks every page you open against that task: on-task pages pass, drift gets blocked, and when it's unsure it asks you. Every answer becomes a training row for your own model.

Same site, different answer: a YouTube video about your task passes, and an informative but unrelated YouTube video gets blocked.

## 1. Install (2 minutes, no server needed)

1. Get the code: `git clone https://github.com/cyu60/floodgate` (or `git pull` if you have it).
2. In Chrome, open `chrome://extensions` and turn on **Developer mode** (top right).
3. Click **Load unpacked** and pick the **`extension/`** folder (the one with `manifest.json` in it).
4. Pin it: click the puzzle icon in the toolbar, then the pin next to Floodgate.
5. The welcome page opens. Type your task, pick a mode, and start browsing.

It works right away with the built-in **offline heuristic**, so a demo never depends on a server.

**After you pull changes** (yours or a teammate's): `chrome://extensions` → Floodgate → reload (↻), then reload any open tabs.

## 2. Connect the River model (on by default)

The extension uses the team's River model out of the box: **Dashboard → Model → "River model (Jev-compatible /v1/systemone)"** is preselected with the team's ngrok address. Paste the bearer token you were sent into **API key / bearer token** and click **Test connection**. Until the token is in, or when the laptop serving the model is asleep, Floodgate uses the offline heuristic and the block screen says why. Each decision takes about 4 to 8 seconds. If ngrok restarts, paste the new address into **Endpoint** (for new installs, update `DEFAULT_MODEL_URL` in `lib/config.js`).

Site home pages (like youtube.com) are never blocked, so you can search; Floodgate judges what you open next.

### Other providers

Open the Floodgate popup → **Dashboard → Model**, pick a provider and click **Test connection**.

| Provider | Start it with | Use it for |
|---|---|---|
| **Your personal model (gate server)** | `python -m floodgate.gate_server --run models/floodgate-personal-v1.json` (port 8790) | The real thing: trained on River on your own browsing, 77–80% agreement on held-out personal pages. Runs on the machine whose River key trained it |
| River open Jev, public data | `python -m floodgate.gate_server --run models/open-jev-river-v1.json` (port 8790) | The general model trained on Open-Jev's public data |
| same, mocked | `python3 tools/mock_gate.py` (same API, no River or venv, ~1.5 s fake latency) | Building and demoing before the River model is up |
| **Jev-compatible endpoint** | `python -m floodgate.open_jev.server --run data/runs/<run>.json` (port 8791) | Any `/v1/systemone` server; also TypeSafe's hosted Jev as a baseline (API key + model `jev-latest`) |
| **Offline heuristic** | built in | Default, and the fallback whenever the model can't be reached |
| **GBrain memory** (context provider) | gbrain.io workspace → Add a connection → copy the token (Full access to remember) | Remembers every correction in GBrain per task, and reads them back: a page you corrected on any device is decided by GBrain's memory ("GBrain remembers: …") before the model is asked. Tick it under Dashboard → Model → Context providers, paste the token, Test connection. Test offline with `python3 tools/mock_gbrain_mcp.py` (endpoint `http://127.0.0.1:8799/mcp`, any token) |

If the model is down, Floodgate falls back to the heuristic and says so on the block screen ("offline heuristic (… unreachable)"). While a slow model is thinking, likely distractions stay behind a "checking" screen with the video paused.

## 3. What it does

| Feature | Where |
|---|---|
| **Task-relative decisions.** P(distraction) is scored against *your stated task*, not a domain list | `lib/heuristic.js`, `providers/` |
| **Block screen.** Blurs the page, pauses video, locks scrolling. Buttons: *Take me back*, *It's on task (teach Floodgate)*, *Give me 5 minutes*, *Change task* | `content.js` |
| **Unclear pages: it asks.** Between the "ask" and "block" thresholds you get a small card: *On task / Distraction / It depends*. "It depends" saves a 50/50 soft label | `content.js` |
| **YouTube-style navigation.** Sites that change the URL without reloading (YouTube, X, Reddit) are re-checked once the new title settles | `content.js` |
| **Modes.** Focus, Research, Creator (the influencer case: trends, memes and viral videos count as work), Break | `lib/config.js` |
| **About me.** Free text sent to the model with every page ("I'm a content creator", "I'm a musician") | Dashboard → Model |
| **Learns immediately.** Your labels apply on the next visit, before any retraining: an exact page or domain decides outright; similar titles shift the score | `lib/memory.js` |
| **Train on your browsing history.** *Teach* tab loads your Chrome history and asks about the pages it is least sure of first. Keys `1` `2` `3`, `Space`, `Z` | Dashboard → Teach |
| **Training rows export.** Labels become Open-Jev noul rows in the exact format of `prep_gate_dataset.py` | Dashboard → Share, `lib/rows.js` |
| **Share your model.** A model card holds your River checkpoint and temperature, your rules, and (only if you opt in) your labelled pages. Importing one loads the checkpoint into your gate server. The repo's River cards (`models/open-jev-river-v1.json`) import as-is, and exported cards work with `gate_server --run` | Dashboard → Share, `lib/modelcard.js` |
| **Toolbar badge** shows the percent for the current tab (red = blocked, amber = asked, green = allowed) | `background.js` |
| **Pause** for 15 minutes from the popup, or press `Alt+Shift+P` | popup, `background.js` |

### How one decision is made

1. Not a web page, or on your allow list: **allow**. Paused: **allow**. On your block list: **block**.
2. You labelled this page (or its whole domain) for the same or a similar task: that label decides.
3. Otherwise the chosen provider returns P(distraction). If it can't be reached, the offline heuristic answers instead.
4. Labels on pages with similar titles shift the score.
5. The mode's thresholds turn P into an action. With no task set, nothing is ever blocked.

| Mode | Blocks at | Asks from |
|---|---|---|
| Focus | 70% | 50% |
| Research | 80% | 55% |
| Creator | 85% | 55% |
| Break | never | never |

## 4. For teammates: plug your part in

Everything that decides, adds context, or learns is a **provider**, a small JS object in `providers/`. Floodgate only calls the methods you define:

```js
export default {
  id: "gbrain",
  name: "GBrain memory",
  description: "One line for the dashboard.",
  settings: [{ key: "endpoint", label: "Endpoint", default: "http://127.0.0.1:9000" }], // editable in Dashboard → Model
  async classify(page, ctx, cfg) { return { p: 0.8, reason: "…", model: "…" }; }, // DECIDE: P(distraction), throw to fall back
  async enrich(page, ctx, cfg)   { return { current_project: "…" }; },            // CONTEXT: merged into the model's state (2 s budget)
  async onLabel(label, ctx, cfg) {},                                                // LEARN: the user labelled a page
  async onContext(ctx, cfg) {},                                                     // task / mode / about-me changed
  async health(cfg) { return { ok: true, detail: "…" }; },                          // status dot + Test connection
};
```

To add one: copy `providers/_template.js` (it documents every field of `page`, `ctx` and `label`), add it to `PROVIDERS` in `providers/index.js`, reload the extension. It appears in **Dashboard → Model**: as a decision provider if it has `classify`, as a toggle under *Context providers* if it has `enrich`. It runs in the service worker, so use `fetch()`; host permissions already allow any URL.

Suggested split:

- **River (training and serving):** nothing to change in the extension. Keep `gate_server.py` answering the contract below. Train on exported rows with `python -m floodgate.open_jev.train --extra floodgate-labels.jsonl`. Overrides also arrive live at `POST /override` (in `data/gate_log.jsonl`).
- **GBrain (done, `providers/gbrain.js`):** `onLabel` writes each correction to GBrain, `recall` reads them back to decide pages (memory that follows you across devices), `enrich` fetches task context.
- **Memorable (next):** copy the GBrain pattern: `onLabel` to store a correction, `recall` to return `{ p, reason, source }` for a page and task (or `null`), add it to `PROVIDERS`. Order of authority: your local labels → memory providers → the model → the heuristic.
- **QM:** the same pattern: `classify` if it decides, `enrich` if it adds context, `onLabel` if it learns.

### Gate server contract (`floodgate/gate_server.py`, mocked by `tools/mock_gate.py`)

| Call | Body | Returns |
|---|---|---|
| `POST /` | `{url, title, task, about_me, mode, description, channel, query, extra}` | `{p, lock, task, ms}` |
| `POST /task` | `{task, profile}` | `{task}` |
| `POST /override` | `{url, title, label, model_p, task, mode, kind, scope}` | `{logged: true}`, appended to `data/gate_log.jsonl` |
| `POST /model` | `{checkpoint, temperature}` | loads a shared model card without restarting |
| `GET /` | | `{ok, task, threshold, checkpoint, temperature, …}` |

`label` is 0 (on task), 1 (distraction) or 0.5 (it depends). The extension ignores the server's `lock` and applies the thresholds of the mode the user picked. The server currently uses `url`, `title`, `task` and `about_me`; the other fields are there for whoever wants page descriptions, YouTube channel names or search queries in the prompt.

## 5. Files

| Path | What |
|---|---|
| `manifest.json` | MV3 manifest |
| `background.js` | Service worker: decides, caches (10 min), logs, badges, handles messages |
| `content.js` | Runs in every page: reads title and metadata, detects in-app navigation, shows the block screen and the ask card (closed shadow DOM) |
| `lib/classifier.js` | Rules → your labels → provider → thresholds |
| `lib/heuristic.js` | Offline classifier (task overlap, domain priors, entertainment and learning cues, creator mode) |
| `lib/memory.js` | Your labels applied at decision time |
| `lib/rows.js`, `lib/modelcard.js` | Training-row export, model cards |
| `lib/store.js`, `lib/config.js`, `lib/text.js` | Storage, constants and modes, text helpers |
| `providers/` | `heuristic`, `floodgate-gate` (River), `systemone` (Jev API), `_template.js` |
| `pages/` | Popup and dashboard (Overview, Teach, Model, Share) |
| `test/` | `npm test` (logic, Node only), `npm run e2e` (loads the extension in Chromium with Playwright and clicks through every flow) |

## 6. Troubleshooting

- **Nothing happens on a tab:** tabs opened before install get the script injected on install; if one doesn't, reload the tab. Floodgate never runs on `chrome://` pages, the Chrome Web Store or the PDF viewer.
- **Never blocks:** is a task set? Is the mode Break, or is it paused? Is the site on your allow list?
- **Logs:** `chrome://extensions` → Floodgate → *service worker* opens the background console. Decisions are also in Dashboard → Overview.
- **Model shows offline:** check the URL under Dashboard → Model → Test connection. The gate server listens on `127.0.0.1:8790` by default.

## 7. Privacy

Settings, labels and the decision log live in `chrome.storage.local` in your browser. A page's URL, title and short description go only to the provider you pick (localhost by default). History is read only when you click *Load my history* or *Download raw history*. Model cards leave out your labelled pages unless you tick the box.

## 8. Demo script (about 2 minutes)

1. Task: "research TypeSafe's Jev model for the hackathon", mode **Focus**.
2. Open a YouTube video about Jev: it passes (low %, "About your task (“jev”)").
3. Click an unrelated recommendation, like a satellite-launch explainer: **blocked**, "Informative, but not about your task". Same site, opposite answer.
4. Open a blog that's hard to call: the **ask card** appears. Answer "It depends".
5. On a blocked page that is actually on task, click **It's on task**. Reload: it passes with "You labelled this page on task". That's a training row.
6. Switch to **Creator**: a meme compilation passes; the unrelated explainer now asks instead of blocking.
7. Dashboard → **Teach**: label a few history pages with `1` / `2` / `3`. **Share**: download the training rows (River trains on them), export a model card, and a teammate imports it along with its River checkpoint. Importing `models/open-jev-river-v1.json` swaps the team's trained model into a running gate server with no restart.
