# Floodgate

**You decide what flows in.** An open Jev, trained on River AI, that stands between you and every page you open

**Own Your Intelligence Hackathon** · YC HQ, San Francisco · September 27, 2026 · hosted by River AI, GBrain, Memorable, QM, Superset and UFO.

Team: [cyu60](https://github.com/cyu60), [quachphu](https://github.com/quachphu), [TriNguyen1110](https://github.com/TriNguyen1110), [AdityaGaur77](https://github.com/AdityaGaur77), [atilavahedian](https://github.com/atilavahedian).

A calibrated decision model (an **open Jev**) trained on **River**. Floodgate asks "is this page a distraction from what I said I'm doing?" before each page loads. Read the full PRD: [docs/PRD.md](docs/PRD.md). The pitch story and open team decisions: [docs/STORY-AND-DISCUSSION.md](docs/STORY-AND-DISCUSSION.md). Independent Codex review and how we win: [docs/CODEX-REVIEW.md](docs/CODEX-REVIEW.md).

## What we built today

In one afternoon at the Own Your Intelligence Hackathon, we went from "can an open Jev run on River?" to a trained, calibrated, served model driving a browser gate:

1. **Proved the core idea on River.** Open-Jev's decision head starts as `logit(Yes) − logit(No)`. River returns exactly that from any open model, so an untrained model on River already behaves like Open-Jev at step 0. No GPU, no custom head.
2. **Ported Open-Jev's System One API** (noul, choice, score, confidence, legend) so requests and responses are byte-compatible with Jev's `POST /v1/systemone`.
3. **Trained our own open Jev on River**: `open-jev-river-v1`, 20 training steps in 23 minutes of River compute, on a stratified sample of Open-Jev's public data. Calibrated test accuracy went **69.7% → 86.2%**, and **75.4% → 87.7%** on task types it never saw.
4. **Served it as a Jev-compatible API.** The same `curl` that works against TypeSafe's Jev works against our checkpoint.
5. **Built Floodgate**, a Chrome extension plus local gate. It asks the model "is this page a distraction from my stated task?" on every navigation, locks the page above a threshold, and logs every "this is on task" override as a new training row.
6. **Benchmarked against real Jev.** Our trained model matches or beats Jev on the obvious calls. Neither model knows where *your* task begins and ends, and that is the gap Floodgate closes with personal training.
7. **Shipped it in the open**: this repo, a PRD ([docs/PRD.md](docs/PRD.md)), a shareable model card, and an MIT licence crediting Open-Jev.

## How Floodgate builds on Open-Jev and River

### In plain words

**Jev** (by TypeSafe AI) is a new kind of AI model that never writes text. You describe a situation and ask a question, and it points to a spot on a dial: a yes/no probability, a pick from a list, or a score. Those numbers are calibrated, so "0.8" means right about 80% of the time. That makes it perfect for software decisions like "should this page be blocked?". But Jev is closed: everyone gets the same model, and you cannot train it on your own judgment.

**Open-Jev** (by Zefan Cai) is an open-source recreation of Jev. Its key trick is simple: to ask "is this answer correct?", it looks at how strongly an ordinary open model leans toward saying "Yes" versus "No", then trains that lean with a thin add-on layer (a LoRA) until the lean becomes an honest probability. It gets within 3 tasks of Jev on the public JevBench (197 vs 200 of 231).

**River** is an API that lets you train open models on your own data without owning GPUs. It gives you exactly the ingredients Open-Jev needs: open models, a way to read how strongly the model leans toward each next word, LoRA training, and saved models you own and can share.

**Floodgate** puts these together. We took Open-Jev's design (how questions are asked, how answers are formatted, how confidence is calibrated) and rebuilt it on River, so anyone can train their own Jev-style decision model. Then we point it at the most personal decision there is: *is this page a distraction from what I said I'm doing?* Trained on your own browsing and your own overrides, it learns your boundaries, which is something neither Jev nor any general model can know.

### What we took from Open-Jev, and how it maps onto River

| Open-Jev piece | What it does | How Floodgate does it on River |
|---|---|---|
| System One API (`state` + typed `questions`) | One request, many independent questions: noul (yes/no), choice, score | Ported as-is (`floodgate/open_jev/core.py`). Same request body and response shape as Jev's `POST /v1/systemone` |
| Candidate prompts | Each option becomes its own "Is this proposed answer correct? Answer Yes or No." prompt | Same text, same chat template, thinking mode off |
| Decision head, initialised as `lm_head[Yes] − lm_head[No]` | Turns the model's last state into one score per candidate | We read that exact quantity from River: sample one token with top-20 logprobs, score = logprob(Yes) − logprob(No) (`scorer.py`). The untrained base on River is Open-Jev at step 0 |
| Scores to probabilities | Noul = sigmoid of the score; choice/score = softmax across candidates | Same (`record_logits`, `softmax`) |
| Training: LoRA r8 + head, candidate NLL + 0.1 Brier | Teach the lean to match the answer key | River LoRA r8 with `train_unembed=True` (the Yes/No readout adapts, like the head). Loss = cross-entropy on a single Yes/No target token per candidate, weighted by the target probability, each question weighing 1 in total (`train.py`) |
| Calibration temperature | One number fitted on a held-out split so probabilities are honest | Same (`fit_temperature` on the calibration split) |
| Public v1.1 dataset | 147K typed decision rows across ~30 task families | Stratified sample: 1,164 train / 140 calibration / 228 test / 115 OOD rows, 18 families (`data.py`) |
| Local GPU server | Serves `/v1/systemone` | Same endpoint, River does the compute (`server.py`); the Floodgate browser gate calls it (`gate_server.py`) |

### What is different from Open-Jev (honest limits)

- **No separate head and no Brier term.** River does not support custom heads or custom losses, so we train the model's own Yes/No readout with plain cross-entropy and rely on the temperature for calibration.
- **Choice is trained per candidate, not as one softmax.** Each option is its own yes/no example; at answer time we still softmax across options exactly like Open-Jev.
- **Coarse readout.** River returns rounded logprobs (for example Yes −0.63, No −1.00), so untrained scores cluster; training spreads them out.
- **Latency.** River's shared pool takes seconds per batch; Jev takes 0.1–0.4 s. Fine for a demo with caching, a dedicated deployment for real use.
- **Scale.** Open-Jev trained on 148K rows for 37K steps; our hackathon run uses ~1.2K rows for 20 steps. The point is the pipeline and personalisation, not beating Jev on benchmarks.

### How a training run works

```
Open-Jev public rows ──▶ each option becomes a Yes/No check ──▶ River train_step (cross-entropy on the Yes/No token)
                                                                  │  20 steps × ~128 questions, ~85 s each
                                                                  ▼
                                    trained LoRA checkpoint (river://…) + calibration temperature
                                                                  │
         exam on unseen test + OOD rows (base vs trained)  ◀──────┤
                                                                  ▼
                        /v1/systemone server ──▶ Floodgate gate ──▶ Chrome extension (lock / let through)
                                                                  ▲
                                   your overrides ("this is on task") become new training rows
```

1. **Textbook:** questions with answer keys (Open-Jev's public set now; your browsing labels next).
2. **Practice:** every option becomes "is this correct? Yes/No"; River measures how far the model's lean is from the key and nudges a thin LoRA layer. The big model underneath is never changed.
3. **Exam:** unseen test questions and task types the model never saw, compared with the untrained model.
4. **Confidence dial:** one temperature so that 0.8 means about 80%.
5. **Use it:** the saved checkpoint serves Jev-format answers; Floodgate asks it about every page you open.
6. **Make it yours:** train again with `--extra your_rows.jsonl`. The result is a `river://` checkpoint you own and can share.

## The custom model: `open-jev-river-v1`

### What it is

| | |
|---|---|
| Base model | `Qwen/Qwen3.6-35B-A3B-FP8` (open, mixture-of-experts, ~3B active parameters), unchanged |
| What we trained | A LoRA adapter, rank 8, on attention + MLP layers, plus the output readout (`train_unembed=True`) so the Yes/No lean itself adapts, playing the role of Open-Jev's decision head |
| Decision score | `logprob(Yes) − logprob(No)` at the first answer token, one per candidate |
| Calibration | One temperature, **T = 3.31**, fitted on 140 held-out calibration rows |
| Where it lives | A River checkpoint: `river://6ce27692-…/sampler_weights/open-jev-river-v1` ([model card](models/open-jev-river-v1.json)) |
| How to use it | `python -m floodgate.open_jev.server --run models/open-jev-river-v1.json`, then `POST /v1/systemone` |

### How it was trained

| Setting | Value |
|---|---|
| Data | 1,164 rows sampled from [Open-Jev v1.1](https://huggingface.co/datasets/ZefanCai/Open-Jev-v1.1): 240 natural-language-inference rows (WANLI) + 56 each from 17 task families (browser control, citations, customer support, email selection, mailroom, retrieval, workflows, games such as Snake, tic-tac-toe, ViZDoom, platformers, and more) |
| Mix | 666 choice, 368 noul, 130 score questions → ~4,300 Yes/No checks per epoch |
| Schedule | 2 epochs × 10 batches of 128 questions = 20 optimizer steps (AdamW, lr 2e-4, grad clip 1.0) |
| Loss | Cross-entropy on one Yes/No token per candidate, weighted by the target probability; every question weighs 1 |
| Time | 23 minutes of training (69 s per step on average) + ~1 minute per evaluation pass |
| Hardware we needed | None. River ran every forward pass, backward pass and optimizer step |

The training loss fell steadily from 0.0018 to 0.0003 per question over the full batches (the two small end-of-epoch batches of 12 questions are noisier).

### The gains

Held-out Open-Jev rows the model never trained on, each model scored with its own fitted temperature:

| Split | Metric | Untrained base | `open-jev-river-v1` | Change |
|---|---|---:|---:|---:|
| Test (228) | Accuracy | 69.7% | **86.2%** | +16.5 pts |
| | Log loss | 0.803 | **0.450** | −44% |
| | Brier score | 0.410 | **0.221** | −46% |
| OOD (115, task types held out) | Accuracy | 75.4% | **87.7%** | +12.3 pts |
| | Log loss | 0.610 | **0.378** | −38% |
| | Brier score | 0.336 | **0.211** | −37% |

By question type:

| Type | Test before → after | OOD before → after |
|---|---|---|
| Noul (yes/no) | 0.88 → **0.93** | 0.92 → **0.94** |
| Choice (pick one) | 0.63 → **0.81** | 0.65 → **0.80** |
| Score (rubric level) | 0.50 → **0.89** | 0.57 → **0.93** |

What this means:
- **Accuracy:** it picks the right answer far more often, especially on multiple choice and rubric scores, where the untrained model was close to guessing.
- **Log loss and Brier:** its probabilities are much more honest. Confident answers are right more often, and unsure answers are actually unsure. This is what lets Floodgate use a plain threshold like "lock above 0.7".
- **OOD:** the gains hold on task families it never saw, so it learned the general skill of judging a candidate against a context, not just these datasets.

For scale: Open-Jev's 27B model reaches 98.3% on its own internal test set after 37,160 steps on 148,639 rows. We used 0.8% of that data and 0.05% of the steps. The point is not to beat it, but to show the whole loop (train, calibrate, evaluate, serve, personalise) runs on River in an afternoon.

### On the Floodgate question, versus Jev

Task: "research TypeSafe's Jev model for the hackathon". Question: "Is this page a distraction from the stated task?"

| Page | Jev 1.13 | `open-jev-river-v1` |
|---|---:|---:|
| Fireship video on Jev (on task) | 0.57 | 0.53 |
| Satellite-launch explainer (informative, off task) | 0.95 | 0.96 |
| TypeSafe's own Noul docs (on task) | 0.76 | 0.58 |
| GTA 6 gameplay | 0.96 | 0.97 |
| Same satellite video, task = "report on launch failures" | 0.35 | 0.42 |

It matches or beats Jev on the clear calls, and scores the on-task TypeSafe docs as less of a distraction than Jev does (0.58 vs 0.76). But both models still sit near the middle on pages whose meaning depends on *your* task. General training makes a good judge. Only your own labels and overrides teach it your boundaries, which is the next training round (`--extra your_rows.jsonl`).

### Sharing it

The model is a file-like `river://` path plus one temperature, captured in [`models/open-jev-river-v1.json`](models/open-jev-river-v1.json). Anyone with access to the training account can serve it with one command. Handing someone your personal Floodgate model is handing them that card.

## Quick start

```bash
uv venv -p 3.13 .venv && source .venv/bin/activate
uv pip install river-client transformers jinja2 pyarrow
export RIVER_API_KEY=rv_...          # your River key

python -m floodgate.check_access                     # models your key can use
python -m floodgate.open_jev.data                    # sample Open-Jev's public v1.1 corpus
python -m floodgate.open_jev.train --dry-run         # 2 steps end to end (~3 min)
python -m floodgate.open_jev.train --epochs 2 --batch 128 --lr 2e-4 --name open-jev-river-v1
python -m floodgate.open_jev.server --run data/runs/open-jev-river-v1-*.json   # Jev-compatible API on :8791
```

Try it with the request from Jev's docs:

```bash
curl -s localhost:8791/v1/systemone -H 'Content-Type: application/json' -d '{
  "state": "I was charged twice for my September invoice and I want my money back today.",
  "questions": {
    "refund_requested": {"type":"noul","instructions":"Is a refund explicitly requested?"},
    "intent": {"type":"choice","instructions":"Choose the customer intent.",
               "criteria":{"billing":"A payment or refund issue","technical":"A malfunction or setup issue","other":"Another request"}}
  }}'
```

## The browser gate (Floodgate extension)

```bash
python -m floodgate.gate_server --task "finish the hackathon demo" --run data/runs/open-jev-river-v1-*.json
```

Then open `chrome://extensions`, enable Developer mode, and **Load unpacked** the `extension/` folder. Set your task from the extension popup.

## Layout

| Path | What |
|---|---|
| `floodgate/open_jev/core.py` | Open-Jev's request compiler, candidate prompts, typed responses, calibration (ported, MIT) |
| `floodgate/open_jev/scorer.py` | Yes/No logprob gap per candidate on River |
| `floodgate/open_jev/train.py` | LoRA training on River + base vs trained eval + temperature |
| `floodgate/open_jev/server.py` | `POST /v1/systemone`, same body and response as Jev |
| `floodgate/gate_server.py`, `extension/` | The Floodgate browser gate |
| `floodgate/label_*`, `tools/label.html` | Labelling loop for personal gate rows |
| `docs/` | PRD, River API guide and reference |

## Credits

[Open-Jev](https://github.com/Zefan-Cai/Open-Jev) by Zefan Cai · Jev by [TypeSafe AI](https://docs.typesafe.ai) · [River AI](https://docs.river.ai).
