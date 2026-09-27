"""Synthetic, local two-person GBrain demo. No River key or model calls required."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

from floodgate.gbrain import GBrainClient, GBrainError
from floodgate.memory import PersonalMemory

DEFAULT_HOME = Path.home() / ".local/share/floodgate/demo-brains"
SCENARIOS = {
    "warm-intro": {
        "title": "Who can unblock the demo?",
        "question": "Who can help me ship the Atlas offline demo?",
        "task": "Ship the Atlas offline demo",
        "url": "https://example.org/quiet-harbor",
        "hint": "Atlas → Bob → Maya → Quiet Harbor. The resource does not mention Atlas.",
    },
    "promise": {
        "title": "Why does this page matter?",
        "question": "What should I read to keep my promise to Bob?",
        "task": "Keep the Friday handoff promise",
        "url": "https://example.org/pocket-vault",
        "hint": "Friday handoff → promise → offline constraint → Pocket Vault.",
    },
    "different-person": {
        "title": "Same page, different person",
        "question": "Does Quiet Harbor help my current work?",
        "task": "Prepare the Cedar launch pitch",
        "tasks": {"alice": "Ship the Atlas offline demo", "bob": "Prepare the Cedar launch pitch"},
        "url": "https://example.org/quiet-harbor",
        "hint": "Switch between Alice and Bob. Bob's pitch context is independent of Alice's technical work.",
    },
}

# Entirely fictional people, commitments and resources; URLs are not fetched.
ALICE_NODES = [
    ("alice", "Alice", "person", "I build products with friends and prefer working examples.", {}),
    ("atlas", "Atlas offline demo", "project", "A prototype that works without a network connection.", {"keywords": ["Atlas", "offline", "demo"]}),
    ("bob", "Bob", "person", "My teammate; he knows people who have shipped local software.", {}),
    ("maya", "Maya", "person", "An engineer Bob collaborated with last summer.", {}),
    ("quiet-harbor", "Quiet Harbor", "resource", "Maya's practical guide to conflict resolution and durable local synchronization.", {"url": "https://example.org/quiet-harbor"}),
    ("handoff", "Friday handoff", "project", "The delivery milestone we agreed on.", {"keywords": ["Friday", "handoff", "promise"]}),
    ("promise", "Promise to Bob", "commitment", "I promised Bob a working build by Friday at 5 PM.", {"task": "Keep the Friday handoff promise"}),
    ("constraint", "Works on the train", "constraint", "The build must retain data and work when the network is unavailable.", {}),
    ("pocket-vault", "Pocket Vault", "resource", "An implementation walkthrough for local durable storage.", {"url": "https://example.org/pocket-vault"}),
    ("weekend", "Weekend pottery", "preference", "Alice's private fixture: blue ceramic bowls.", {}),
]
ALICE_EDGES = [
    ("alice", "atlas", "builds", "Alice's project note"),
    ("atlas", "bob", "has_teammate", "Alice's project note"),
    ("bob", "maya", "collaborated_with", "Bob told Alice about a past collaboration"),
    ("maya", "quiet-harbor", "authored", "A resource Alice explicitly saved"),
    ("alice", "handoff", "owns", "Alice's milestone note"),
    ("handoff", "promise", "depends_on", "Alice's explicit commitment"),
    ("promise", "constraint", "requires", "Alice and Bob's delivery checklist"),
    ("constraint", "pocket-vault", "explained_by", "Alice's saved implementation reference"),
]
BOB_NODES = [
    ("bob", "Bob", "person", "I handle customer conversations and prefer short summaries.", {}),
    ("cedar", "Cedar launch pitch", "project", "Prepare a clear product story for potential customers.", {"keywords": ["Cedar", "launch", "pitch"]}),
    ("alice", "Alice", "person", "A friend who works on the technical prototype.", {}),
    ("story", "The five-minute story", "resource", "A guide to explaining a product through a customer's problem.", {"url": "https://example.org/five-minute-story"}),
    ("private", "Bob's weekend plan", "preference", "Bob's private fixture: green hiking boots.", {}),
]
BOB_EDGES = [
    ("bob", "cedar", "owns", "Bob's project note"),
    ("cedar", "story", "supported_by", "Bob's selected presentation guide"),
    ("bob", "alice", "knows", "Bob's own statement"),
]


def initialize(home: Path, command: str) -> None:
    """Create only missing demo stores; never force-reinitialize an existing brain."""
    for owner in ("alice", "bob"):
        root = home / owner
        if (root / ".gbrain/config.json").exists():
            continue
        root.mkdir(parents=True, exist_ok=True)
        env = {k: os.environ[k] for k in ("HOME", "PATH", "LANG", "TMPDIR", "SYSTEMROOT") if k in os.environ}
        env["GBRAIN_HOME"] = str(root.resolve())
        result = subprocess.run(
            [command, "init", "--pglite", "--no-embedding", "--non-interactive", "--db-only"],
            cwd=root, env=env, capture_output=True, text=True, timeout=120,
        )
        if result.returncode:
            raise RuntimeError(f"GBrain initialization failed for {owner}: {result.stderr[-1500:]}")
        print(f"Initialized {owner}'s demo brain (local, no model provider).", flush=True)


def open_memories(stack: ExitStack, home: Path, command: str) -> dict[str, PersonalMemory]:
    return {
        owner: PersonalMemory(stack.enter_context(GBrainClient(home / owner, command, timeout=15)), owner)
        for owner in ("alice", "bob")
    }


def seed(memories: dict[str, PersonalMemory]) -> None:
    for owner, nodes, edges in (("alice", ALICE_NODES, ALICE_EDGES), ("bob", BOB_NODES, BOB_EDGES)):
        memory = memories[owner]
        for key, title, kind, body, metadata in nodes:
            memory.upsert_node(key, title, kind, body, {"provenance": "Synthetic hackathon fixture", **metadata})
        for source, target, relation, provenance in edges:
            memory.connect(source, target, relation, provenance)
        print(f"Saved {owner}: {len(nodes)} nodes, {len(edges)} explicit links.", flush=True)


def ask(memories: dict[str, PersonalMemory], owner: str, scenario: str) -> dict:
    query = dict(SCENARIOS[scenario])
    query["task"] = query.get("tasks", {}).get(owner, query["task"])
    # Retrieval is task-anchored. Passing the resource URL here would make finding
    # it a direct lookup and conceal the graph traversal this demo is proving.
    result = memories[owner].context(query["task"], limit=12)
    return {"owner": owner, "scenario": query, "context": result,
            "note": "Real GBrain retrieval on synthetic data. This view shows evidence, not an LLM answer or River score."}


def verify(home: Path, command: str) -> None:
    """Use fresh processes to prove persistence and connected retrieval."""
    with ExitStack() as stack:
        memories = open_memories(stack, home, command)
        alice = ask(memories, "alice", "warm-intro")["context"]
        promise = ask(memories, "alice", "promise")["context"]
        bob = ask(memories, "bob", "different-person")["context"]
        evidence_keys = lambda result: {item.get("key") for item in result["evidence"]}
        checks = [
            ("quiet-harbor" in evidence_keys(alice), "Missing resource reached through friends"),
            (any(len(path.get("edges", [])) >= 3 for path in alice["paths"]), "Missing three-hop evidence path"),
            ("pocket-vault" in evidence_keys(promise), "Missing promise/constraint resource"),
            ("story" in evidence_keys(bob), "Missing Bob's independent project context"),
            ("quiet-harbor" not in evidence_keys(bob), "Alice's resource leaked into Bob's context"),
            ("green hiking boots" not in json.dumps(alice), "Bob's private fixture leaked"),
            ("weekend" not in evidence_keys(alice), "Unrelated Alice memory entered context"),
        ]
        for passed, message in checks:
            if not passed:
                raise RuntimeError(message)
    print("PASS: restart persistence, three-hop friend path, promise path, unrelated exclusion, separate owner contexts.")


def serve(memories: dict[str, PersonalMemory], port: int) -> None:
    page = Path(__file__).resolve().parent.parent / "tools/memory-demo.html"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            if parsed.path == "/":
                data = page.read_bytes()
                mime = "text/html; charset=utf-8"
            elif parsed.path == "/api/context":
                query = parse_qs(parsed.query)
                owner = query.get("owner", ["alice"])[0]
                scenario = query.get("scenario", ["warm-intro"])[0]
                if owner not in memories or scenario not in SCENARIOS:
                    return self.send_error(400, "Choose a demo owner and scenario")
                try:
                    data = json.dumps(ask(memories, owner, scenario)).encode()
                except (GBrainError, RuntimeError, ValueError):
                    return self.send_error(503, "Memory unavailable; inspect the demo terminal")
                mime = "application/json"
            else:
                return self.send_error(404)
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *args):
            pass

    print(f"Demo: http://127.0.0.1:{port} (fictional profiles; not an account system)", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--home", type=Path, default=DEFAULT_HOME)
    parser.add_argument("--gbrain-command", default="gbrain")
    parser.add_argument("--port", type=int, default=8792)
    parser.add_argument("--owner", choices=("alice", "bob"), default="alice")
    parser.add_argument("--scenario", choices=SCENARIOS, default="warm-intro")
    parser.add_argument("action", choices=("seed", "ask", "verify", "serve"))
    args = parser.parse_args()
    home = args.home.expanduser().resolve()
    try:
        if args.action == "seed":
            initialize(home, args.gbrain_command)
        if args.action == "verify":
            return verify(home, args.gbrain_command)
        with ExitStack() as stack:
            memories = open_memories(stack, home, args.gbrain_command)
            if args.action == "seed":
                seed(memories)
            elif args.action == "ask":
                print(json.dumps(ask(memories, args.owner, args.scenario), indent=2))
            else:
                serve(memories, args.port)
    except (GBrainError, RuntimeError, ValueError, OSError, subprocess.TimeoutExpired) as exc:
        parser.exit(1, f"Demo failed: {exc}\n")


if __name__ == "__main__":
    main()
