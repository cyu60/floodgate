"""Train an Open-Jev adapter on River and measure it like Open-Jev does.

Open-Jev: frozen Qwen + LoRA r8 + scalar head (init lm_head[Yes]-lm_head[No]), loss = candidate
NLL + 0.1 Brier, then one calibration temperature. River has no custom head or loss, so:
  scalar            -> logprob(Yes) - logprob(No) at the answer token (same init, no extra head)
  head training     -> LoRA with train_unembed=True (the Yes/No readout rows adapt)
  candidate loss    -> per-candidate cross_entropy on a single Yes/No target token,
                       weight = target prob, normalised so every record weighs 1 in total
  Brier term        -> dropped (custom losses unsupported)
  calibration       -> same: one temperature fitted on the calibration split

  python -m floodgate.open_jev.train --dry-run
  python -m floodgate.open_jev.train --epochs 2 --name open-jev-river-v1
  python -m floodgate.open_jev.train --extra data/gate_rows.jsonl   # opt-in: your own rows
  python -m floodgate.open_jev.train --compare models/open-jev-river-v1.json   # paired significance vs a card
"""
import argparse
import json
import random
import time
from pathlib import Path

from transformers import AutoTokenizer

from floodgate import BASE_MODEL, client
from floodgate.open_jev.core import candidate_prompts, fit_temperature, metrics, softmax
from floodgate.open_jev.scorer import Renderer, model_sampler, score_records, session_sampler

DATA = Path(__file__).resolve().parents[2] / "data"


def read(path, limit=None):
    rows = [json.loads(l) for l in Path(path).read_text().splitlines() if l.strip()]
    return rows[:limit] if limit else rows


def datums(records, r: Renderer, eos: int) -> list[dict]:
    out = []
    for rec in records:
        prompts = candidate_prompts(rec)
        tgt = rec["target"]
        # noul: 1 prompt, P(yes)=target[1]; choice/score: prompt k is "is option k correct?", P(yes)=target[k]
        p_yes = [tgt[1]] if rec["kind"] == "noul" else tgt
        norm = 1.0 / len(prompts)
        for prompt, py in zip(prompts, p_yes):
            ids = r.prompt_ids(prompt)
            for tok_id, w in ((r.yes, py), (r.no, 1.0 - py)):
                if w <= 1e-6:
                    continue
                full = ids + [tok_id]
                out.append({"input_ids": full, "target_tokens": full[1:] + [eos], "weights": [0.0] * (len(ids) - 1) + [w * norm, 0.0]})
    return out


def evaluate(name, logits, rows, temperature=1.0):
    m = metrics(logits, [r["target"] for r in rows], temperature)
    by = {}
    for k in ("noul", "choice", "score"):
        idx = [i for i, r in enumerate(rows) if r["kind"] == k]
        if idx:
            by[k] = metrics([logits[i] for i in idx], [rows[i]["target"] for i in idx], temperature)["accuracy"]
    acc = f"{m['accuracy']:.3f}" if m["accuracy"] is not None else "-"
    kinds = " ".join(f"{k}={v:.2f}" for k, v in by.items() if v is not None)
    print(f"  {name:28s} n={m['n']:4d} acc={acc} nll={m['nll']:.3f} brier={m['brier']:.3f}  [{kinds}]")
    return {**m, "by_kind": by}


def per_row(logits, rows, T):
    """(correct or None for soft targets, brier) per row, matching core.metrics."""
    out = []
    for l, rec in zip(logits, rows):
        p, t = softmax(l, T), rec["target"]
        out.append((p.index(max(p)) == t.index(1.0) if max(t) == 1.0 else None, sum((a - b) ** 2 for a, b in zip(p, t))))
    return out


def paired(name, new, old, n_boot=10000, seed=0):
    """Paired bootstrap over the same rows: accuracy gain and Brier drop of `new` over `old`, with 95% CI and
    one-sided p (share of resamples where new is not better)."""
    rng = random.Random(seed)
    idx = list(range(len(new)))
    hard = [i for i in idx if new[i][0] is not None]
    acc = lambda I: sum(new[i][0] - old[i][0] for i in I) / max(1, len(I))
    bri = lambda I: sum(old[i][1] - new[i][1] for i in I) / max(1, len(I))
    res = {}
    for key, fn, pool in (("accuracy_gain", acc, hard), ("brier_drop", bri, idx)):
        boots = sorted(fn([rng.choice(pool) for _ in pool]) for _ in range(n_boot))
        p = sum(b <= 0 for b in boots) / n_boot
        res[key] = {"delta": fn(pool), "ci95": [boots[int(0.025 * n_boot)], boots[int(0.975 * n_boot)]], "p": p}
    a, b = res["accuracy_gain"], res["brier_drop"]
    sig = lambda r: "significant" if r["p"] < 0.05 else "not significant"
    print(f"  {name:28s} acc {a['delta']:+.3f} [{a['ci95'][0]:+.3f},{a['ci95'][1]:+.3f}] p={a['p']:.3f} ({sig(a)})   "
          f"brier -{b['delta']:.3f} [{b['ci95'][0]:+.3f},{b['ci95'][1]:+.3f}] p={b['p']:.3f} ({sig(b)})")
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--name", default="open-jev-river")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--train-limit", type=int)
    ap.add_argument("--eval-limit", type=int)
    ap.add_argument("--extra", help="extra Open-Jev-style JSONL mixed into train (e.g. your gate rows)")
    ap.add_argument("--epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=96, help="records per optimizer step")
    ap.add_argument("--rank", type=int, default=8)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--skip-base", action="store_true")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--compare", action="append", default=[], help="model card(s) to score on the same splits and test the new model against (paired bootstrap)")
    a = ap.parse_args()
    if a.dry_run:
        a.train_limit, a.eval_limit, a.epochs, a.batch, a.name = a.train_limit or 48, a.eval_limit or 24, 1, 24, a.name + "-dry"

    import river_client as river

    tok = AutoTokenizer.from_pretrained(a.base)
    r = Renderer(tok)
    eos = tok.eos_token_id if tok.eos_token_id is not None else tok.convert_tokens_to_ids("<|im_end|>")
    train = read(DATA / "openjev/train.jsonl", a.train_limit)
    if a.extra:
        extra = [dict(x, source=x.get("source", "extra"), options=x.get("options", ["no", "yes"])) for x in read(a.extra)]
        train += extra
        print(f"+ {len(extra)} extra rows from {a.extra}")
    cal, test, ood = (read(DATA / f"openjev/{s}.jsonl", a.eval_limit) for s in ("cal", "test", "ood"))
    random.Random(a.seed).shuffle(train)
    batches = [train[i : i + a.batch] for i in range(0, len(train), a.batch)]
    print(f"train {len(train)} records -> {len(batches)} batches x {a.epochs} epochs; eval cal/test/ood {len(cal)}/{len(test)}/{len(ood)}; base {a.base}")

    run = {"name": a.name, "base": a.base, "rank": a.rank, "lr": a.lr, "epochs": a.epochs, "batch": a.batch, "train_rows": len(train), "steps": [], "eval": {}}
    runs = DATA / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    run_path = runs / f"{a.name}-{int(time.time())}.json"
    save = lambda: run_path.write_text(json.dumps(run, indent=2))

    with client().session(project=a.name) as session:
        if not a.skip_base:
            print("BASE (untrained = Open-Jev at step 0):")
            t0 = time.time()
            base = session_sampler(session, a.base)
            bc, bt, bo = (score_records(x, r, base) for x in (cal, test, ood))
            T0 = fit_temperature(bc, [x["target"] for x in cal])
            run["eval"]["base"] = {"temperature": T0, "test": evaluate("test (raw)", bt, test), "test_cal": evaluate(f"test (T={T0:.2f})", bt, test, T0),
                                   "ood_cal": evaluate(f"ood (T={T0:.2f})", bo, ood, T0), "sec": time.time() - t0}
            save()

        others = {}
        for card_path in a.compare:
            card = json.loads(Path(card_path).read_text())
            name = card.get("name", Path(card_path).stem)
            print(f"COMPARE {name}:")
            smp = session_sampler(session, a.base, card["checkpoint"])
            oc, ot, oo = (score_records(x, r, smp) for x in (cal, test, ood))
            To = fit_temperature(oc, [x["target"] for x in cal])
            run["eval"][name] = {"temperature": To, "test_cal": evaluate(f"test (T={To:.2f})", ot, test, To), "ood_cal": evaluate(f"ood (T={To:.2f})", oo, ood, To)}
            others[name] = (per_row(ot, test, To), per_row(oo, ood, To))
            save()

        model = session.create_model(base_model=a.base, lora=river.LoraConfig(rank=a.rank, train_attn=True, train_mlp=True, train_unembed=True), tokenizer=tok)
        print("model_id:", model.model_id)
        for ep in range(a.epochs):
            for b in batches:
                t0 = time.time()
                data = datums(b, r, eos)
                fb, _ = model.train_step(data, lr=a.lr, loss_fn="cross_entropy", grad_clip_norm=1.0)
                loss = fb.metrics.get("loss", float("nan"))
                dt = time.time() - t0
                print(f"  ep {ep} step {model.step:3d}  records={len(b):3d} datums={len(data):4d} loss/record={loss / len(b):.4f}  {dt:5.1f}s")
                run["steps"].append({"epoch": ep, "step": model.step, "loss_per_record": loss / len(b), "sec": dt})
                save()

        print("TRAINED:")
        live = model_sampler(model)
        tc, tt, to = (score_records(x, r, live) for x in (cal, test, ood))
        T = fit_temperature(tc, [x["target"] for x in cal])
        run["eval"]["trained"] = {"temperature": T, "test": evaluate("test (raw)", tt, test), "test_cal": evaluate(f"test (T={T:.2f})", tt, test, T),
                                  "ood_cal": evaluate(f"ood (T={T:.2f})", to, ood, T)}
        if others:
            print("SIGNIFICANCE (paired bootstrap, same rows; significant = p < 0.05):")
            new_t, new_o = per_row(tt, test, T), per_row(to, ood, T)
            run["significance"] = {name: {"test": paired(f"vs {name} test", new_t, ot_), "ood": paired(f"vs {name} ood", new_o, oo_)}
                                   for name, (ot_, oo_) in others.items()}
        save()
        ck = model.save_weights(a.name, mode="inference")
        run["checkpoint"] = ck.path
        run["temperature"] = T
        save()
        print("checkpoint:", ck.path, " temperature:", round(T, 3))
    print("run log:", run_path)


if __name__ == "__main__":
    main()
