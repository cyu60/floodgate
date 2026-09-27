"""Stand-in for hosted GBrain (gbrain.io) to test extension/providers/gbrain.js offline.

   python3 tools/mock_gbrain_mcp.py   -> MCP at http://127.0.0.1:8799/mcp

Speaks what hosted GBrain speaks: MCP over streamable HTTP (JSON-RPC, SSE replies) with the tools `recall` and
`remember` (remember requires a provenance), behind OAuth 2.1: discovery metadata, dynamic client registration,
authorization code + PKCE S256 (the authorize step approves instantly), refresh tokens. Any Bearer token is also
accepted, like a self-hosted `gbrain serve`. GET /debug shows the last Authorization header and the saved notes.
"""
import base64
import hashlib
import json
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

BASE = "http://127.0.0.1:8799"
NOTES = ["Current focus: finishing the Floodgate demo for the Own Your Intelligence hackathon (River + GBrain)."]
TOOLS = [
    {"name": "recall", "description": "retrieve saved facts", "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}, "limit": {"type": "integer"}}}},
    {"name": "remember", "description": "save one fact", "inputSchema": {"type": "object", "properties": {"fact": {"type": "string"}, "provenance": {"type": "string"}, "entity": {"type": "string"}}, "required": ["fact", "provenance"]}},
    {"name": "forget", "description": "delete a fact", "inputSchema": {"type": "object", "properties": {"id": {"type": "string"}}}},
]
CODES = {}  # code -> (code_challenge, redirect_uri)
STATE = {"last_auth": "", "clients": 0}


class H(BaseHTTPRequestHandler):
    def _json(self, code, body, headers=None):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/.well-known/oauth-protected-resource/mcp":
            return self._json(200, {"resource": f"{BASE}/mcp", "authorization_servers": [BASE], "scopes_supported": ["memory:read", "memory:full"]})
        if u.path == "/.well-known/oauth-authorization-server":
            return self._json(200, {"issuer": BASE, "authorization_endpoint": f"{BASE}/oauth/authorize", "token_endpoint": f"{BASE}/oauth/token",
                                    "registration_endpoint": f"{BASE}/oauth/register", "revocation_endpoint": f"{BASE}/oauth/revoke",
                                    "code_challenge_methods_supported": ["S256"], "grant_types_supported": ["authorization_code", "refresh_token"]})
        if u.path == "/oauth/authorize":  # approve instantly and send the code back to the extension
            q = {k: v[0] for k, v in parse_qs(u.query).items()}
            if q.get("code_challenge_method") != "S256" or not q.get("code_challenge"):
                return self._json(400, {"error": "invalid_request", "error_description": "PKCE S256 required"})
            code = secrets.token_urlsafe(12)
            CODES[code] = (q["code_challenge"], q["redirect_uri"])
            self.send_response(302)
            self.send_header("Location", f"{q['redirect_uri']}?{urlencode({'code': code, 'state': q.get('state', '')})}")
            self.end_headers()
            return
        if u.path == "/debug":
            return self._json(200, {"last_auth": STATE["last_auth"], "notes": NOTES, "clients": STATE["clients"]})
        self._json(404, {"error": "not_found"})

    def do_POST(self):
        raw = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        path = urlparse(self.path).path
        if path == "/oauth/register":
            STATE["clients"] += 1
            return self._json(201, {"client_id": f"mock-client-{STATE['clients']}", **json.loads(raw or b"{}")})
        if path == "/oauth/token":
            f = {k: v[0] for k, v in parse_qs(raw.decode()).items()}
            if f.get("grant_type") == "authorization_code":
                challenge, redirect = CODES.pop(f.get("code"), (None, None))
                digest = base64.urlsafe_b64encode(hashlib.sha256(f.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                if not challenge or digest != challenge or redirect != f.get("redirect_uri"):
                    return self._json(400, {"error": "invalid_grant", "error_description": "bad code, verifier or redirect_uri"})
            elif f.get("grant_type") != "refresh_token" or not f.get("refresh_token"):
                return self._json(400, {"error": "unsupported_grant_type"})
            return self._json(200, {"access_token": f"mock-access-{secrets.token_hex(4)}", "refresh_token": "mock-refresh", "token_type": "Bearer",
                                    "expires_in": 3600, "scope": "memory:read memory:full"})
        if path == "/oauth/revoke":
            return self._json(200, {})
        # MCP
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return self._json(401, {"error": "invalid_token"}, {"WWW-Authenticate": f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource/mcp"'})
        STATE["last_auth"] = auth
        m = json.loads(raw)
        if "id" not in m:
            self.send_response(202)
            self.end_headers()
            return
        meth, out = m["method"], {"jsonrpc": "2.0", "id": m["id"]}
        if meth == "initialize":
            out["result"] = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}}, "serverInfo": {"name": "mock-gbrain"}}
        elif meth == "tools/list":
            out["result"] = {"tools": TOOLS}
        elif meth == "tools/call":
            name, a = m["params"]["name"], m["params"].get("arguments", {})
            if name == "remember":
                if not a.get("fact") or not a.get("provenance"):
                    out["error"] = {"code": -32602, "message": "remember requires fact and provenance"}
                else:
                    NOTES.append(a["fact"])
                    out["result"] = {"content": [{"type": "text", "text": "remembered"}]}
            else:
                out["result"] = {"content": [{"type": "text", "text": "\n".join(NOTES[-5:])}]}
        else:
            out["result"] = {}
        body = f"event: message\ndata: {json.dumps(out)}\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Mcp-Session-Id", "mock-1")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    print(f"mock GBrain (MCP + OAuth 2.1) on {BASE}/mcp")
    HTTPServer(("127.0.0.1", 8799), H).serve_forever()
