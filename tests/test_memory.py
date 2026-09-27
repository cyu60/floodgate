"""Behavior checks using GBrain's page/revision/GraphPath wire shapes."""
from collections import deque
import copy
import json
import re
import unittest
from unittest.mock import patch

from floodgate.memory import PersonalMemory, PersonalMemoryError, canonical_url


class FakeGBrain:
    def __init__(self):
        self.pages, self.edges, self.calls = {}, {}, []
        self.fail = None

    def call(self, name, args):
        self.calls.append((name, copy.deepcopy(args)))
        if self.fail == name:
            raise PersonalMemoryError("unavailable")
        if name == "get_page":
            if args["slug"] not in self.pages:
                raise PersonalMemoryError("page_not_found")
            return copy.deepcopy(self.pages[args["slug"]])
        if name == "put_page":
            old = self.pages.get(args["slug"])
            if old and args.get("expected_revision") != old["revision"]:
                raise PersonalMemoryError("revision_conflict")
            if not old and "expected_revision" in args:
                raise PersonalMemoryError("revision_conflict")
            title = json.loads(re.search(r"(?m)^title: (.+)$", args["content"])[1])
            self.pages[args["slug"]] = {"slug": args["slug"], "title": title,
                                        "content": args["content"], "revision": str(int(old["revision"]) + 1 if old else 1)}
            return {"status": "updated" if old else "created", "revision": self.pages[args["slug"]]["revision"]}
        if name == "add_link":
            assert "link_type" not in args  # No undeclared schema predicates.
            assert args["from"] in self.pages and args["to"] in self.pages
            self.edges[(args["from"], args["to"], args.get("link_source", "manual"))] = {"from_slug": args["from"], "to_slug": args["to"], "link_type": "", "context": args["context"]}
            return {"status": "ok"}
        if name == "list_pages":
            return [{"slug": p["slug"], "title": p["title"]} for p in sorted(self.pages.values(), key=lambda p: p["slug"])
                    if args["tag"] in p["content"]][:args["limit"]]
        if name == "search":
            return [{"slug": p["slug"], "title": p["title"]} for p in self.pages.values()
                    if set(args["query"].casefold().split()) & set(p["content"].casefold().split())][:args["limit"]]
        if name == "traverse_graph":
            assert args["direction"] == "both"
            result, seen = {}, {args["slug"]}
            queue = deque([(args["slug"], 0)])
            while queue:
                slug, depth = queue.popleft()
                if depth >= args["depth"]:
                    continue
                for pair, edge in self.edges.items():
                    if slug in pair:
                        result[pair] = dict(edge, depth=depth + 1)
                        other = pair[1] if pair[0] == slug else pair[0]
                        if other not in seen:
                            seen.add(other)
                            queue.append((other, depth + 1))
            return list(result.values())
        raise AssertionError(name)


class PersonalMemoryTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeGBrain()
        self.memory = PersonalMemory(self.client, "alice")

    def node(self, key, title, kind, body="", **metadata):
        return self.memory.upsert_node(key, title, kind, body or title, metadata)

    def edge(self, source, target, relation="connected_to"):
        self.memory.connect(source, target, relation, "Alice explicitly described this connection.")

    def test_three_hop_resource_has_attributed_path_without_keyword_overlap(self):
        self.node("atlas", "Atlas", "project")
        self.node("bob", "Bob", "person", "Alice's teammate.", person_id="bob")
        self.node("maya", "Maya", "person", "Bob's collaborator.", person_id="maya")
        resource = self.node("harbor", "Quiet Harbor", "resource", "Consent checklist.", url="https://example.com/harbor")
        self.edge("atlas", "bob", "has_teammate")
        self.edge("bob", "maya", "collaborates_with")
        self.edge("maya", "harbor", "recommends")
        # An unrelated project attached to the same friend must not leak its branch.
        self.node("weekend", "Weekend camping", "project")
        unrelated = self.node("tent", "Pine tent", "resource")
        self.edge("bob", "weekend", "organizes")
        self.edge("weekend", "tent", "uses")
        self.node("snack", "Favorite snack", "preference", "Potato chips")
        self.edge("bob", "snack", "prefers")
        result = self.memory.context("Prepare Atlas", "https://example.com/harbor")
        evidence = {item["slug"]: item for item in result["evidence"]}
        self.assertIn(resource, evidence)
        self.assertNotIn(unrelated, evidence)
        self.assertNotIn(self.memory._slug("snack"), evidence)
        path = next(p for p in result["paths"] if p["slugs"][-1] == resource)
        self.assertEqual(len(path["edges"]), 3)
        self.assertEqual(path["titles"], ["Atlas", "Bob", "Maya", "Quiet Harbor"])
        self.assertEqual(path["nodes"][1]["body"], "Alice's teammate.")
        self.assertEqual([e["relation"] for e in path["edges"]], ["has_teammate", "collaborates_with", "recommends"])
        self.assertTrue(all(e["provenance"] for e in path["edges"]))
        self.assertTrue(any(name == "traverse_graph" for name, _ in self.client.calls))

    def test_reversed_edges_and_restart_preserve_real_graph(self):
        self.node("atlas", "Atlas", "project")
        self.node("promise", "Deliver a consent review", "commitment")
        self.node("rules", "Consent checklist", "resource")
        self.edge("promise", "atlas", "supports")
        self.edge("rules", "promise", "required_for")
        fresh = PersonalMemory(self.client, "alice")
        result = fresh.context("Finish Atlas")
        self.assertIn("rules", [e["key"] for e in result["evidence"]])
        path = next(p for p in result["paths"] if p["slugs"][-1] == fresh._slug("rules"))
        self.assertEqual(path["edges"][0]["from"], fresh._slug("promise"))

    def test_unrelated_preference_cannot_bridge_to_resource(self):
        self.node("atlas", "Atlas", "project")
        self.node("bob", "Bob", "person")
        self.node("hobby", "Weekend pottery", "preference")
        self.node("video", "Pottery tutorial", "resource")
        self.edge("atlas", "bob", "has_teammate")
        self.edge("bob", "hobby", "enjoys")
        self.edge("hobby", "video", "explained_by")
        result = self.memory.context("Prepare Atlas")
        self.assertNotIn("video", [e["key"] for e in result["evidence"]])
        self.assertFalse(any(self.memory._slug("hobby") in p["slugs"] for p in result["paths"]))

    def test_owner_root_and_foreign_links_cannot_cross_brains(self):
        with self.assertRaisesRegex(PersonalMemoryError, "foreign_owner"):
            PersonalMemory(self.client, "bob")
        bob = PersonalMemory(FakeGBrain(), "bob")
        bob_secret = bob.upsert_node("secret", "Atlas private finances", "note", "Bob's confidential fixture")
        self.node("atlas", "Atlas", "project")
        self.client.edges[(self.memory._slug("atlas"), bob_secret)] = {
            "from_slug": self.memory._slug("atlas"), "to_slug": bob_secret,
            "context": json.dumps({"version": 1, "owner_id": "alice", "relation": "knows", "provenance": "forged"})}
        result = self.memory.context("Atlas")
        self.assertNotIn("confidential", json.dumps(result))
        self.assertFalse(any(name == "get_page" and args["slug"] == bob_secret for name, args in self.client.calls))
        with self.assertRaisesRegex(PersonalMemoryError, "foreign_owner"):
            self.memory.connect("atlas", bob_secret, "knows", "Alice says so")

    def test_poisoned_owner_field_is_rejected_even_in_own_namespace(self):
        slug = self.node("atlas", "Atlas", "project")
        self.client.pages[slug]["content"] = self.client.pages[slug]["content"].replace('"owner_id": "alice"', '"owner_id": "bob"')
        with self.assertRaisesRegex(PersonalMemoryError, "foreign_owner"):
            self.memory.context("Atlas")

    def test_correction_replaces_old_label_and_is_scoped_to_task_and_page(self):
        url = "https://example.com/video?v=1&utm_source=test#time"
        self.memory.record_override("Study Atlas", url, "A video", 0.0)
        before, pages = self.memory.revision, len(self.client.pages)
        self.memory.record_override("Study Atlas", url, "A video", 1.0)
        self.assertGreater(self.memory.revision, before)
        self.assertEqual(len(self.client.pages), pages)
        result = self.memory.context("Study Atlas", "https://example.com/video?v=1")
        correction = [e for e in result["evidence"] if e["kind"] == "correction"]
        self.assertEqual(len(correction), 1)
        self.assertEqual(correction[0]["metadata"]["label"], 1.0)
        unrelated = self.memory.context("Rest tonight", "https://example.com/video?v=1")
        self.assertFalse(any(e["kind"] == "correction" for e in unrelated["evidence"]))

    def test_updates_round_trip_timeline_and_use_current_revision(self):
        slug = self.node("atlas", "Atlas", "project", "Version one")
        self.client.pages[slug]["content"] += "\n<!-- timeline -->\n2026-09-27 Preserve this external note.\n"
        old_revision = self.client.pages[slug]["revision"]
        self.node("atlas", "Atlas revised", "project", "Version two")
        page = self.client.pages[slug]
        self.assertIn("Preserve this external note", page["content"])
        self.assertNotIn("Version one", page["content"])
        put = [args for name, args in self.client.calls if name == "put_page"][-1]
        self.assertEqual(put["expected_revision"], old_revision)
        self.assertEqual(page["title"], "Atlas revised")
        revision = self.memory.revision
        self.node("atlas", "Atlas revised", "project", "Version two")
        self.assertEqual(self.memory.revision, revision)

    def test_distinct_relationships_between_same_people_are_retained(self):
        self.node("alice", "Alice", "person")
        self.node("bob", "Bob", "person")
        self.edge("alice", "bob", "knows")
        self.edge("alice", "bob", "works_with")
        self.assertEqual(len(self.client.edges), 2)
        self.assertEqual({json.loads(e["context"])["relation"] for e in self.client.edges.values()}, {"knows", "works_with"})

    def test_pending_top_level_receipt_does_not_report_success(self):
        original = self.client.call
        def pending(name, args):
            return {"state": "queued"} if name == "put_page" else original(name, args)
        self.client.call = pending
        revision = self.memory.revision
        with self.assertRaisesRegex(PersonalMemoryError, "write_not_committed"):
            self.node("atlas", "Atlas", "project")
        self.assertEqual(self.memory.revision, revision)
        self.assertFalse(self.memory.status()["available"])

    def test_bad_page_diagnostic_identifies_shape_without_revealing_content(self):
        slug = self.node("atlas", "Atlas", "project")
        header = self.client.pages[slug]["content"].split("<!-- floodgate:start -->")[0]
        self.client.pages[slug]["content"] = header + "Private fixture text without the required managed markers."
        with self.assertRaises(PersonalMemoryError) as raised:
            self.memory.context("Atlas")
        self.assertEqual(raised.exception.code, "invalid_page_markers")
        self.assertNotIn("Private", str(raised.exception))
        self.assertFalse(self.memory.status()["available"])

    def test_failed_write_and_budget_are_reported_truthfully(self):
        revision = self.memory.revision
        self.client.fail = "put_page"
        with self.assertRaises(PersonalMemoryError):
            self.node("atlas", "Atlas", "project")
        self.assertEqual(self.memory.revision, revision)
        self.assertFalse(self.memory.status()["available"])
        self.client.fail = None
        with patch("floodgate.memory.time.monotonic", side_effect=[0, 5]):
            result = self.memory.context("Atlas")
        self.assertTrue(result["truncated"])
        self.assertEqual(result["evidence"], [])

    def test_url_normalization_retains_resource_identity(self):
        self.assertEqual(canonical_url("https://user:secret@example.com/video?v=42&utm_source=x&access_token=secret#fragment"),
                         "https://example.com/video?v=42")
        with self.assertRaises(ValueError):
            canonical_url("javascript:alert(1)")


if __name__ == "__main__":
    unittest.main()
