"""Tiny stand-in for GBrain's MCP endpoint (streamable HTTP, JSON-RPC) to test extension/providers/gbrain.js offline.
   python3 tools/mock_gbrain_mcp.py   -> http://127.0.0.1:8799/mcp   (token: anything non-empty)"""
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
NOTES = ["Current focus: finishing the Floodgate demo for the Own Your Intelligence hackathon (River + GBrain)."]
TOOLS = [{"name": "search_memory", "description": "search", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}},
         {"name": "remember", "description": "write a note", "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}}]
class H(BaseHTTPRequestHandler):
    def do_POST(self):
        if not self.headers.get("Authorization", "").startswith("Bearer "):
            self.send_response(401); self.end_headers(); return
        m = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        if "id" not in m:
            self.send_response(202); self.end_headers(); return
        meth = m["method"]
        if meth == "initialize": res = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "mock-gbrain"}}
        elif meth == "tools/list": res = {"tools": TOOLS}
        elif meth == "tools/call":
            a = m["params"]["arguments"]
            if m["params"]["name"] == "remember": NOTES.append(a["text"]); res = {"content": [{"type": "text", "text": "remembered"}]}
            else: res = {"content": [{"type": "text", "text": "\n".join(NOTES[-3:])}]}
        else: res = {}
        body = f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'id': m['id'], 'result': res})}\n\n".encode()
        self.send_response(200); self.send_header("Content-Type", "text/event-stream"); self.send_header("Mcp-Session-Id", "mock-1"); self.end_headers(); self.wfile.write(body)
    def log_message(self, *a): pass
if __name__ == "__main__":
    print("mock GBrain MCP on http://127.0.0.1:8799/mcp"); HTTPServer(("127.0.0.1", 8799), H).serve_forever()
