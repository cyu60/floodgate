"""Noul-style probe on River: P(yes) from the Yes/No logit gap at the answer position.

This is the Open-Jev trick without a separate head. Open-Jev initialises its scalar
decision head as lm_head[Yes] - lm_head[No] over the last hidden state (jev/model.py),
i.e. the Yes/No logit difference. River exposes that directly: sample max_tokens=1
with logprobs=K and read the two tokens. Verified 2026-09-23 on the untrained base:
manga page at 23:40 -> 0.915 distraction, River docs at 10:15 -> 0.294, batch of 3 in 5.6 s.

  python -m habitect_gate.jev_probe                       # runs the three demo cases
  python -m habitect_gate.jev_probe --checkpoint river://…  # same, through a trained LoRA
"""
import argparse
import math

from transformers import AutoTokenizer

from habitect_gate import BASE_MODEL, client

SYSTEM = "You are a decision model. Answer with exactly one word: Yes or No."


def render(tok, state: str, question: str) -> str:
    msgs = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"State:\n{state}\n\nQuestion: {question}\nAnswer (Yes/No):"},
    ]
    return tok.apply_chat_template(msgs, tokenize=False, add_generation_prompt=True, enable_thinking=False)


def noul(session, tok, cases: list[tuple[str, str]], base_model: str = BASE_MODEL, checkpoint=None, temperature: float = 1.0) -> list[dict]:
    """cases = [(state, question)]. Returns P(yes) per case from the Yes/No logits, with an
    optional calibration temperature applied to the logit gap (fit on held-out data)."""
    prompts = [render(tok, s, q) for s, q in cases]
    kw = dict(base_model=base_model, max_tokens=1, temperature=0.0, logprobs=10)
    if checkpoint:
        kw["checkpoint"] = checkpoint
    out = session.sample(prompts, **kw)
    yes_ids = {tok.encode(t, add_special_tokens=False)[0] for t in ("Yes", " Yes")}
    no_ids = {tok.encode(t, add_special_tokens=False)[0] for t in ("No", " No")}
    results = []
    for grp in out:
        smp = grp[0]
        tops = smp.top_logprobs[0] if smp.top_logprobs else []
        ly = max((t.logprob for t in tops if t.token_id in yes_ids), default=-30.0)
        ln = max((t.logprob for t in tops if t.token_id in no_ids), default=-30.0)
        gap = (ly - ln) / temperature
        p = 1.0 / (1.0 + math.exp(-gap))
        results.append({"p_yes": p, "logit_gap": ly - ln, "greedy": smp.text.strip()})
    return results


DEMO = [
    ("URL: https://asurascans.com/series/solo-leveling-ch-201 Title: Solo Leveling Chapter 201. Time: 23:40 Tuesday. Stated task: finish the hackathon demo.", "Is this page a distraction from the stated task?"),
    ("URL: https://docs.river.ai/python-api Title: River Python API reference. Time: 10:15 Wednesday. Stated task: prep River dataset script.", "Is this page a distraction from the stated task?"),
    ("URL: https://www.youtube.com/watch?v=abc Title: Fireship - An ex-OpenAI researcher just deleted language from the LLM. Time: 14:05 Wednesday. Stated task: research Jev for hackathon.", "Is this page a distraction from the stated task?"),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--checkpoint")
    ap.add_argument("--temperature", type=float, default=1.0)
    a = ap.parse_args()
    tok = AutoTokenizer.from_pretrained(a.base)
    with client().session() as s:
        for (state, q), r in zip(DEMO, noul(s, tok, DEMO, a.base, a.checkpoint, a.temperature)):
            print(f"p_yes={r['p_yes']:.3f}  gap={r['logit_gap']:+.2f}  greedy={r['greedy']:<4} | {state[:70]}…")


if __name__ == "__main__":
    main()
