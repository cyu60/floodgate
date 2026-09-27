"""Habitect Gate server: the Chrome extension posts {url, title} per navigation; we answer
{"p": P(distraction), "lock": bool} from the River noul probe (base model or a trained checkpoint).

  python -m habitect_gate.gate_server --task "prep River dataset" [--checkpoint river://…] [--threshold 0.7]

Stdlib only. Keeps one River session open; decisions and overrides are appended to
data/gate_log.jsonl so every override becomes a training row.
"""
import argparse
import json
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from transformers import AutoTokenizer

from habitect_gate import BASE_MODEL, client
from habitect_gate.open_jev.core import compile_request, softmax
from habitect_gate.open_jev.scorer import Renderer, score_records, session_sampler

LOG = Path(__file__).resolve().parent.parent / "data" / "gate_log.jsonl"
QUESTION = "Is this page a distraction from the stated task?"
STATE = {"task": "deep work", "threshold": 0.7, "checkpoint": None, "temperature": 1.0}
CACHE: dict[str, tuple[float, float]] = {}
LOCK = threading.Lock()


def decide(session, tok, url: str, title: str) -> dict:
    key = url.split("#")[0]
    now = time.time()
    if key in CACHE and now - CACHE[key][1] < 600:
        p = CACHE[key][0]
    else:
        state = {"url": url[:300], "title": title[:160], "time": f"{datetime.now():%H:%M %A}", "stated_task": STATE["task"]}
        recs = compile_request(state, {"distraction": {"type": "noul", "instructions": QUESTION}})
        with LOCK:
            logits = score_records(recs, Renderer(tok), session_sampler(session, BASE_MODEL, STATE["checkpoint"]))
        p = softmax(logits[0], STATE["temperature"])[1]
        CACHE[key] = (p, now)
    return {"p": round(p, 3), "lock": p >= STATE["threshold"], "task": STATE["task"]}


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
                CACHE.clear()
                return self._json(200, {"task": STATE["task"]})
            if self.path == "/override":  # user says the decision was wrong -> training row
                row = {"ts": datetime.now().isoformat(), "kind": "override", **body}
                LOG.parent.mkdir(exist_ok=True)
                LOG.open("a").write(json.dumps(row) + "\n")
                return self._json(200, {"logged": True})
            t0 = time.time()
            d = decide(session, tok, body.get("url", ""), body.get("title", ""))
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
    ap.add_argument("--run", help="data/runs/*.json from open_jev.train: uses its checkpoint + temperature")
    a = ap.parse_args()
    if a.run:
        info = json.load(open(a.run))
        a.checkpoint, a.temperature = info["checkpoint"], info["temperature"]
    STATE.update(task=a.task, threshold=a.threshold, checkpoint=a.checkpoint, temperature=a.temperature)
    tok = AutoTokenizer.from_pretrained(BASE_MODEL)
    with client().session(project="habitect-gate") as session:
        print(f"habitect gate on http://127.0.0.1:{a.port}  task={a.task!r} threshold={a.threshold} ckpt={a.checkpoint}")
        HTTPServer(("127.0.0.1", a.port), make_handler(session, tok)).serve_forever()


if __name__ == "__main__":
    main()
