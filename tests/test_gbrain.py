"""Exercise the actual subprocess transport without GBrain or credentials."""
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from floodgate.gbrain import GBrainClient, GBrainError


FAKE_SERVER = r'''
import json, os, sys, time
initialized = False
def send(value):
    print(json.dumps(value), flush=True)
def reply(request, value):
    send({"jsonrpc": "2.0", "id": request["id"], "result": value})
for line in sys.stdin:
    request = json.loads(line)
    method = request.get("method")
    if method == "initialize":
        reply(request, {"protocolVersion": request["params"]["protocolVersion"],
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "fake", "version": "1"}})
    elif method == "notifications/initialized":
        initialized = True
    elif method == "tools/call":
        assert initialized
        tool = request["params"]["name"]
        if tool == "slow":
            time.sleep(5)
        if tool == "malformed":
            print("not JSON", flush=True)
            continue
        if tool == "partial":
            sys.stdout.write('{"jsonrpc":'); sys.stdout.flush()
            time.sleep(5)
        if tool == "exit":
            sys.exit(2)
        if tool == "wrong_id":
            send({"jsonrpc": "2.0", "id": 999999, "result": {}})
            continue
        if tool == "rpc_error":
            send({"jsonrpc": "2.0", "id": request["id"],
                  "error": {"code": -32602, "message": "invalid arguments"}})
            continue
        if tool == "tool_error":
            reply(request, {"isError": True, "content": [{"type": "text", "text":
                json.dumps({"error": {"code": "revision_conflict", "detail": "Read again"}})}]})
            continue
        if tool == "ping":
            send({"jsonrpc": "2.0", "id": "ping-1", "method": "ping"})
            answer = json.loads(sys.stdin.readline())
            assert answer["id"] == "ping-1" and answer["result"] == {}
            send({"jsonrpc": "2.0", "method": "notifications/message", "params": {}})
        if tool == "unsupported":
            send({"jsonrpc": "2.0", "id": "sample-1", "method": "sampling/createMessage"})
            answer = json.loads(sys.stdin.readline())
            assert answer["error"]["code"] == -32601
        if tool == "stderr":
            sys.stderr.write("x" * 1000000); sys.stderr.flush()
        if tool == "plain":
            reply(request, {"content": [{"type": "text", "text": "plain text"}]})
            continue
        if tool == "array":
            reply(request, {"content": [{"type": "text", "text": "[1, 2, 3]"}]})
            continue
        if tool in ("notice", "empty_notice", "error_notice", "ambiguous"):
            data = [] if tool == "empty_notice" else {"slug": "floodgate/owner"}
            if tool == "error_notice":
                data = {"error": "page_not_found", "message": "Page missing"}
            second = '{"different":"data"}' if tool == "ambiguous" else "Backup coverage notice: no full backup yet."
            reply(request, {"isError": tool == "error_notice", "content": [
                {"type": "text", "text": json.dumps(data)},
                {"type": "text", "text": second},
            ]})
            continue
        payload = {"pid": os.getpid(), "arguments": request["params"]["arguments"],
                   "env": dict(os.environ), "cwd": os.getcwd(), "argv": sys.argv[1:]}
        if tool == "structured":
            reply(request, {"structuredContent": payload,
                            "content": [{"type": "text", "text": "ignored"}]})
        else:
            reply(request, {"content": [{"type": "text", "text": json.dumps(payload)}]})
'''


class GBrainClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="floodgate-mcp-test-")
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        # A literal executable path, including characters a shell would treat
        # specially, verifies there is no shell evaluation in startup.
        self.command = root / "fake gbrain ; literal"
        self.command.write_text(f"#!{sys.executable}\n" + FAKE_SERVER)
        self.command.chmod(0o700)
        self.home = root / "brain home"
        self.home.mkdir()
        self.client = GBrainClient(self.home, str(self.command), timeout=1)
        self.addCleanup(self.client.close)

    def test_handshake_persistence_environment_and_shutdown(self):
        poisoned = {
            "GBRAIN_HOME": "/wrong", "GBRAIN_SOURCE": "wrong-source",
            "GBRAIN_BRAIN_ID": "wrong-brain", "DATABASE_URL": "wrong-db",
            "GBRAIN_DATABASE_URL": "wrong-db", "OPENAI_API_KEY": "secret",
            "ANTHROPIC_API_KEY": "secret", "RIVER_API_KEY": "secret",
            "BUN_OPTIONS": "--preload=/wrong", "PGPASSWORD": "secret",
        }
        with patch.dict(os.environ, poisoned):
            with self.client as client:
                first = client.call("echo", {"text": "literal\nUnicode: café"})
                second = client.call("structured", {"n": 2})
                self.assertEqual(first["pid"], second["pid"])
                self.assertEqual(first["argv"], ["serve", "--surface", "full"])
                self.assertEqual(first["cwd"], str(self.home.resolve()))
                self.assertEqual(first["env"]["GBRAIN_HOME"], str(self.home.resolve()))
                self.assertEqual(first["arguments"]["text"], "literal\nUnicode: café")
                for key in poisoned.keys() - {"GBRAIN_HOME"}:
                    self.assertNotIn(key, first["env"])
                process = client._process
        self.assertIsNotNone(process.poll())
        self.assertIsNone(self.client._process)
        self.client.close()  # Idempotent.

    def test_errors_preserve_payload_and_healthy_connection(self):
        pid = self.client.call("echo", {})["pid"]
        with self.assertRaises(GBrainError) as caught:
            self.client.call("tool_error", {})
        self.assertEqual(caught.exception.code, "revision_conflict")
        self.assertEqual(caught.exception.payload["error"]["detail"], "Read again")
        with self.assertRaises(GBrainError) as caught:
            self.client.call("rpc_error", {})
        self.assertEqual(caught.exception.code, -32602)
        self.assertEqual(self.client.call("echo", {})["pid"], pid)

    def test_ping_notifications_unimplemented_request_and_stderr(self):
        for tool in ("ping", "unsupported", "stderr"):
            self.assertIn("pid", self.client.call(tool, {}))

    def test_plain_text_and_json_array_results(self):
        self.assertEqual(self.client.call("plain", {}), "plain text")
        self.assertEqual(self.client.call("array", {}), [1, 2, 3])

    def test_appended_gbrain_notices_do_not_change_data_shape(self):
        self.assertEqual(self.client.call("notice", {}), {"slug": "floodgate/owner"})
        self.assertEqual(self.client.last_notices, ("Backup coverage notice: no full backup yet.",))
        self.assertEqual(self.client.call("empty_notice", {}), [])
        with self.assertRaises(GBrainError) as caught:
            self.client.call("error_notice", {})
        self.assertEqual(caught.exception.code, "page_not_found")
        with self.assertRaisesRegex(GBrainError, "ambiguous"):
            self.client.call("ambiguous", {})
        self.assertEqual(self.client.call("array", {}), [1, 2, 3])
        self.assertEqual(self.client.last_notices, ())

    def test_concurrent_callers_share_one_serialized_process(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda n: self.client.call("echo", {"n": n}), range(20)))
        self.assertEqual([r["arguments"]["n"] for r in results], list(range(20)))
        self.assertEqual(len({r["pid"] for r in results}), 1)

    def test_timeouts_close_child_and_do_not_retry_mutation(self):
        self.client.start()
        self.client.timeout = 0.1
        process = self.client._process
        started = time.monotonic()
        with self.assertRaisesRegex(GBrainError, "outcome may be unknown"):
            self.client.call("slow", {})
        self.assertLess(time.monotonic() - started, 1.5)
        self.assertIsNotNone(process.poll())
        self.assertIsNone(self.client._process)
        self.client.timeout = 1
        self.assertIn("pid", self.client.call("echo", {}))

    def test_malformed_partial_eof_and_wrong_id_fail_closed(self):
        for tool in ("malformed", "partial", "exit", "wrong_id"):
            with self.subTest(tool=tool):
                self.client.start()
                self.client.timeout = 0.1
                process = self.client._process
                with self.assertRaises(GBrainError):
                    self.client.call(tool, {})
                self.assertIsNotNone(process.poll())
                self.assertIsNone(self.client._process)
                self.client.timeout = 1

    def test_missing_command_home_and_invalid_input(self):
        with self.assertRaisesRegex(GBrainError, "not found"):
            GBrainClient(self.home, str(self.home / "missing")).start()
        with self.assertRaisesRegex(GBrainError, "does not exist"):
            GBrainClient(self.home / "missing", str(self.command)).start()
        with self.assertRaises(ValueError):
            GBrainClient(self.home, timeout=0)
        with self.assertRaises(ValueError):
            self.client.call("echo", {"invalid": float("nan")})
        with self.assertRaises(TypeError):
            self.client.call("echo", {"invalid": object()})
        self.assertIsNone(self.client._process)


if __name__ == "__main__":
    unittest.main()
