"""Floodgate server: the Chrome extension posts {url, title} per navigation; we answer
{"p": P(distraction), "lock": bool} from the River noul probe (base model or a trained checkpoint).

  python -m floodgate.gate_server --task "prep River dataset" [--checkpoint river://…] [--threshold 0.7]

Stdlib only. Keeps one River session open; decisions and overrides are appended to
data/gate_log.jsonl so every override becomes a training row.

The Chrome extension also sends `task` and `about_me` with each page (so several tabs or people can use
different tasks), and can hot-swap the model from a shared model card via POST /model.
"""
import argparse
import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from transformers import AutoTokenizer

from floodgate import BASE_MODEL, client
from floodgate.open_jev.core import compile_request, softmax
from floodgate.open_jev.letters import score_letters
from floodgate.open_jev.scorer import Renderer, score_records, session_sampler

LOG = Path(__file__).resolve().parent.parent / "data" / "gate_log.jsonl"
QUESTION = "Is this page a distraction from the stated task?"
STATE = {"task": "deep work", "threshold": 0.7, "checkpoint": None, "temperature": 1.0, "profile": "", "base_model": BASE_MODEL, "use_about_me": False, "letters": False}
CACHE: dict[tuple, tuple[float, float]] = {}
LOCK = threading.Lock()


def decide(session, tok, url: str, title: str, task: str | None = None, about_me: str | None = None) -> dict:
    task = task or STATE["task"]
    about_me = STATE["profile"] if about_me is None else about_me
    key = (task, about_me, url.split("#")[0])
    now = time.time()
    if key in CACHE and now - CACHE[key][1] < 600:
        p = CACHE[key][0]
    else:
        # Same text line the training rows use (prep_gate_dataset / label tool / train_personal), so a model
        # fine-tuned on personal rows sees at serve time exactly the format it was trained on.
        state = f"URL: {url[:200]} Title: {title[:120]}. Time: {datetime.now():%H:%M %A}. Stated task: {task}."
        if about_me and STATE.get("use_about_me"):
            state += f" About me: {about_me[:300]}."
        recs = compile_request(state, {"distraction": {"type": "noul", "instructions": QUESTION}})
        with LOCK:
            sampler = session_sampler(session, BASE_MODEL, STATE["checkpoint"])
            # letter-readout checkpoints (train_letters.py) are asked "A. No / B. Yes", others the per-candidate Yes/No prompt
            logits = score_letters(recs, tok, sampler) if STATE["letters"] else score_records(recs, Renderer(tok), sampler)
        p = softmax(logits[0], STATE["temperature"])[1]
        CACHE[key] = (p, now)
    return {"p": round(p, 3), "lock": p >= STATE["threshold"], "task": task}


def make_handler(session, tok):
    class H(BaseHTTPRequestHandler):
        def _json(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_OPTIONS(self):
            self._json(204, {})

        def do_GET(self):
            self._json(200, {"ok": True, **STATE})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
            if self.path == "/task":
                STATE["task"] = body.get("task", STATE["task"])
                STATE["profile"] = body.get("profile", STATE["profile"]) or ""
                CACHE.clear()
                return self._json(200, {"task": STATE["task"]})
            if self.path == "/model":  # load a shared model card's checkpoint without restarting
                STATE["checkpoint"] = body.get("checkpoint") or None
                STATE["temperature"] = float(body.get("temperature") or 1.0)
                STATE["letters"] = body.get("method") == "semif-letters"
                CACHE.clear()
                return self._json(200, {"checkpoint": STATE["checkpoint"], "temperature": STATE["temperature"]})
            if self.path == "/override":  # user says the decision was wrong -> training row
                row = {"ts": datetime.now().isoformat(), "kind": "override", **body}
                LOG.parent.mkdir(exist_ok=True)
                LOG.open("a").write(json.dumps(row) + "\n")
                return self._json(200, {"logged": True})
            t0 = time.time()
            d = decide(session, tok, body.get("url", ""), body.get("title", ""), body.get("task"), body.get("about_me"))
            d["ms"] = int((time.time() - t0) * 1000)
            LOG.parent.mkdir(exist_ok=True)
            LOG.open("a").write(json.dumps({"ts": datetime.now().isoformat(), "kind": "decision", "url": body.get("url"), "title": body.get("title"), **d}) + "\n")
            self._json(200, d)

        def log_message(self, *a):
            pass

    return H


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default=STATE["task"])
    ap.add_argument("--threshold", type=float, default=STATE["threshold"])
    ap.add_argument("--checkpoint")
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--run", help="a model card (models/*.json) or data/runs/*.json: uses its checkpoint + temperature")
    ap.add_argument("--use-about-me", action="store_true", help="append the extension's 'about me' to the state (off by default: personal models were trained without it)")
    a = ap.parse_args()
    letters = False
    if a.run:
        info = json.load(open(a.run))
        a.checkpoint, a.temperature = info["checkpoint"], info["temperature"]
        letters = info.get("method") == "semif-letters"
    STATE.update(task=a.task, threshold=a.threshold, checkpoint=a.checkpoint, temperature=a.temperature, use_about_me=a.use_about_me, letters=letters)
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    with client().session(project="floodgate") as session:
        print(f"Floodgate on http://127.0.0.1:{a.port}  task={a.task!r} threshold={a.threshold} ckpt={a.checkpoint}")
        HTTPServer(("127.0.0.1", a.port), make_handler(session, tok)).serve_forever()


if __name__ == "__main__":
    main()
