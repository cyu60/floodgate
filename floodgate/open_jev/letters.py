"""SemIf-style readout on River: all options in ONE prompt, labelled A, B, C...; read the
logprobs of those letter tokens at the first answer position (one call per question instead
of one per option). Inspired by SemIf (github.com/TheoLeeCJ/SemIf-OpenJev, MIT).

Training with this format on River is plain SFT: target token = the correct letter
(soft targets = one weighted datum per letter).
"""
import json
import math
import string

from floodgate.open_jev.core import softmax

LETTERS = string.ascii_uppercase


def render(rec: dict) -> str:
    state = rec["state"] if isinstance(rec["state"], str) else json.dumps(rec["state"], ensure_ascii=False, sort_keys=True)
    opts = rec["options"] if rec["kind"] != "noul" else ["No", "Yes"]
    lines = "\n".join(f"{LETTERS[i]}. {o}" for i, o in enumerate(opts))
    return (f"Context:\n{state}\n\nQuestion: {rec['question']}\n\nOptions:\n{lines}\n\n"
            f"Answer with the single letter of the correct option.")


def letter_ids(tok, n):
    ids = []
    for L in LETTERS[:n]:
        t = tok.encode(L, add_special_tokens=False)
        assert len(t) == 1, L
        ids.append(t[0])
    return ids


def score_letters(records, tok, sampler, chunk=256):
    prompts = [tok.apply_chat_template([{"role": "user", "content": render(r)}], tokenize=False, add_generation_prompt=True, enable_thinking=False) for r in records]
    out = []
    for i in range(0, len(prompts), chunk):
        for rec, g in zip(records[i:i + chunk], sampler(prompts[i:i + chunk])):
            n = 2 if rec["kind"] == "noul" else len(rec["options"])
            lp = {t.token_id: t.logprob for t in (g[0].top_logprobs[0] if g[0].top_logprobs else [])}
            floor = (min(lp.values()) - 1.0) if lp else -30.0
            out.append([lp.get(tid, floor) for tid in letter_ids(tok, n)])
    return out


def letter_datums(records, tok, eos):
    """One prompt per question; target token = the correct letter. Soft targets -> one weighted datum per letter."""
    out = []
    for rec in records:
        n = 2 if rec["kind"] == "noul" else len(rec["options"])
        ids = tok(tok.apply_chat_template([{"role": "user", "content": render(rec)}], tokenize=False, add_generation_prompt=True, enable_thinking=False), add_special_tokens=False)["input_ids"]
        for tid, w in zip(letter_ids(tok, n), rec["target"]):
            if w <= 1e-6:
                continue
            full = ids + [tid]
            out.append({"input_ids": full, "target_tokens": full[1:] + [eos], "weights": [0.0] * (len(ids) - 1) + [w, 0.0]})
    return out
