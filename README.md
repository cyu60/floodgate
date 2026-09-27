# Floodgate

**You decide what flows in.** An open Jev, trained on River AI, that stands between you and every page you open

**Own Your Intelligence Hackathon** · YC HQ, San Francisco · September 27, 2026 · hosted by River AI, GBrain, Memorable, QM, Superset and UFO.

Team: [cyu60](https://github.com/cyu60), [quachphu](https://github.com/quachphu), [TriNguyen1110](https://github.com/TriNguyen1110), [AdityaGaur77](https://github.com/AdityaGaur77), [atilavahedian](https://github.com/atilavahedian).

A calibrated decision model (an **open Jev**) trained on **River**. Floodgate asks "is this page a distraction from what I said I'm doing?" before each page loads. Read the full PRD: [docs/PRD.md](docs/PRD.md).

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

Load it: `chrome://extensions` → Developer mode → **Load unpacked** → the `extension/` folder. It works right away with a built-in offline heuristic. Set your task from the popup.

Then point it at your model (Dashboard → Model → "River open Jev (gate server)"):

```bash
python -m floodgate.gate_server --task "finish the hackathon demo" --run data/runs/open-jev-river-v1-*.json
python3 tools/mock_gate.py        # same API with no River, for building and demoing the extension
```

Full guide (features, modes, the gate server contract, how teammates plug in GBrain/QM providers, demo script): [extension/README.md](extension/README.md).

## Layout

| Path | What |
|---|---|
| `floodgate/open_jev/core.py` | Open-Jev's request compiler, candidate prompts, typed responses, calibration (ported, MIT) |
| `floodgate/open_jev/scorer.py` | Yes/No logprob gap per candidate on River |
| `floodgate/open_jev/train.py` | LoRA training on River + base vs trained eval + temperature |
| `floodgate/open_jev/server.py` | `POST /v1/systemone`, same body and response as Jev |
| `floodgate/gate_server.py`, `extension/` | The Floodgate browser gate ([guide](extension/README.md)) |
| `tools/mock_gate.py` | Same HTTP contract as the gate server, no River: for extension work |
| `floodgate/label_*`, `tools/label.html` | Labelling loop for personal gate rows |
| `docs/` | PRD, River API guide and reference |

## Credits

[Open-Jev](https://github.com/Zefan-Cai/Open-Jev) by Zefan Cai · Jev by [TypeSafe AI](https://docs.typesafe.ai) · [River AI](https://docs.river.ai).
