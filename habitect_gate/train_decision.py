"""Open-Jev-on-River: LoRA SFT with a single Yes/No target token and soft labels.

Open-Jev trains LoRA + a scalar head (init = lm_head[Yes]-lm_head[No]) with candidate NLL +
0.1 Brier. River has no custom head or loss, so we use the closest thing it does have:
  * target token = "Yes" or "No" at the answer position (cross_entropy, weights mask the prompt)
  * soft label p -> two rows for the same prompt, target Yes weighted p and No weighted 1-p
    (weighted cross-entropy = cross-entropy against the soft distribution)
  * train_unembed=True so the Yes/No readout rows themselves adapt, like the head
  * calibration temperature fit in code afterwards on held-out rows (see jev_probe.noul)
Reads Open-Jev-style rows: {state, question, kind:"noul", target:[p_no, p_yes]}.

  python -m habitect_gate.train_decision --data data/gate_rows.jsonl --dry-run
  python -m habitect_gate.train_decision --data data/gate_rows.jsonl --steps 30 --name habitect-gate-v1
"""
import argparse
import json
import random
import time
from pathlib import Path

from transformers import AutoTokenizer

from habitect_gate import BASE_MODEL, client
from habitect_gate.jev_probe import noul, render

DATA = Path(__file__).resolve().parent.parent / "data"


def rows_to_data(tok, rows, eos):
    yes = tok.encode("Yes", add_special_tokens=False)
    no = tok.encode("No", add_special_tokens=False)
    assert len(yes) == 1 and len(no) == 1, "Yes/No must be single tokens"
    out = []
    for r in rows:
        assert r["kind"] == "noul"
        p_no, p_yes = r["target"]
        prompt_ids = tok(render(tok, r["state"], r["question"]), add_special_tokens=False)["input_ids"]
        for tok_id, w in ((yes[0], p_yes), (no[0], p_no)):
            if w <= 0.0:
                continue
            ids = prompt_ids + [tok_id]
            out.append({"input_ids": ids, "target_tokens": ids[1:] + [eos], "weights": [0.0] * (len(prompt_ids) - 1) + [w, 0.0]})
    return out


def brier(preds, rows):
    return sum((p["p_yes"] - r["target"][1]) ** 2 for p, r in zip(preds, rows)) / len(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(DATA / "gate_rows.jsonl"))
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--name", default="habitect-gate")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--steps", type=int, default=30)
    ap.add_argument("--rank", type=int, default=16)
    ap.add_argument("--lr", type=float, default=5e-5)
    ap.add_argument("--micro", type=int, default=0)
    ap.add_argument("--holdout", type=int, default=100)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    if a.dry_run:
        a.limit, a.steps, a.rank, a.name = a.limit or 60, 3, 8, a.name + "-dry"

    import river_client as river

    rows = [json.loads(l) for l in Path(a.data).read_text().splitlines() if l.strip()]
    random.Random(a.seed).shuffle(rows)
    held, train = rows[: a.holdout], rows[a.holdout :]
    if a.limit:
        train = train[: a.limit]
        held = held[: max(10, a.limit // 5)]
    tok = AutoTokenizer.from_pretrained(a.base)
    eos = tok.eos_token_id if tok.eos_token_id is not None else tok.convert_tokens_to_ids("<|im_end|>")
    batch = rows_to_data(tok, train, eos)
    micro = a.micro or len(batch)
    chunks = [batch[i : i + micro] for i in range(0, len(batch), micro)]
    print(f"{len(train)} rows -> {len(batch)} weighted datums, {sum(len(d['input_ids']) for d in batch):,} tokens/step; holdout {len(held)}")

    c = client()
    with c.session(project=a.name) as session:
        base_preds = noul(session, tok, [(r["state"], r["question"]) for r in held], a.base)
        print(f"BASE  holdout Brier={brier(base_preds, held):.4f}  acc={sum((p['p_yes'] >= .5) == (r['target'][1] >= .5) for p, r in zip(base_preds, held)) / len(held):.3f}")

        model = session.create_model(base_model=a.base, lora=river.LoraConfig(rank=a.rank, train_unembed=True), tokenizer=tok)
        for step in range(a.steps):
            t0 = time.time()
            loss = 0.0
            for i, ch in enumerate(chunks):
                loss += model.forward_backward(ch, loss_fn="cross_entropy", zero_out=(i == 0)).metrics["loss"]
            model.optim_step(lr=a.lr, grad_clip_norm=1.0)
            print(f"step {model.step:3d}  loss={loss:10.3f}  per_row={loss / len(train):.4f}  {time.time() - t0:5.1f}s")

        ck = model.save_weights(a.name, mode="inference")
        preds = noul(session, tok, [(r["state"], r["question"]) for r in held], a.base, checkpoint=ck)
        print(f"TWIN  holdout Brier={brier(preds, held):.4f}  acc={sum((p['p_yes'] >= .5) == (r['target'][1] >= .5) for p, r in zip(preds, held)) / len(held):.3f}")
        print("checkpoint:", ck.path)
        (DATA / "runs").mkdir(parents=True, exist_ok=True)
        (DATA / "runs" / f"{a.name}-{int(time.time())}.json").write_text(json.dumps({"checkpoint": ck.path, "base": a.base, "rank": a.rank, "steps": a.steps, "rows": len(train)}, indent=2))


if __name__ == "__main__":
    main()
