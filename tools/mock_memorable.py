"""Tiny stand-in for Memorable's MCP endpoint (streamable HTTP, JSON-RPC) to test extension/providers/memorable.js offline.
   python3 tools/mock_memorable.py   -> http://127.0.0.1:8798/mcp   (token optional)"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
PROCEDURE = [
    "Procedure: wire a sponsor provider into the Floodgate extension (run 4 times, last one succeeded).",
    "  step 2 of 5 — check the training API reference at docs.river.ai",
    "  step 3 of 5 — copy providers/_template.js and fill in recall() and enrich()",
    "  next: register it in providers/index.js, then reload the extension and hit Test connection",
]
TOOLS = [{"name": "recall_procedure", "description": "recall the procedure for a task",
          "inputSchema": {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}}]
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        m = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        if "id" not in m:
            self.send_response(202); self.end_headers(); return
        meth = m["method"]
        if meth == "initialize": res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "mock-memorable"}}
        elif meth == "tools/list": res = {"tools": TOOLS}
        elif meth == "tools/call": res = {"content": [{"type": "text", "text": "\n".join(PROCEDURE)}]}
        else: res = {}
        body = f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': res})}\n\n".encode()
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Mcp-Session-Id", "mock-1"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
if __name__ == "__main__":
    print("mock Memorable MCP on http://127.0.0.1:8798/mcp"); HTTPServer(("127.0.0.1", 8798), H).serve_forever()
