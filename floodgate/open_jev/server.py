"""Jev-compatible HTTP endpoint backed by River: POST /v1/systemone with {state, questions}.
Same body and response shape as api.typesafe.ai/v1/systemone, so the MentorMates proxy, the Jev
SDKs' request format, and the Floodgate can all point at it.

  python -m floodgate.open_jev.server --checkpoint river://... --temperature 1.7
  python -m floodgate.open_jev.server            # untrained base = Open-Jev at step 0
  curl -s localhost:8791/v1/systemone -d '{"state":"...","questions":{"q":{"type":"noul","instructions":"..."}}}'
"""
import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from transformers import AutoTokenizer

from floodgate import BASE_MODEL, client
from floodgate.open_jev.core import compile_request, format_response, softmax
from floodgate.open_jev.scorer import Renderer, score_records, session_sampler


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--checkpoint")
    ap.add_argument("--temperature", type=float, default=1.0)
    ap.add_argument("--run", help="data/runs/*.json from train.py: reads checkpoint + temperature")
    ap.add_argument("--port", type=int, default=8791)
    a = ap.parse_args()
    if a.run:
        info = json.load(open(a.run))
        a.checkpoint, a.temperature = info["checkpoint"], info["temperature"]
    tok = AutoTokenizer.from_pretrained(a.base)
    r = Renderer(tok)
    model_name = "open-jev-river" + ("" if a.checkpoint else "-base")

    with client().session(project="open-jev-server") as session:
        sampler = session_sampler(session, a.base, a.checkpoint)

        class H(BaseHTTPRequestHandler):
            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_OPTIONS(self):
                self._send(204, {})

            def do_GET(self):
                self._send(200, {"models": [{"name": model_name, "checkpoint": a.checkpoint, "temperature": a.temperature}]})

            def do_POST(self):
                if self.path.rstrip("/") != "/v1/systemone":
                    return self._send(404, {"detail": "Not Found"})
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                    t0 = time.time()
                    recs = compile_request(body.get("state"), body.get("questions"))
                    logits = score_records(recs, r, sampler)
                    out = format_response(recs, [softmax(l, a.temperature) for l in logits])
                    prompts = sum(1 if x["kind"] == "noul" else len(x["options"]) for x in recs)
                    out.update(model=model_name, usage={"candidate_prompts": prompts, "latency_ms": int((time.time() - t0) * 1000)})
                    self._send(200, out)
                except ValueError as e:
                    self._send(422, {"detail": str(e)})

            def log_message(self, *args):
                pass

        print(f"open-jev on River: http://127.0.0.1:{a.port}/v1/systemone  model={model_name} T={a.temperature}")
        ThreadingHTTPServer(("127.0.0.1", a.port), H).serve_forever()


if __name__ == "__main__":
    main()
