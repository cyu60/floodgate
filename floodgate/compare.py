"""Jev vs Floodgate's open Jev on River, on the same browsing states and the same noul question.

  python -m floodgate.compare [--run data/runs/<trained>.json]
"""
import argparse
import json
import time

from transformers import AutoTokenizer

import floodgate  # noqa: F401  (loads .env)
from floodgate import BASE_MODEL, client
from floodgate.jev import ask
from floodgate.open_jev.core import compile_request, softmax
from floodgate.open_jev.scorer import Renderer, score_records, session_sampler

QUESTION = "Is this page a distraction from the stated task?"
TASK = "research TypeSafe's Jev model for the hackathon"
CASES = [
    ("on-task video", {"url": "https://www.youtube.com/watch?v=jev1", "title": "An ex-OpenAI researcher just deleted language from the LLM - Fireship", "stated_task": TASK}),
    ("informative, off-task video", {"url": "https://www.youtube.com/watch?v=sat2", "title": "Why China's satellite launch failed - explained", "stated_task": TASK}),
    ("on-task docs", {"url": "https://docs.typesafe.ai/primitives/noul", "title": "Noul - TypeSafe AI docs", "stated_task": TASK}),
    ("entertainment", {"url": "https://www.youtube.com/watch?v=gta6", "title": "GTA 6: 26 Minute Gameplay Reveal", "stated_task": TASK}),
    ("same video, different task", {"url": "https://www.youtube.com/watch?v=sat2", "title": "Why China's satellite launch failed - explained", "stated_task": "write a report on space launch failures"}),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="trained run json (checkpoint + temperature); default = untrained base")
    a = ap.parse_args()
    ck, T = None, 1.0
    if a.run:
        info = json.load(open(a.run))
        ck, T = info["checkpoint"], info["temperature"]
    q = {"distraction": {"type": "noul", "instructions": QUESTION}}

    jev, jms = [], []
    for _, st in CASES:
        t0 = time.time()
        jev.append(ask(st, q)["answers"]["distraction"]["noul"])
        jms.append(int((time.time() - t0) * 1000))

    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    recs = [compile_request(st, q)[0] for _, st in CASES]
    t0 = time.time()
    with client().session(project="floodgate-compare") as s:
        logits = score_records(recs, Renderer(tok), session_sampler(s, BASE_MODEL, ck))
    ours = [softmax(l, T)[1] for l in logits]
    oms = int((time.time() - t0) * 1000)

    label = "open Jev on River" + (" (trained)" if ck else " (base)")
    print(f"{'case':30s} {'Jev':>6s} {'ms':>5s}   {label}")
    for (name, _), j, ms, o in zip(CASES, jev, jms, ours):
        print(f"{name:30s} {j:6.3f} {ms:5d}   {o:6.3f}")
    print(f"(River batch of {len(CASES)}: {oms} ms total)")


if __name__ == "__main__":
    main()
