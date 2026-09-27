"""Train a SemIf-style (letter readout) decision adapter on River and compare with the base.

  python -m floodgate.open_jev.train_letters --name semif-river-v1
"""
import argparse, json, random, time
from pathlib import Path
from transformers import AutoTokenizer
import floodgate  # noqa: F401
from floodgate import BASE_MODEL, client
from floodgate.open_jev.core import fit_temperature, metrics
from floodgate.open_jev.letters import letter_datums, score_letters
from floodgate.open_jev.scorer import model_sampler

DATA = Path("/Users/china/codeDev/river-ai/data/openjev")


def rep(name, logits, rows, T):
    m = metrics(logits, [r["target"] for r in rows], T)
    by = {k: metrics([logits[i] for i, r in enumerate(rows) if r["kind"] == k], [r["target"] for r in rows if r["kind"] == k], T)["accuracy"] for k in ("noul", "choice", "score")}
    print(f"  {name:10s} acc={m['accuracy']:.3f} nll={m['nll']:.3f} brier={m['brier']:.3f} {({k: round(v, 2) for k, v in by.items() if v is not None})}", flush=True)
    return {**m, "by_kind": by}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", default="semif-river-v1")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=8)
    a = ap.parse_args()
    import river_client as river
    rd = lambda f: [json.loads(l) for l in open(DATA / f)]
    train, cal, test, ood = rd("train.jsonl"), rd("cal.jsonl"), rd("test.jsonl"), rd("ood.jsonl")
    random.Random(0).shuffle(train)
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    eos = tok.eos_token_id if tok.eos_token_id is not None else tok.convert_tokens_to_ids("<|im_end|>")
    batches = [train[i:i + a.batch] for i in range(0, len(train), a.batch)]
    run = {"name": a.name, "method": "semif-letters", "base": BASE_MODEL, "rank": a.rank, "lr": a.lr, "epochs": a.epochs, "steps": []}
    out = Path("models") / f"{a.name}.json"
    with client().session(project=a.name) as s:
        model = s.create_model(base_model=BASE_MODEL, lora=river.LoraConfig(rank=a.rank, train_attn=True, train_mlp=True, train_unembed=True), tokenizer=tok)
        t00 = time.time()
        for ep in range(a.epochs):
            for b in batches:
                t0 = time.time()
                d = letter_datums(b, tok, eos)
                fb, _ = model.train_step(d, lr=a.lr, loss_fn="cross_entropy", grad_clip_norm=1.0)
                dt = time.time() - t0
                run["steps"].append({"step": model.step, "loss": fb.metrics.get("loss"), "sec": dt})
                print(f"  ep {ep} step {model.step:2d} datums={len(d)} loss={fb.metrics.get('loss', 0):.4f} {dt:5.1f}s", flush=True)
        run["train_sec"] = time.time() - t00
        live = model_sampler(model)
        lc, lt, lo = (score_letters(x, tok, live) for x in (cal, test, ood))
        T = fit_temperature(lc, [r["target"] for r in cal])
        print(f"TRAINED (letters), T={T:.2f}:", flush=True)
        run["eval"] = {"temperature": T, "test_cal": rep("test", lt, test, T), "ood_cal": rep("ood", lo, ood, T)}
        ck = model.save_weights(a.name, mode="inference")
        run.update(checkpoint=ck.path, temperature=T)
        out.write_text(json.dumps(run, indent=2))
        print("checkpoint:", ck.path, "->", out, flush=True)


if __name__ == "__main__":
    main()
