"""Memory/gate contract checks; no model packages, credentials, or River calls."""
import http.client
import json
import tempfile
import threading
import unittest
from http.server import HTTPServer
from pathlib import Path
from unittest.mock import patch

from floodgate import gate_server as gate


def model_memory(state):
    return json.JSONDecoder().raw_decode(state.split(gate.MEMORY_MARKER, 1)[1])[0]


class FakeMemory:
    def __init__(self, owner_id="alice"):
        self.owner_id = owner_id
        self.revision = 0
        self.fail = False
        self.writes = []
        self.reads = []
        self.evidence = [{"slug": "shared/project", "body": "Bob's research supports Alice's project"}]
        self.paths = [{"slugs": ["alice", "project", "bob", "research"],
                       "edges": [{"from": "alice", "to": "project", "relation": "working-on"}]}]

    def status(self):
        return {"available": not self.fail, "private_command": "do-not-expose"}

    def context(self, task, url="", title="", limit=8):
        self.reads.append((task, url, title))
        if self.fail:
            raise RuntimeError("sensitive process detail")
        return {"owner_id": self.owner_id, "evidence": self.evidence, "paths": self.paths}

    def record_task(self, task):
        self._write(("task", task))

    def record_override(self, task, url, title, label=0.0):
        self._write(("override", task, url, title, label))

    def _write(self, value):
        if self.fail:
            raise RuntimeError("sensitive process detail")
        self.writes.append(value)
        self.revision += 1


class GateMemoryTests(unittest.TestCase):
    def setUp(self):
        self.state = gate.STATE.copy()
        gate.STATE.update(task="prepare launch", threshold=0.7, checkpoint=None, temperature=1.0, profile="", use_about_me=False)
        gate.CACHE.clear()
        self.temp = tempfile.TemporaryDirectory()
        self.memory = FakeMemory()
        self.records = []
        self.scorer = patch.object(gate, "score_records", side_effect=self.score).start()
        patch.object(gate, "Renderer", return_value=object()).start()
        patch.object(gate, "LOG", Path(self.temp.name) / "gate.jsonl").start()
        self.server = HTTPServer(("127.0.0.1", 0), gate.make_handler(None, None, self.memory))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        patch.stopall()
        self.temp.cleanup()
        gate.STATE.clear()
        gate.STATE.update(self.state)
        gate.CACHE.clear()

    def score(self, records, *_args):
        self.records.append(records)
        return [[0.0, 1.0]]

    def request(self, method, path, body=None, raw=None, headers=None):
        connection = http.client.HTTPConnection(*self.server.server_address, timeout=5)
        payload = raw if raw is not None else (json.dumps(body) if body is not None else None)
        connection.request(method, path, body=payload, headers={"Content-Type": "application/json", **(headers or {})})
        response = connection.getresponse()
        result = response.status, json.loads(response.read())
        connection.close()
        return result

    def test_graph_evidence_reaches_model_and_response(self):
        decision = gate.decide(None, None, "https://example.com/research", "Bob's research", memory=self.memory)
        state = self.records[0][0]["state"]
        self.assertEqual(model_memory(state)["owner_id"], "alice")
        self.assertEqual(model_memory(state)["paths"], self.memory.paths)
        self.assertEqual(decision["memory"]["evidence"], self.memory.evidence)
        self.assertTrue(decision["memory"]["available"])
        self.assertNotIn("private_command", decision["memory"])

    def test_cache_tracks_owner_task_revision_title_and_content(self):
        url = "https://example.com"
        gate.decide(None, None, url, "research", memory=self.memory)
        gate.decide(None, None, url + "#same-page", "research", memory=self.memory)
        self.assertEqual(self.scorer.call_count, 1)
        self.memory.revision += 1
        gate.decide(None, None, url, "research", memory=self.memory)
        gate.STATE["task"] = "new task"
        gate.decide(None, None, url, "research", memory=self.memory)
        gate.decide(None, None, url, "research", memory=FakeMemory("bob"))
        gate.decide(None, None, url, "new title", memory=self.memory)
        self.memory.evidence.append({"body": "new shared fact"})
        gate.decide(None, None, url, "new title", memory=self.memory)
        self.assertEqual(self.scorer.call_count, 6)

    def test_memory_outage_drops_stale_context_and_recovery_works(self):
        url = "https://example.com"
        gate.decide(None, None, url, "research", memory=self.memory)
        self.memory.fail = True
        result = gate.decide(None, None, url, "research", memory=self.memory)
        self.assertFalse(result["memory"]["available"])
        self.assertEqual(result["memory"]["evidence"], [])
        self.assertNotIn(gate.MEMORY_MARKER, self.records[-1][0]["state"])
        self.assertNotIn("sensitive", json.dumps(result))
        self.memory.fail = False
        self.assertTrue(gate.decide(None, None, url, "research", memory=self.memory)["memory"]["available"])

    def test_no_memory_retains_original_decision_shape(self):
        result = gate.decide(None, None, "https://example.com", "", None)
        self.assertEqual(set(result), {"p", "lock", "task"})
        self.assertNotIn(gate.MEMORY_MARKER, self.records[0][0]["state"])
        self.assertRegex(self.records[0][0]["state"], r"^URL: https://example.com Title: \. Time: \d{2}:\d{2} \w+\. Stated task: prepare launch\.$")

    def test_per_request_task_and_opt_in_profile_preserve_training_text(self):
        status, result = self.request("POST", "/decide", {
            "url": "https://example.com", "title": "resource", "task": "Atlas research",
            "about_me": "I study distributed systems", "user_id": "bob",
        })
        self.assertEqual(status, 200)
        self.assertEqual(result["task"], "Atlas research")
        self.assertEqual(result["memory"]["owner_id"], "alice")
        self.assertEqual(self.memory.reads[-1][0], "Atlas research")
        self.assertEqual(gate.STATE["task"], "prepare launch")
        self.assertIn("Stated task: Atlas research.", self.records[-1][0]["state"])
        self.assertNotIn("About me:", self.records[-1][0]["state"])
        gate.STATE["use_about_me"] = True
        gate.decide(None, None, "https://example.com", "resource", "Atlas research", "I study distributed systems", memory=self.memory)
        self.assertIn(" About me: I study distributed systems.", self.records[-1][0]["state"])
        self.assertEqual(self.scorer.call_count, 2)

    def test_profile_fallback_and_model_hot_swap_are_validated_atomically(self):
        status, result = self.request("POST", "/task", {"profile": "Reader of practical examples"})
        self.assertEqual(status, 200)
        self.assertEqual(result["profile"], "Reader of practical examples")
        gate.STATE["use_about_me"] = True
        gate.decide(None, None, "https://example.com", "resource", memory=self.memory)
        self.assertIn("About me: Reader of practical examples.", self.records[-1][0]["state"])
        status, result = self.request("POST", "/model", {"checkpoint": "river://new-checkpoint", "temperature": 0.8})
        self.assertEqual(status, 200)
        self.assertEqual(result, {"checkpoint": "river://new-checkpoint", "temperature": 0.8})
        self.assertFalse(gate.CACHE)
        for invalid in (0, -1, float("nan"), True, "hot"):
            self.assertEqual(self.request("POST", "/model", {"checkpoint": "bad", "temperature": invalid})[0], 400)
            self.assertEqual(gate.STATE["checkpoint"], "river://new-checkpoint")
            self.assertEqual(gate.STATE["temperature"], 0.8)

    def test_task_and_override_are_written_and_invalidate_cache(self):
        gate.decide(None, None, "https://example.com", "", memory=self.memory)
        status, result = self.request("POST", "/task", {"task": "project research", "user_id": "bob"})
        self.assertEqual(status, 200)
        self.assertEqual(result["memory"]["owner_id"], "alice")
        self.assertEqual(self.memory.writes[-1], ("task", "project research"))
        self.assertFalse(gate.CACHE)
        gate.decide(None, None, "https://example.com", "", memory=self.memory)
        status, result = self.request("POST", "/override", {
            "url": "https://example.com", "title": "research", "task": "project research",
            "label": 0.0, "user_id": "bob", "extra_secret": "not-logged",
        })
        self.assertEqual(status, 200)
        self.assertTrue(result["logged"])
        self.assertTrue(result["memory"]["saved"])
        self.assertFalse(gate.CACHE)
        self.assertEqual(self.memory.writes[-1], ("override", "project research", "https://example.com", "research", 0.0))
        rows = gate.LOG.read_text()
        self.assertNotIn("extra_secret", rows)
        self.assertNotIn("user_id", rows)

    def test_failed_memory_write_keeps_task_and_training_log(self):
        self.memory.fail = True
        status, result = self.request("POST", "/task", {"task": "new task"})
        self.assertEqual(status, 200)
        self.assertEqual(gate.STATE["task"], "new task")
        self.assertFalse(result["memory"]["saved"])
        status, result = self.request("POST", "/override", {"url": "https://example.com"})
        self.assertEqual(status, 200)
        self.assertTrue(result["logged"])
        self.assertFalse(result["memory"]["saved"])
        self.assertIn('"kind": "override"', gate.LOG.read_text())

    def test_memory_inspection_cannot_select_other_owner(self):
        status, result = self.request("GET", "/memory?user_id=bob")
        self.assertEqual(status, 200)
        self.assertEqual(result["owner_id"], "alice")
        self.assertEqual(result["paths"], self.memory.paths)
        self.assertNotIn("private_command", result)

    def test_wrong_owner_context_is_discarded(self):
        with patch.object(self.memory, "context", return_value={"owner_id": "bob", "evidence": ["secret"]}):
            result = gate.decide(None, None, "https://example.com", "", memory=self.memory)
        self.assertFalse(result["memory"]["available"])
        self.assertEqual(result["memory"]["evidence"], [])
        self.assertNotIn(gate.MEMORY_MARKER, self.records[-1][0]["state"])

    def test_visited_site_cannot_read_memory_or_poison_task(self):
        headers = {"Origin": "https://untrusted.example"}
        self.assertEqual(self.request("GET", "/memory", headers=headers)[0], 403)
        self.assertEqual(self.request("POST", "/task", {"task": "injected"}, headers=headers)[0], 403)
        self.assertEqual(self.memory.writes, [])
        self.assertEqual(gate.STATE["task"], "prepare launch")
        self.assertEqual(self.request("GET", "/memory", headers={"Host": "rebind.example"})[0], 403)

    def test_extension_and_same_local_origin_can_read_memory(self):
        extension = "chrome-extension://" + "a" * 32
        self.assertEqual(self.request("GET", "/memory", headers={"Origin": extension})[0], 200)
        local = f"http://127.0.0.1:{self.server.server_port}"
        self.assertEqual(self.request("GET", "/memory", headers={"Origin": local})[0], 200)
        invalid = "chrome-extension://not-an-extension"
        self.assertEqual(self.request("GET", "/memory", headers={"Origin": invalid})[0], 403)

    def test_invalid_writes_do_not_change_memory(self):
        for body in [{"task": ""}, {"task": 42}, {"task": "a" * 1001}]:
            self.assertEqual(self.request("POST", "/task", body)[0], 400)
        for body in [{"url": "javascript:alert(1)"}, {"url": "https://example.com", "label": 2},
                     {"url": "https://example.com", "model_p": float("nan")}]:
            self.assertEqual(self.request("POST", "/override", body)[0], 400)
        self.assertEqual(self.request("POST", "/task", raw="{")[0], 400)
        self.assertEqual(self.request("POST", "/task", raw="x" * (gate.MAX_BODY + 1))[0], 413)
        self.assertEqual(self.memory.writes, [])
        self.assertEqual(gate.STATE["task"], "prepare launch")

    def test_historical_task_soft_label_keeps_exact_task_attribution(self):
        status, result = self.request("POST", "/override", {
            "url": "https://example.com", "task": "old task", "label": 0.5,
            "scope": "url", "mode": "focus", "kind": "dashboard", "user_id": "bob",
        })
        self.assertEqual(status, 200)
        self.assertTrue(result["memory"]["saved"])
        self.assertEqual(result["memory"]["owner_id"], "alice")
        self.assertEqual(self.memory.writes[-1], ("override", "old task", "https://example.com", "", 0.5))
        self.assertEqual(gate.STATE["task"], "prepare launch")
        row = json.loads(gate.LOG.read_text())
        self.assertEqual((row["kind"], row["label_kind"], row["scope"], row["mode"]), ("override", "dashboard", "url", "focus"))

    def test_domain_label_is_logged_without_claiming_page_memory_saved(self):
        status, result = self.request("POST", "/override", {
            "url": "https://example.com", "task": "old task", "label": 0.5, "scope": "domain",
        })
        self.assertEqual(status, 200)
        self.assertTrue(result["logged"])
        self.assertFalse(result["memory"]["saved"])
        self.assertEqual(result["memory"]["reason"], "domain_scope_not_supported")
        self.assertEqual(self.memory.writes, [])
        self.assertEqual(json.loads(gate.LOG.read_text())["scope"], "domain")

    def test_model_context_has_total_size_budget(self):
        self.memory.evidence = [{"body": "x" * 10_000, "metadata": {str(i): "y" * 2000 for i in range(30)}} for _ in range(100)]
        result = gate.decide(None, None, "https://example.com", "", memory=self.memory)
        self.assertLessEqual(len(json.dumps(model_memory(self.records[-1][0]["state"]))), 20_000)
        self.assertTrue(result["memory"]["available"])

    def test_context_budget_preserves_correction_before_graph_and_other_evidence(self):
        correction = {"kind": "correction", "body": "Owner explicitly marked this page on task.",
                      "metadata": {"label": 0, "task": "prepare launch", "url": "https://example.com"}}
        large_evidence = [{"kind": "resource", "body": "x" * 1000,
                           "metadata": {str(i): "y" * 1000 for i in range(12)}} for _ in range(2)]
        paths = [{"nodes": [{"body": "x" * 400} for _ in range(4)],
                  "edges": [{"provenance": "y" * 1000} for _ in range(3)]} for _ in range(8)]
        found = {"owner_id": self.memory.owner_id, "evidence": large_evidence + [correction], "paths": paths}
        with patch.object(self.memory, "context", return_value=found):
            result = gate.decide(None, None, "https://example.com", "", memory=self.memory)
        context = model_memory(self.records[-1][0]["state"])
        self.assertIn(correction, context["evidence"])
        self.assertEqual(context["paths"], [])
        self.assertLessEqual(len(json.dumps(context)), 20_000)
        self.assertTrue(result["memory"]["truncated"])


if __name__ == "__main__":
    unittest.main()
