"""Mock Floodgate gate: the same HTTP contract as floodgate/gate_server.py, with no River, no key, no venv.

For building and demoing the Chrome extension before the River model is up:

  python3 tools/mock_gate.py                    # http://127.0.0.1:8790, ~1.5 s per decision like River
  python3 tools/mock_gate.py --latency 0        # instant

Then Dashboard -> Model -> "River open Jev (gate server)". Decisions are crude keyword rules; overrides are
logged to data/gate_log.jsonl exactly like the real server, so the labelling loop can be tested end to end.
"""
import argparse
import json
import re
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

LOG = Path(__file__).resolve().parent.parent / "data" / "gate_log.jsonl"
FUN = {"youtube.com", "reddit.com", "x.com", "twitter.com", "instagram.com", "tiktok.com", "netflix.com", "twitch.tv", "9gag.com"}
FUN_WORDS = re.compile(r"\b(gameplay|funny|memes?|compilation|trailer|speedrun|minecraft|fortnite|gta|reaction|highlights|prank|vlog|live ?stream)\b", re.I)
STOP = set("a an the and or of for to in on at by with from is are my your this that it be do i we you".split())
STATE = {"ok": True, "mock": True, "task": "deep work", "profile": "", "threshold": 0.7, "checkpoint": None, "temperature": 1.0, "base_model": "mock"}
ARGS = argparse.Namespace(latency=1.5, log=LOG)


def words(text: str) -> set[str]:
    return {w.rstrip("s") for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in STOP and len(w) > 2}


def score(url: str, title: str, task: str) -> float:
    dom = urlparse(url).netloc.lower().removeprefix("www.")
    overlap = len(words(task) & words(f"{title} {url}"))
    p = 0.8 if any(dom == d or dom.endswith("." + d) for d in FUN) else 0.5
    p += 0.35 if FUN_WORDS.search(title or "") else 0
    return round(max(0.03, min(0.97, p - 0.3 * overlap)), 3)


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
        self._json(200, STATE)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0) or 0)) or b"{}")
        ARGS.log.parent.mkdir(parents=True, exist_ok=True)
        if self.path == "/task":
            STATE["task"] = body.get("task", STATE["task"])
            STATE["profile"] = body.get("profile", STATE["profile"]) or ""
            return self._json(200, {"task": STATE["task"]})
        if self.path == "/model":
            STATE["checkpoint"], STATE["temperature"] = body.get("checkpoint"), float(body.get("temperature") or 1.0)
            return self._json(200, {"checkpoint": STATE["checkpoint"], "temperature": STATE["temperature"]})
        if self.path == "/override":
            with ARGS.log.open("a") as f:
                f.write(json.dumps({"ts": datetime.now().isoformat(), "kind": "override", "mock": True, **body}) + "\n")
            return self._json(200, {"logged": True})
        t0 = time.time()
        time.sleep(ARGS.latency)
        task = body.get("task") or STATE["task"]
        p = score(body.get("url", ""), body.get("title", ""), task)
        d = {"p": p, "lock": p >= STATE["threshold"], "task": task, "model": "mock gate", "ms": int((time.time() - t0) * 1000)}
        print(f"{p:.2f}  {body.get('title', '')[:70]!r}  task={task!r}")
        self._json(200, d)

    def log_message(self, *a):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8790)
    ap.add_argument("--latency", type=float, default=1.5, help="seconds per decision (River's shared pool is ~1-6 s)")
    ap.add_argument("--log", type=Path, default=LOG, help="where overrides are appended (default data/gate_log.jsonl)")
    ap.parse_args(namespace=ARGS)
    print(f"mock Floodgate gate on http://127.0.0.1:{ARGS.port}  (latency {ARGS.latency}s, no River)")
    ThreadingHTTPServer(("127.0.0.1", ARGS.port), H).serve_forever()


if __name__ == "__main__":
    main()
