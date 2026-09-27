"""Post-train an open Jev locally, no River and no API key. Same recipe as train.py / train_personal.py
(LoRA, cross-entropy on one Yes/No token per candidate, score = logit(Yes) - logit(No)) but on a small
open model running on your own machine (Apple MPS, CUDA or CPU).

  pip install torch transformers peft pyarrow huggingface_hub
  python -m floodgate.open_jev.data --train 400 --cal 60 --test 120 --ood 60     # public rows, no key
  python -m floodgate.open_jev.train_local                                        # train on them + eval
  python -m floodgate.open_jev.train_local --labels gate_labels.jsonl             # or on YOUR labels
"""
import argparse, json, random, time
from pathlib import Path
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import LoraConfig, get_peft_model
from floodgate.open_jev.core import candidate_prompts, record_logits, softmax
from floodgate.open_jev.scorer import Renderer
from floodgate.open_jev.train_personal import url_of

ROOT = Path(__file__).resolve().parents[2]


def device():
    if torch.cuda.is_available(): return "cuda"
    if torch.backends.mps.is_available(): return "mps"
    return "cpu"


def gaps(model, r, prompts, dev, bs=8):
    """logit(Yes) - logit(No) at the first answer token, one per prompt."""
    out = []
    r.tok.padding_side = "left"
    for i in range(0, len(prompts), bs):
        enc = r.tok([r.chat(p) for p in prompts[i:i + bs]], return_tensors="pt", padding=True, add_special_tokens=False).to(dev)
        with torch.no_grad():
            last = model(**enc).logits[:, -1, :].float()
        out += (last[:, r.yes] - last[:, r.no]).tolist()
    return out


def score(model, r, rows, dev):
    flat, counts = [], []
    for rec in rows:
        ps = candidate_prompts(rec); counts.append(len(ps)); flat += ps
    g, out, k = gaps(model, r, flat, dev), [], 0
    for rec, c in zip(rows, counts):
        out.append(record_logits(rec["kind"], g[k:k + c])); k += c
    return out


def report(name, logits, rows):
    """accuracy = argmax matches target argmax; brier over the full distribution."""
    acc = brier = 0.0
    for l, rec in zip(logits, rows):
        p, t = softmax(l, 1.0), rec["target"]
        acc += max(range(len(p)), key=p.__getitem__) == max(range(len(t)), key=t.__getitem__)
        brier += sum((a - b) ** 2 for a, b in zip(p, t))
    acc, brier = acc / len(rows), brier / len(rows)
    print(f"  {name:10s} accuracy={acc:.3f}  brier={brier:.3f}  (n={len(rows)})", flush=True)
    return {"accuracy": acc, "brier": brier}


def examples(rows, r):
    """(prompt_ids, Yes/No token, weight) per candidate, same weighting as train.datums."""
    out = []
    for rec in rows:
        ps, tgt = candidate_prompts(rec), rec["target"]
        p_yes = [tgt[1]] if rec["kind"] == "noul" else tgt
        for p, py in zip(ps, p_yes):
            ids = r.prompt_ids(p)
            for tok, w in ((r.yes, py), (r.no, 1.0 - py)):
                if w > 1e-6: out.append((ids, tok, w / len(ps)))
    return out


def load(path):
    return [json.loads(l) for l in open(path) if l.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="Qwen/Qwen3-0.6B")
    ap.add_argument("--labels", help="your gate_labels.jsonl (held out by URL); default: public data/openjev splits")
    ap.add_argument("--name", default="floodgate-local-v1")
    ap.add_argument("--train-rows", type=int, default=300)
    ap.add_argument("--test-rows", type=int, default=100)
    ap.add_argument("--epochs", type=int, default=1)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--lr", type=float, default=2e-4)
    ap.add_argument("--rank", type=int, default=8)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    rng = random.Random(a.seed); torch.manual_seed(a.seed)
    if a.labels:
        rows = load(a.labels)
        urls = sorted({url_of(x) for x in rows}); rng.shuffle(urls)
        held = set(urls[: max(1, len(urls) // 4)])
        train = [x for x in rows if url_of(x) not in held]; test = [x for x in rows if url_of(x) in held]
    else:
        d = ROOT / "data" / "openjev"
        if not (d / "train.jsonl").exists():
            raise SystemExit("no data: run  python -m floodgate.open_jev.data --train 400 --cal 60 --test 120 --ood 60  first")
        train, test = load(d / "train.jsonl"), load(d / "test.jsonl")
        rng.shuffle(train); rng.shuffle(test)
    train, test = train[: a.train_rows], test[: a.test_rows]
    dev = device()
    print(f"{a.model} on {dev}: train {len(train)} rows, held-out {len(test)} rows", flush=True)

    tok = AutoTokenizer.from_pretrained(a.model)
    if tok.pad_token is None: tok.pad_token = tok.eos_token
    r = Renderer(tok)
    dtype = torch.float32 if dev == "cpu" else torch.bfloat16
    model = AutoModelForCausalLM.from_pretrained(a.model, torch_dtype=dtype).to(dev).eval()
    out = {"name": a.name, "base_model": a.model, "train_rows": len(train), "heldout": len(test), "eval": {}}
    print("HELD-OUT:", flush=True)
    out["eval"]["base"] = report("base", score(model, r, test, dev), test)

    model = get_peft_model(model, LoraConfig(r=a.rank, lora_alpha=2 * a.rank, target_modules="all-linear", task_type="CAUSAL_LM"))
    opt = torch.optim.AdamW([p for p in model.parameters() if p.requires_grad], lr=a.lr)
    ex = examples(train, r)
    t0, step = time.time(), 0
    model.train()
    for ep in range(a.epochs):
        rng.shuffle(ex)
        for i in range(0, len(ex), a.batch):
            loss = 0.0
            for ids, tok_id, w in ex[i:i + a.batch]:
                logits = model(input_ids=torch.tensor([ids], device=dev)).logits[0, -1].float()
                loss = loss - w * torch.log_softmax(logits, -1)[tok_id]
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0); opt.step(); step += 1
            if step % 10 == 0:
                print(f"  epoch {ep} step {step}/{a.epochs * ((len(ex) + a.batch - 1) // a.batch)} loss={loss.item():.4f} {time.time() - t0:5.0f}s", flush=True)
    model.eval()
    out["eval"]["trained"] = report("trained", score(model, r, test, dev), test)
    out["train_seconds"] = round(time.time() - t0)
    adapter = ROOT / "data" / "runs" / a.name
    model.save_pretrained(adapter); out["adapter"] = str(adapter.relative_to(ROOT))
    Path(ROOT / "models", f"{a.name}.json").write_text(json.dumps(out, indent=2))
    print(f"saved adapter to {adapter} and card to models/{a.name}.json")


if __name__ == "__main__":
    main()
