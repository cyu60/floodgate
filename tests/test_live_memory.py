"""Opt-in real GBrain → personal memory → HTTP gate integration proof.

Run with an installed GBrain executable (no model/API credentials required):
  FLOODGATE_GBRAIN_COMMAND=/absolute/path/to/gbrain \
    python3 -m unittest discover -s tests -p test_live_memory.py -v

The test creates and deletes its own temporary brain. Existing personal and
demo brains are never opened. Only the River scorer and tokenizer renderer are
mocked; MCP, PGLite, graph writes/reads, HTTP, and request compilation are real.
"""
from contextlib import contextmanager
import http.client
from http.server import HTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch

from floodgate import gate_server as gate
from floodgate.gbrain import GBrainClient
from floodgate.memory import PersonalMemory, PersonalMemoryError


COMMAND = os.environ.get("FLOODGATE_GBRAIN_COMMAND")


class ObservedGBrainClient(GBrainClient):
    """Record genuine tool responses without replacing transport or behavior."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.receipts = []

    def call(self, name, arguments):
        result = super().call(name, arguments)
        if name == "put_page":
            self.receipts.append((arguments["slug"], result))
        return result


@contextmanager
def running_gate(memory):
    with HTTPServer(("127.0.0.1", 0), gate.make_handler(None, None, memory)) as server:
        thread = threading.Thread(
            target=lambda: server.serve_forever(poll_interval=0.02), daemon=True,
        )
        thread.start()
        try:
            yield server.server_address
        finally:
            server.shutdown()
            thread.join(timeout=5)


def request(address, method, path, body=None):
    connection = http.client.HTTPConnection(*address, timeout=30)
    try:
        connection.request(method, path,
                           body=json.dumps(body) if body is not None else None,
                           headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        return response.status, json.loads(response.read())
    finally:
        connection.close()


@unittest.skipUnless(COMMAND, "set FLOODGATE_GBRAIN_COMMAND to run real local GBrain integration")
class LiveMemoryTests(unittest.TestCase):
    def test_real_memory_http_corrections_graph_and_restart(self):
        executable = shutil.which(os.path.expanduser(COMMAND))
        self.assertIsNotNone(executable, "FLOODGATE_GBRAIN_COMMAND must name an installed executable")
        executable = str(Path(executable).resolve())
        owner = "live-integration-alice"
        task = "Ship the Nimbus offline demo"
        url = "https://example.org/quiet-harbor"
        observed_records = []

        def score(records, *_args):
            observed_records.append(records)
            return [[1.0, 0.0]]

        with tempfile.TemporaryDirectory(prefix="floodgate-live-memory-") as scratch:
            home = Path(scratch) / "brain"
            home.mkdir(mode=0o700)
            env = {key: value for key, value in os.environ.items()
                   if key in ("HOME", "PATH", "LANG", "TMPDIR", "TMP", "TEMP")
                   or key.startswith("LC_")}
            env["GBRAIN_HOME"] = str(home)
            initialized = subprocess.run(
                [executable, "init", "--pglite", "--no-embedding", "--non-interactive", "--db-only"],
                cwd=home, env=env, capture_output=True, text=True, timeout=120,
            )
            self.assertEqual(initialized.returncode, 0, initialized.stderr[-1500:])
            self.assertTrue((home / ".gbrain/config.json").is_file())
            state = gate.STATE.copy()
            previous_log = gate.LOG
            gate.LOG = Path(scratch) / "gate.jsonl"
            gate.CACHE.clear()
            gate.STATE.update(task="before task", threshold=0.7, checkpoint=None, temperature=1.0)
            try:
                with patch.object(gate, "score_records", side_effect=score) as scorer, \
                        patch.object(gate, "Renderer", return_value=object()):
                    with ObservedGBrainClient(home, executable, timeout=15) as brain:
                        memory = PersonalMemory(brain, owner)
                        # The reference contains no task words: finding it requires
                        # the stored relationship path, not a title/query match.
                        for key, title, kind, body, metadata in (
                            ("nimbus", "Nimbus offline demo", "project", "A prototype for disconnected use.", {}),
                            ("bob", "Bob", "person", "A teammate who knows an experienced engineer.", {}),
                            ("maya", "Maya", "person", "Bob's collaborator and a reference author.", {}),
                            ("harbor", "Quiet Harbor", "resource", "A durable synchronization walkthrough.", {"url": url}),
                        ):
                            memory.upsert_node(key, title, kind, body,
                                               {"provenance": "Synthetic integration fixture", **metadata})
                        for source, target, relation in (
                            ("nimbus", "bob", "has_teammate"),
                            ("bob", "maya", "collaborated_with"),
                            ("maya", "harbor", "authored"),
                        ):
                            memory.connect(source, target, relation, "Synthetic integration fixture")

                        with running_gate(memory) as address:
                            status, written = request(address, "POST", "/task", {
                                "task": task, "user_id": "cannot-switch-the-owner",
                            })
                            self.assertEqual(status, 200, written)
                            self.assertTrue(written["memory"]["saved"], written)
                            self.assertEqual(written["memory"]["owner_id"], owner)

                            status, inspection = request(address, "GET", "/memory?user_id=someone-else")
                            self.assertEqual(status, 200, inspection)
                            self.assertTrue(inspection["available"], inspection)
                            self.assertEqual(inspection["owner_id"], owner)
                            self.assertIn("harbor", [node["key"] for node in inspection["evidence"]])
                            self.assertTrue(any(len(path["edges"]) == 3 for path in inspection["paths"]))

                            status, decision = request(address, "POST", "/decide", {"url": url, "title": "Quiet Harbor"})
                            self.assertEqual(status, 200, decision)
                            model_state = observed_records[-1][0]["state"]
                            self.assertIn(f"Stated task: {task}.", model_state)
                            model_memory = json.JSONDecoder().raw_decode(model_state.split(gate.MEMORY_MARKER, 1)[1])[0]
                            self.assertIn("harbor", [node["key"] for node in model_memory["evidence"]])
                            self.assertTrue(any(len(path["edges"]) == 3 for path in model_memory["paths"]))
                            self.assertIn("Synthetic integration fixture", json.dumps(model_memory))

                            correction_slug = None
                            first_correction_revision = None
                            for label in (0, 1):
                                status, overridden = request(address, "POST", "/override", {
                                    "task": task, "url": url, "title": "Quiet Harbor", "label": label,
                                })
                                self.assertEqual(status, 200, overridden)
                                self.assertTrue(overridden["memory"]["saved"], overridden)
                                corrections = [node for node in memory.context(task, url=url)["evidence"]
                                               if node["kind"] == "correction"]
                                self.assertEqual(len(corrections), 1)
                                self.assertEqual(corrections[0]["metadata"]["label"], label)
                                if correction_slug is None:
                                    correction_slug = corrections[0]["slug"]
                                self.assertEqual(corrections[0]["slug"], correction_slug)
                                stored = brain.call("get_page", {"slug": correction_slug, "include_content": True})
                                self.assertEqual(stored["type"], "note")
                                if first_correction_revision is None:
                                    first_correction_revision = stored["revision"]
                                else:
                                    self.assertNotEqual(stored["revision"], first_correction_revision)

                            # Cache invalidation must let the latest explicit
                            # correction reach the real compile_request output.
                            status, decision = request(address, "POST", "/decide", {"url": url, "title": "Quiet Harbor"})
                            self.assertEqual(status, 200, decision)
                            self.assertEqual(scorer.call_count, 2)
                            corrections = [node for node in json.JSONDecoder().raw_decode(observed_records[-1][0]["state"].split(gate.MEMORY_MARKER, 1)[1])[0]["evidence"]
                                           if node["kind"] == "correction"]
                            self.assertEqual([node["metadata"]["label"] for node in corrections], [1])

                        # These are real top-level mutation receipts, not fake
                        # success flags supplied by a transport stub.
                        self.assertTrue(brain.receipts)
                        for slug, receipt in brain.receipts:
                            self.assertEqual(receipt["state"], "committed", (slug, receipt))
                            self.assertTrue(receipt["revision"])
                            self.assertEqual(receipt["source_id"], "default")
                        correction_writes = [receipt for slug, receipt in brain.receipts if slug == correction_slug]
                        self.assertEqual(len(correction_writes), 2)

                    # The earlier HTTP server and stdio child have both closed;
                    # this reads the existing database from a fresh process.
                    with GBrainClient(home, executable, timeout=15) as restarted:
                        fresh = PersonalMemory(restarted, owner)
                        context = fresh.context(task, url=url)
                        corrections = [node for node in context["evidence"] if node["kind"] == "correction"]
                        self.assertEqual([node["metadata"]["label"] for node in corrections], [1])
                        self.assertEqual(corrections[0]["slug"], correction_slug)
                        self.assertIn("harbor", [node["key"] for node in context["evidence"]])
                        self.assertTrue(any(len(path["edges"]) == 3 for path in context["paths"]))
                        with self.assertRaises(PersonalMemoryError) as rejected:
                            PersonalMemory(restarted, "live-integration-bob")
                        self.assertEqual(rejected.exception.code, "foreign_owner")
                        # Refusing another owner must not change the persisted owner.
                        self.assertEqual(PersonalMemory(restarted, owner).owner_id, owner)
                rows = [json.loads(line) for line in gate.LOG.read_text().splitlines()]
                self.assertEqual([row["label"] for row in rows if row["kind"] == "override"], [0, 1])
            finally:
                gate.STATE.clear()
                gate.STATE.update(state)
                gate.CACHE.clear()
                gate.LOG = previous_log


if __name__ == "__main__":
    unittest.main()
