"""Train Floodgate on YOUR labels (data/gate_labels.jsonl from the label tool) on River, and test it honestly.

Holds out ~25% of your labelled pages (split by URL, so no page is in both train and test), then compares
on those held-out pages: untrained base  vs  public open-jev-river-v1  vs  your personal adapter.
Trains on YOUR labels only by default (--public 0). The public model is only used as a comparison baseline.

  python -m floodgate.open_jev.train_personal --labels /Users/china/codeDev/river-ai/data/gate_labels.jsonl
"""
import argparse, json, random, time
from pathlib import Path
from transformers import AutoTokenizer
import floodgate  # noqa: F401
from floodgate import BASE_MODEL, client
from floodgate.open_jev.scorer import Renderer, model_sampler, score_records, session_sampler
from floodgate.open_jev.train import datums
from floodgate.open_jev.core import softmax

PUBLIC = Path("/Users/china/codeDev/river-ai/data/openjev/train.jsonl")
PUBLIC_CARD = Path(__file__).resolve().parents[2] / "models" / "open-jev-river-v1.json"


def url_of(r):
    return (r.get("metadata") or {}).get("url") or r["state"].split(" Title:")[0]


def report(name, logits, rows, T=1.0):
    ps = [softmax(l, T)[1] for l in logits]
    acc = sum((p >= 0.5) == (r["target"][1] >= 0.5) for p, r in zip(ps, rows)) / len(rows)
    brier = sum((p - r["target"][1]) ** 2 for p, r in zip(ps, rows)) / len(rows)
    print(f"  {name:32s} agree-with-you={acc:.3f}  brier={brier:.3f}  (n={len(rows)})", flush=True)
    return {"agreement": acc, "brier": brier, "probs": ps}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--labels", default="/Users/china/codeDev/river-ai/data/gate_labels.jsonl")
    ap.add_argument("--name", default="floodgate-personal-v1")
    ap.add_argument("--holdout", type=float, default=0.25)
    ap.add_argument("--public", type=int, default=0, help="public rows mixed in (default 0: YOUR data only)")
    ap.add_argument("--repeat", type=int, default=3, help="times your rows are repeated per epoch")
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    import river_client as river
    rows = [json.loads(l) for l in open(a.labels) if l.strip()]
    rng = random.Random(a.seed)
    urls = sorted({url_of(r) for r in rows}); rng.shuffle(urls)
    test_urls = set(urls[: max(1, int(len(urls) * a.holdout))])
    test = [r for r in rows if url_of(r) in test_urls]
    mine = [r for r in rows if url_of(r) not in test_urls]
    pos = sum(r["target"][1] >= 0.5 for r in rows)
    print(f"{len(rows)} labels ({pos} distraction / {len(rows)-pos} work) -> train {len(mine)} / held-out {len(test)} (by URL)", flush=True)
    public = []
    if a.public:
        public = [json.loads(l) for l in open(PUBLIC)]; rng.shuffle(public); public = public[: a.public]
    pool = mine * a.repeat + public; rng.shuffle(pool)
    per = max(1, len(pool) // a.steps)
    tok = AutoTokenizer.from_pretrained(BASE_MODEL); r = Renderer(tok)
    eos = tok.eos_token_id if tok.eos_token_id is not None else tok.convert_tokens_to_ids("<|im_end|>")
    card = json.loads(PUBLIC_CARD.read_text())
    out = {"name": a.name, "labels": len(rows), "train_personal": len(mine), "heldout": len(test), "public_mixed": len(public), "eval": {}}
    with client().session(project=a.name) as s:
        print("HELD-OUT pages you labelled:", flush=True)
        out["eval"]["base"] = report("untrained base", score_records(test, r, session_sampler(s, BASE_MODEL)), test)
        out["eval"]["public"] = report("public model (open-jev-river-v1)", score_records(test, r, session_sampler(s, BASE_MODEL, card["checkpoint"])), test, card["temperature"])
        model = s.create_model(base_model=BASE_MODEL, lora=river.LoraConfig(rank=a.rank, train_attn=True, train_mlp=True, train_unembed=True), tokenizer=tok)
        t0 = time.time()
        for i in range(a.steps):
            b = pool[i * per:(i + 1) * per] or pool[:per]
            fb, _ = model.train_step(datums(b, r, eos), lr=a.lr, loss_fn="cross_entropy", grad_clip_norm=1.0)
            print(f"  step {model.step} rows={len(b)} loss={fb.metrics.get('loss', 0):.4f} {time.time()-t0:5.0f}s", flush=True)
        out["eval"]["personal"] = report("YOUR model (personal)", score_records(test, r, model_sampler(model)), test)
        ck = model.save_weights(a.name, mode="inference")
        out.update(checkpoint=ck.path, temperature=1.0)
    print("\nper held-out page (you / base / public / yours):")
    for i, row in enumerate(test):
        print(f"  {row['target'][1]:.2f} / {out['eval']['base']['probs'][i]:.2f} / {out['eval']['public']['probs'][i]:.2f} / {out['eval']['personal']['probs'][i]:.2f}  {row['state'][:110]}")
    for k in out["eval"]: out["eval"][k].pop("probs", None)
    Path("models", f"{a.name}.json").write_text(json.dumps(out, indent=2))
    print("checkpoint:", out["checkpoint"])


if __name__ == "__main__":
    main()
