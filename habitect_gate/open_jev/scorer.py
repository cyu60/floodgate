"""Score candidates on River. scalar = logprob(Yes) - logprob(No) at the first answer token.

That difference equals logit(Yes) - logit(No), which is exactly how Open-Jev initialises its
decision head (lm_head[Yes] - lm_head[No] on the last hidden state). So the untrained base on
River is Open-Jev at step 0, and LoRA training (with train_unembed) moves the same quantity.
"""
from habitect_gate.open_jev.core import candidate_prompts, record_logits

TOP_K = 20


class Renderer:
    def __init__(self, tok):
        self.tok = tok
        self.yes = tok.encode("Yes", add_special_tokens=False)
        self.no = tok.encode("No", add_special_tokens=False)
        assert len(self.yes) == 1 and len(self.no) == 1, "Yes/No must be single tokens"
        self.yes, self.no = self.yes[0], self.no[0]

    def chat(self, prompt: str) -> str:
        return self.tok.apply_chat_template([{"role": "user", "content": prompt}], tokenize=False, add_generation_prompt=True, enable_thinking=False)

    def prompt_ids(self, prompt: str) -> list[int]:
        return self.tok(self.chat(prompt), add_special_tokens=False)["input_ids"]


def _gap(sample, r: Renderer) -> float:
    tops = sample.top_logprobs[0] if sample.top_logprobs else []
    lp = {t.token_id: t.logprob for t in tops}
    floor = min(lp.values()) - 1.0 if lp else -30.0  # token outside top-K: bounded by the K-th logprob
    return lp.get(r.yes, floor) - lp.get(r.no, floor)


def score_records(records, r: Renderer, sampler, chunk: int = 256) -> list[list[float]]:
    """records -> per-record class logits. `sampler(list_of_prompts)` returns list[list[Sample]]."""
    flat, counts = [], []
    for rec in records:
        ps = candidate_prompts(rec)
        counts.append(len(ps))
        flat += [r.chat(p) for p in ps]
    gaps = []
    for i in range(0, len(flat), chunk):
        gaps += [_gap(g[0], r) for g in sampler(flat[i : i + chunk])]
    out, k = [], 0
    for rec, c in zip(records, counts):
        out.append(record_logits(rec["kind"], gaps[k : k + c]))
        k += c
    return out


def session_sampler(session, base_model: str, checkpoint=None):
    kw = dict(base_model=base_model, max_tokens=1, temperature=0.0, logprobs=TOP_K)
    if checkpoint:
        kw["checkpoint"] = checkpoint
    return lambda prompts: session.sample(prompts, **kw)


def model_sampler(model):
    return lambda prompts: model.sample(prompts, max_tokens=1, temperature=0.0, logprobs=TOP_K)
