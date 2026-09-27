"""Ensemble existing River checkpoints without training: score each card on the same cal/test/ood rows,
calibrate each with its own temperature, average the probabilities, and compare with each model alone.

  python -m floodgate.open_jev.ensemble models/open-jev-river-v1.json models/semif-river-v1.json

Cards with "method": "semif-letters" (train_letters.py) are read with the letter prompt, others with
the per-candidate Yes/No prompt. Also reports a paired bootstrap of the ensemble vs the first card.
"""
import argparse, json, math
from pathlib import Path
from transformers import AutoTokenizer
import floodgate  # noqa: F401
from floodgate import BASE_MODEL, client
from floodgate.open_jev.core import fit_temperature, softmax
from floodgate.open_jev.letters import score_letters
from floodgate.open_jev.scorer import Renderer, score_records, session_sampler
from floodgate.open_jev.train import DATA, evaluate, paired, per_row, read

SPLITS = ("cal", "test", "ood")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cards", nargs="+")
    ap.add_argument("--name", default="ensemble")
    a = ap.parse_args()
    rows = {s: read(DATA / f"openjev/{s}.jsonl") for s in SPLITS}
    tok = AutoTokenizer.from_pretrained(BASE_MODEL); r = Renderer(tok)
    probs, names, out = [], [], {"name": a.name, "members": [], "eval": {}}
    with client().session(project=a.name) as s:
        for path in a.cards:
            card = json.loads(Path(path).read_text())
            name = card.get("name", Path(path).stem)
            smp = session_sampler(s, BASE_MODEL, card["checkpoint"])
            letters = card.get("method") == "semif-letters"
            lg = {k: (score_letters(v, tok, smp) if letters else score_records(v, r, smp)) for k, v in rows.items()}
            T = fit_temperature(lg["cal"], [x["target"] for x in rows["cal"]])
            print(f"{name} ({'letters' if letters else 'per-option'}), T={T:.2f}:", flush=True)
            out["eval"][name] = {k: evaluate(k, lg[k], rows[k], T) for k in ("test", "ood")}
            probs.append({k: [softmax(l, T) for l in lg[k]] for k in SPLITS})
            names.append(name); out["members"].append({"name": name, "checkpoint": card["checkpoint"], "temperature": T, "letters": letters})
    # average calibrated probabilities; log() so evaluate/per_row (which softmax) get them back at T=1
    avg = {k: [[math.log(max(sum(p[k][i][j] for p in probs) / len(probs), 1e-12)) for j in range(len(probs[0][k][i]))]
               for i in range(len(rows[k]))] for k in SPLITS}
    print(f"ENSEMBLE (mean of {len(probs)} calibrated models):")
    out["eval"]["ensemble"] = {k: evaluate(k, avg[k], rows[k]) for k in ("test", "ood")}
    first = [[math.log(max(q, 1e-12)) for q in p] for p in probs[0]["test"]], [[math.log(max(q, 1e-12)) for q in p] for p in probs[0]["ood"]]
    print(f"SIGNIFICANCE vs {names[0]} (paired bootstrap, significant = p < 0.05):")
    out["significance"] = {"test": paired("test", per_row(avg["test"], rows["test"], 1.0), per_row(first[0], rows["test"], 1.0)),
                           "ood": paired("ood", per_row(avg["ood"], rows["ood"], 1.0), per_row(first[1], rows["ood"], 1.0))}
    Path("models", f"{a.name}.json").write_text(json.dumps(out, indent=2))
    print(f"-> models/{a.name}.json")


if __name__ == "__main__":
    main()
