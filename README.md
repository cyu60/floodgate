# Floodgate

**You decide what flows in.** An open Jev, trained on River AI, that stands between you and every page you open

**Own Your Intelligence Hackathon** · YC HQ, San Francisco · September 27, 2026 · hosted by River AI, GBrain, Memorable, QM, Superset and UFO.

Team: [cyu60](https://github.com/cyu60), [quachphu](https://github.com/quachphu), [TriNguyen1110](https://github.com/TriNguyen1110), [AdityaGaur77](https://github.com/AdityaGaur77).

A calibrated decision model (an **open Jev**) trained on **River**. Floodgate asks "is this page a distraction from what I said I'm doing?" before each page loads. Read the full PRD: [docs/PRD.md](docs/PRD.md).

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
