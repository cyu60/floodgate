# PRD — Floodgate: an open Jev, trained on River, that guards your attention

*Own Your Intelligence Hackathon · YC HQ · Sep 27, 2026. Own your intelligence, literally: the model that judges your attention is yours, trained on your overrides.*

## 1. One line

A browser gate that asks a small, calibrated decision model "is this page a distraction from what I said I'm doing?" before every page loads. The model is an **open Jev** trained on **River**, and every time you override it, it learns you.

## 2. Problem

- Attention leaks through the browser. Blockers are blunt: they block a domain, not a situation. YouTube is a distraction at 23:40 and research at 14:00 when the task is "study Jev".
- The judgment "is this on-task?" needs language understanding, so it needs a model. But a chat LLM is the wrong tool: slow, expensive per call, returns prose you must parse, and its "80% sure" is decoration, not a probability you can threshold.
- TypeSafe's **Jev** solves the interface (typed, calibrated decisions, no text) but it is closed, the same weights serve everyone, and it cannot be fine-tuned on *your* judgment.

## 2a. The idea in one example (team, 14:00)

Use your own browsing history to train your own model. You are watching a YouTube video about what you are doing right now, and it lets you through. Then you drift into another YouTube video that is informative but unrelated to your task, and Floodgate recognises that and blocks it. Same site, same "educational" look, different answer, because the judgment is relative to **your stated task** and learned from **your** history. And because the model is yours, you can **share it**: a checkpoint is a file-like `river://` path you can hand to a friend or a team.

### Measured: even Jev cannot tell your task (Sep 27, 14:05)

Task: "research TypeSafe's Jev model for the hackathon". Question: "Is this page a distraction from the stated task?" (noul, P(yes)).

| Page | Jev 1.13 | Open Jev on River (untrained base) |
|---|---:|---:|
| Fireship video on Jev (on task) | 0.61 | 0.56 |
| Satellite-launch explainer (informative, off task) | 0.95 | 0.95 |
| TypeSafe's own Noul docs page (on task) | **0.75** | 0.56 |
| GTA 6 gameplay (entertainment) | 0.96 | 0.93 |
| Same satellite video, task = "report on launch failures" | 0.33 | 0.56 |

Both models catch the obvious cases. Both are unsure or wrong on the pages that matter: Jev scores the TypeSafe docs you are reading *for this exact task* as 75% distraction. That gap is the product: a general model does not know your task boundaries; a model trained on your overrides does. (Jev ~120–360 ms per call; River base ~6 s for a batch of 5. River returns coarsely rounded logprobs, so untrained scores cluster.)

## 3. Insight

1. A decision model only needs one number per candidate: how much the model prefers "Yes" over "No". **Open-Jev** (Zefan Cai, Apache/MIT) is a LoRA plus a scalar head initialised as `lm_head[Yes] − lm_head[No]`, trained with candidate NLL plus a calibration temperature. It scores 197/231 on public JevBench vs Jev's 200/231.
2. **River** exposes exactly that number for any open model: sample one token with top-K logprobs and read `logprob(Yes) − logprob(No)`. So the untrained base model on River *is* Open-Jev at step 0, and River's LoRA training (with `train_unembed`) moves the same quantity.
3. Therefore: Open-Jev's API, prompts and response format + River's training and serving = **an open Jev you own and can personalise**, with no GPU.

## 4. Users and jobs

| User | Job to be done |
|---|---|
| A builder with a leaky attention span (us) | "Stop me when I drift, let me through when I'm working, and learn the difference from my overrides." |
| A developer who wants Jev-style decisions on their own data | "Give me `/v1/systemone` with calibrated noul/choice/score answers that I can fine-tune." |
| River | A showcase: typed decision models are a first-class use of training-as-an-API. |

## 5. Scope

### In (hackathon v1)

1. **Open Jev on River** (`floodgate/open_jev/`)
   - Port of Open-Jev's request compiler, candidate prompts and typed response formatter (noul / choice / score, confidence, legend). Byte-compatible with Jev's `POST /v1/systemone`.
   - Scorer: Yes/No logprob gap per candidate via River sampling (base, live training weights, or saved checkpoint).
   - Trainer: LoRA r8 + `train_unembed`, one Yes/No target token per candidate, soft targets as weights, each record weighted 1; calibration temperature fitted on a held-out split; base vs trained eval on test + OOD.
   - Data: stratified sample of Open-Jev's public v1.1 corpus (1,164 train / 140 cal / 228 test / 115 OOD, 18 task families).
   - Server: Jev-compatible `/v1/systemone` backed by a River checkpoint.
2. **Floodgate browser gate** (`extension/` + `floodgate/gate_server.py`)
   - Chrome MV3 extension: on each top-frame navigation, POST `{url, title}` to the local gate; lock page if P(distraction) ≥ threshold; popup to set the stated task.
   - Gate asks one noul over `{url, title, time, stated_task}` through the Open-Jev scorer; caches per URL; logs every decision.
   - "This is on task" button on the lock page logs an override as a training row.
3. **Labelling loop** (`floodgate/label_queue.py`, `label_server.py`, `tools/label.html`): queue ambiguous visits, keyboard-label them, write Open-Jev-style rows.

### Out (v1)

- Hosted deployment (personal River keys cannot create dedicated deployments).
- Brier term in the loss (River has no custom losses).
- Page-content features (v1 uses URL + title + time + task only).
- Multi-user accounts, mobile.

### Stretch (if time)

- **Jev as teacher:** label unlabelled history rows with Jev (`floodgate/jev.py`), then correct the ones it gets wrong by hand; train on the corrected set.
- **Share your model:** publish a checkpoint path + temperature as a small JSON "model card" teammates can load with `--run`.

## 6. Architecture

```
Chrome (MV3 extension) ──{url,title}──▶ gate_server :8790
                                          │ compile_request (Open-Jev format)
                                          ▼
                                  open_jev.scorer ──sample(max_tokens=1, logprobs=20)──▶ River
                                          │   scalar = lp(Yes) − lp(No) per candidate
                                          ▼   noul: sigmoid, choice/score: softmax, ÷ temperature
                                  {p, lock} ──▶ lock.html  ──override──▶ data/gate_log.jsonl ──▶ training rows

open_jev.train ──train_step(cross_entropy on Yes/No token)──▶ River LoRA ──save_weights──▶ river:// checkpoint
open_jev.server :8791  POST /v1/systemone  (same body/response as api.typesafe.ai)
```

## 7. How it maps to Open-Jev

| Open-Jev | This project on River |
|---|---|
| Frozen Qwen3.8-27B + LoRA r8 | Qwen3.6-35B-A3B (or 3.8-27B) + LoRA r8 via River |
| Scalar head init `lm_head[Yes] − lm_head[No]` | Read the same gap from River's top-K logprobs; `train_unembed=True` adapts the readout |
| Candidate NLL + 0.1 Brier | Per-candidate Yes/No cross-entropy, weight = target prob, record weight 1; no Brier |
| Temperature on calibration split | Same (`fit_temperature`) |
| `/v1/systemone` server on local GPU | Same API, River does the compute |

## 8. Success metrics

| Metric | Baseline (untrained base, measured) | Target |
|---|---|---|
| Open-Jev test accuracy (228 rows) | 69.7% | trained > base |
| Open-Jev test NLL, calibrated | 0.803 | trained < base |
| Open-Jev OOD accuracy (115 rows) | 75.4% | no regression |
| Gate: agreement with hand labels | TBD | > 90% |
| Gate: decision latency | ~4 s cold, 0 ms cached | < 1 s needs a deployment |
| Overrides turned into training rows | 0 | every override logged |

Trained results: see `data/runs/open-jev-river-v1-*.json` and the README results table.

## 9. Demo script (5 minutes)

1. The problem in one sentence; show a domain blocker failing on "YouTube while researching".
2. `curl` the Jev docs example at our `/v1/systemone`: same request, same typed answer shape, served from a River checkpoint.
3. Base vs trained table on Open-Jev's held-out tasks.
4. Live gate: open a manga chapter (locked, ~0.9), open River docs (through, ~0.2), open an on-task video, override it, show the new training row.
5. Close: "Jev gives everyone the same judgment. This gives you yours."

## 10. Risks

- **Latency:** River's shared pool is ~4 s per decision vs Jev's ~0.3 s. Mitigation: cache, prefetch on hover, and a dedicated deployment later.
- **Calibration without Brier:** keep steps low, fit temperature, watch calibrated NLL.
- **Labels:** rule labels teach rules. The value is in hand labels and overrides.
- **Privacy:** browsing history never leaves the laptop unless you train on it; all personal data files are gitignored.

## 11. Team and next steps

Team: Chinat Yu (cyu60), quachphu, TriNguyen1110, AdityaGaur77.

1. Finish the trained run and fill the results table.
2. Load the extension, set a task, record the demo.
3. Hand-label 150 gate rows, retrain with `--extra`, compare gate agreement.
4. Send River the API feedback (top-K logprobs as a decision readout; a per-position logits endpoint would make it one call).

## 12. Credits

Open-Jev by Zefan Cai (MIT code, Apache-2.0 weights, CC0/CC-BY-4.0 data). Jev and the System One API by TypeSafe AI. River by River AI.
