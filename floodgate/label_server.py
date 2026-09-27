"""Serve tools/label.html and persist labels straight into data/gate_labels.jsonl (no download step).

  python -m floodgate.label_server            # http://127.0.0.1:8765
  GET  /            -> tools/label.html
  GET  /queue       -> data/label_queue.json
  GET  /labels      -> data/gate_labels.jsonl as a JSON array (resume)
  POST /labels      -> body = JSON array of Open-Jev rows; rewrites data/gate_labels.jsonl
Stdlib only.
"""
import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = ROOT / "tools" / "label.html"
QUEUE = ROOT / "data" / "label_queue.json"
LABELS = ROOT / "data" / "gate_labels.jsonl"


class H(BaseHTTPRequestHandler):
    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
        if self.path == "/queue":
            return self._send(200, QUEUE.read_bytes()) if QUEUE.exists() else self._send(404, b'{"error":"run python -m floodgate.label_queue first"}')
        if self.path == "/labels":
            rows = [json.loads(l) for l in LABELS.read_text().splitlines() if l.strip()] if LABELS.exists() else []
            return self._send(200, json.dumps(rows, ensure_ascii=False).encode())
        self._send(404, b"{}")

    def do_POST(self):
        if self.path != "/labels":
            return self._send(404, b"{}")
        n = int(self.headers.get("Content-Length", 0))
        rows = json.loads(self.rfile.read(n) or b"[]")
        LABELS.parent.mkdir(exist_ok=True)
        tmp = LABELS.with_suffix(".tmp")
        with open(tmp, "w") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        tmp.replace(LABELS)
        self._send(200, json.dumps({"saved": len(rows)}).encode())

    def log_message(self, fmt, *args):  # quiet
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    print(f"labeling UI: http://127.0.0.1:{a.port}   (labels -> {LABELS.relative_to(ROOT)})")
    HTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
