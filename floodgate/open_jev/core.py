"""System One request compilation, candidate prompts, typed responses and calibration.

Ported from Open-Jev (https://github.com/Zefan-Cai/Open-Jev, MIT, jev/api.py + jev/metrics.py)
so requests, prompts and responses are byte-compatible with Open-Jev and Jev's /v1/systemone.
Only the model behind it changes: River instead of a local GPU.
"""
import json
import math
from collections.abc import Mapping, Sequence


def _render(value) -> str:
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False)


def _description(value, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, (str, dict, list)):
        raise ValueError("instructions and descriptions must be text, an object, or an array")
    json.dumps(value, allow_nan=False)
    return _render(value)


def compile_request(state, questions: Mapping) -> list[dict]:
    """Jev request body -> one isolated record per question (no targets)."""
    if not isinstance(state, (str, dict, list)):
        raise ValueError("state must be text, a JSON object, or an array")
    state_copy = json.loads(json.dumps(state, ensure_ascii=False, allow_nan=False))
    if not isinstance(questions, Mapping) or not questions:
        raise ValueError("questions must be a nonempty mapping")
    records = []
    for qid, d in questions.items():
        kind = d.get("type")
        if kind not in ("choice", "score", "noul"):
            raise ValueError("question type must be choice, score, or noul")
        rec = {"id": qid, "state": state_copy, "kind": kind, "question": _description(d.get("instructions"))}
        crit = d.get("criteria")
        if kind == "choice":
            if not isinstance(crit, Mapping) or not 1 <= len(crit) <= 255:
                raise ValueError("Choice requires between 1 and 255 candidates")
            descs = [_description(v, optional=True) for v in crit.values()]
            rec["answer_keys"] = list(crit)
            rec["options"] = [k if s is None else f"{k}: {s}" for k, s in zip(crit, descs)]
        elif kind == "score":
            if not isinstance(crit, list) or not 2 <= len(crit) <= 10:
                raise ValueError("Score requires an array of 2 to 10 descriptive levels")
            rec["options"] = [_description(level) for level in crit]
            rec["answer_keys"] = [str(i) for i in range(len(crit))]
            rec["legend"] = dict(zip(rec["answer_keys"], crit))
        else:
            if crit is not None:
                if not isinstance(crit, Mapping) or set(crit) != {"true", "false"}:
                    raise ValueError("Noul criteria must contain true and false descriptions")
                rec["question"] += f"\nYes means: {_description(crit['true'])}\nNo means: {_description(crit['false'])}"
            rec["options"] = ["no", "yes"]
            rec["answer_keys"] = ["false", "true"]
        records.append(rec)
    return records


def candidate_prompts(record: dict) -> list[str]:
    """Open-Jev's exact candidate prompt text. Noul = 1 prompt; choice/score = 1 per option."""
    prefix = f"Context:\n{_render(record['state'])}\n\nQuestion: {_render(record['question'])}\n"
    if record["kind"] == "noul":
        return [prefix + "Is the answer to this question yes? Answer Yes or No."]
    return [prefix + f"Proposed answer: {_render(o)}\nIs this proposed answer correct? Answer Yes or No." for o in record["options"]]


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x)) if x >= 0 else math.exp(x) / (1 + math.exp(x))


def softmax(logits: Sequence[float], temperature: float = 1.0) -> list[float]:
    m = max(logits)
    w = [math.exp((v - m) / temperature) for v in logits]
    s = sum(w)
    return [v / s for v in w]


def record_logits(kind: str, scores: Sequence[float]) -> list[float]:
    """Per-candidate scalars -> class logits. Noul is [0, s] so P(yes) = sigmoid(s), as in Open-Jev."""
    return [0.0, scores[0]] if kind == "noul" else list(scores)


def choice_confidence(probs):
    if len(probs) == 1:
        return 1.0
    u = 1 / len(probs)
    return (max(probs) - u) / (1 - u)


def score_confidence(probs):
    n = len(probs)
    if n == 1:
        return 1.0
    mode = max(range(n), key=probs.__getitem__)
    dist = sum(p * abs(i - mode) for i, p in enumerate(probs))
    c = (n - 1) / 2
    return max(0.0, 1 - dist / (sum(abs(i - c) for i in range(n)) / n))


def format_response(records, probabilities) -> dict:
    """Typed answers in Jev's response format."""
    answers = {}
    for rec, probs in zip(records, probabilities):
        keys, kind = rec["answer_keys"], rec["kind"]
        if kind == "noul":
            answers[rec["id"]] = {"type": kind, "noul": probs[1]}
        elif kind == "choice":
            i = max(range(len(probs)), key=probs.__getitem__)
            answers[rec["id"]] = {"type": kind, "choice": keys[i], "probabilities": dict(zip(keys, probs)), "confidence": choice_confidence(probs)}
        else:
            answers[rec["id"]] = {"type": kind, "score": sum(i * p for i, p in enumerate(probs)), "probabilities": dict(zip(keys, probs)),
                                  "confidence": score_confidence(probs), "legend": rec["legend"]}
    return {"answers": answers}


def fit_temperature(logits, targets, lo=0.05, hi=20.0, grid=41) -> float:
    """One temperature by calibration-set cross-entropy (log-spaced grid; Open-Jev also refines)."""
    def loss(t):
        tot = 0.0
        for row, tgt in zip(logits, targets):
            p = softmax(row, t)
            tot -= sum(q * math.log(max(pi, 1e-12)) for q, pi in zip(tgt, p))
        return tot / len(logits)
    pts = [math.exp(math.log(lo) + i * (math.log(hi) - math.log(lo)) / (grid - 1)) for i in range(grid)] + [1.0]
    return min(pts, key=loss)


def metrics(logits, targets, temperature: float = 1.0) -> dict:
    """Hard-label accuracy, NLL and Brier over rows (targets are distributions)."""
    n = acc = nll = brier = 0.0
    hard = 0
    for row, tgt in zip(logits, targets):
        p = softmax(row, temperature)
        nll -= sum(q * math.log(max(pi, 1e-12)) for q, pi in zip(tgt, p))
        brier += sum((pi - q) ** 2 for pi, q in zip(p, tgt))
        n += 1
        if max(tgt) == 1.0:
            hard += 1
            acc += p.index(max(p)) == tgt.index(1.0)
    return {"n": int(n), "accuracy": acc / hard if hard else None, "nll": nll / n, "brier": brier / n}
