"""TDD for the Floodgate QM skill. Encodes the 15:55 failure: the QM agent found skills/floodgate/ but no
runnable client (tool binaries need `qm sandbox publish`; only skill text trees ship with `qm up`).

  python3 -m unittest tests/test_floodgate_skill.py            # offline tests (mock server)
  LIVE=1 python3 -m unittest tests/test_floodgate_skill.py     # + real public endpoint
"""
import json, os, shutil, subprocess, sys, tempfile, threading, unittest
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "sandbox" / "skills" / "floodgate"
SCRIPT_REL = "skills/floodgate/floodgate.py"   # path the agent runs, relative to its workspace


class Mock(BaseHTTPRequestHandler):
    seen = []
    send_probs = {}
    checkpoint = "river://abc/sampler_weights/floodgate-personal-v1"

    def do_GET(self):
        out = json.dumps({"models": [{"name": "open-jev-river", "checkpoint": Mock.checkpoint, "temperature": 1.0}]}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        Mock.seen.append({"auth": self.headers.get("Authorization"), "path": self.path, "body": body})
        if self.headers.get("Authorization") != "Bearer good-token":
            self.send_response(401); self.end_headers(); self.wfile.write(b'{"detail":"bad token"}'); return
        if "q" not in body["questions"]:
            probs = Mock.send_probs
            answers = {k: {"type": "noul", "noul": probs.get(k, 0.5)} for k in body["questions"]}
            out = json.dumps({"answers": answers, "model": "open-jev-river", "checkpoint": Mock.checkpoint}).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out); return
        q = body["questions"]["q"]
        ans = {"type": "noul", "noul": 0.25} if q["type"] == "noul" else {
            "type": "choice", "choice": list(q["criteria"])[0], "probabilities": {k: (0.9 if i == 0 else 0.1 / (len(q["criteria"]) - 1)) for i, k in enumerate(q["criteria"])}, "confidence": 0.85}
        out = json.dumps({"answers": {"q": ans}, "model": "mock"}).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(out)
    def log_message(self, *a): pass


def workspace(config):
    """A fresh agent workspace: skills/floodgate/ copied as QM materializes it (no exec bit, no env)."""
    ws = Path(tempfile.mkdtemp())
    shutil.copytree(SKILL, ws / "skills" / "floodgate")
    for f in (ws / "skills" / "floodgate").iterdir():
        f.chmod(0o644)
    if config is not None:
        (ws / "skills" / "floodgate" / "config.json").write_text(json.dumps(config))
    return ws


def run(ws, *args, env=None):
    e = {"PATH": os.environ["PATH"], "HOME": str(ws)}
    e.update(env or {})
    return subprocess.run([sys.executable, SCRIPT_REL, *args], cwd=ws, env=e, capture_output=True, text=True, timeout=90)


class Layer(unittest.TestCase):
    def test_script_ships_inside_the_skill(self):
        self.assertTrue((SKILL / "floodgate.py").is_file(), "skills/floodgate/floodgate.py must exist (skill text trees are what `qm up` delivers)")
        self.assertTrue((SKILL / "config.json").is_file(), "skills/floodgate/config.json must carry the endpoint")

    def test_skill_tells_agent_to_run_it_with_python3(self):
        md = (SKILL / "SKILL.md").read_text()
        self.assertIn(f"python3 {SCRIPT_REL}", md)
        self.assertNotRegex(md, r"(?m)^\s*`floodgate (ask|choice|distraction)", "must not tell the agent to run an uninstalled `floodgate` binary")

    def test_no_advertised_tool_without_published_image(self):
        self.assertFalse((ROOT / "sandbox" / "tools" / "floodgate" / "tool.json").exists(),
                         "don't advertise a `floodgate` CLI until `qm sandbox publish` bakes it into the image")

    def test_skill_assets_are_text(self):
        for f in SKILL.iterdir():
            f.read_text(encoding="utf-8")  # raises on binary


class Offline(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Mock)
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Mock.seen.clear()

    def test_runs_with_no_env_using_shipped_config(self):
        ws = workspace({"url": self.url, "token": "good-token"})
        r = run(ws, "ask", "Hey Aditya, merged your PR! Also have you seen the GTA 6 trailer?", "Does this message stay on the goal?")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("P(yes) = 0.25", r.stdout)
        self.assertEqual(Mock.seen[-1]["auth"], "Bearer good-token")
        self.assertEqual(Mock.seen[-1]["path"], "/v1/systemone")

    def test_env_overrides_config(self):
        ws = workspace({"url": "http://127.0.0.1:9", "token": "wrong"})
        r = run(ws, "ask", "x", "y?", env={"FLOODGATE_URL": self.url, "FLOODGATE_TOKEN": "good-token"})
        self.assertEqual(r.returncode, 0, r.stderr)

    def test_choice(self):
        ws = workspace({"url": self.url, "token": "good-token"})
        r = run(ws, "choice", "charged twice, refund", "Which team?", "billing", "technical", "other")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("-> billing", r.stdout)

    def test_distraction_sends_trained_state_format(self):
        ws = workspace({"url": self.url, "token": "good-token"})
        r = run(ws, "distraction", "GTA 6 gameplay reveal", "--task", "build Floodgate")
        self.assertEqual(r.returncode, 0, r.stderr)
        state = Mock.seen[-1]["body"]["state"]
        self.assertRegex(state, r"^URL: .* Title: GTA 6 gameplay reveal\. Time: \d\d:\d\d \w+\. Stated task: build Floodgate\.$")

    def test_bad_token_is_a_clear_error(self):
        ws = workspace({"url": self.url, "token": "nope"})
        r = run(ws, "ask", "x", "y?")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("401", r.stderr + r.stdout)

    def test_unreachable_is_a_clear_error(self):
        ws = workspace({"url": "http://127.0.0.1:9", "token": "t"})
        r = run(ws, "ask", "x", "y?")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("cannot reach", r.stderr + r.stdout)


class SendArticle(unittest.TestCase):
    """Floodgate's core decision: should I send this article to this person?"""
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Mock)
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def ws(self):
        return workspace({"url": self.url, "token": "good-token"})

    ARGS = ["send", "--article", "Open-Jev: typed decisions from open models", "--person", "Aditya: ML engineer on my hackathon team, building the Floodgate extension"]

    def test_asks_atomic_questions_in_one_call(self):
        Mock.send_probs = {"relevant": 0.9, "new_to_them": 0.8, "timely": 0.85, "appropriate": 0.9}
        r = run(self.ws(), *self.ARGS)
        self.assertEqual(r.returncode, 0, r.stderr)
        qs = Mock.seen[-1]["body"]["questions"]
        self.assertEqual(set(qs), {"relevant", "new_to_them", "timely", "appropriate"})
        self.assertTrue(all(q["type"] == "noul" for q in qs.values()))
        state = Mock.seen[-1]["body"]["state"]
        self.assertIn("Open-Jev", json.dumps(state)); self.assertIn("Aditya", json.dumps(state))

    def test_send_when_all_signals_high(self):
        Mock.send_probs = {"relevant": 0.9, "new_to_them": 0.8, "timely": 0.85, "appropriate": 0.9}
        r = run(self.ws(), *self.ARGS)
        self.assertIn("SEND", r.stdout); self.assertNotIn("DON'T SEND", r.stdout)
        for k in ("relevant", "new_to_them", "timely", "appropriate"):
            self.assertIn(k, r.stdout)

    def test_dont_send_when_irrelevant(self):
        Mock.send_probs = {"relevant": 0.1, "new_to_them": 0.9, "timely": 0.8, "appropriate": 0.9}
        r = run(self.ws(), *self.ARGS)
        self.assertIn("DON'T SEND", r.stdout)

    def test_dont_send_when_inappropriate_even_if_relevant(self):
        Mock.send_probs = {"relevant": 0.95, "new_to_them": 0.9, "timely": 0.9, "appropriate": 0.15}
        r = run(self.ws(), *self.ARGS)
        self.assertIn("DON'T SEND", r.stdout)

    def test_hold_when_unsure(self):
        Mock.send_probs = {"relevant": 0.6, "new_to_them": 0.5, "timely": 0.45, "appropriate": 0.8}
        r = run(self.ws(), *self.ARGS)
        self.assertIn("HOLD", r.stdout)

    def test_optional_reason_is_passed(self):
        Mock.send_probs = {"relevant": 0.9, "new_to_them": 0.8, "timely": 0.85, "appropriate": 0.9}
        run(self.ws(), *self.ARGS, "--why", "he asked how Open-Jev works")
        self.assertIn("he asked how Open-Jev works", json.dumps(Mock.seen[-1]["body"]["state"]))

    def test_skill_leads_with_send_decision(self):
        md = (SKILL / "SKILL.md").read_text()
        self.assertIn("python3 skills/floodgate/floodgate.py send", md)
        self.assertRegex(md.split("---")[2], r"(?i)should I send this article")

class RightThings(unittest.TestCase):
    """Prove the agent is using the right things: reachable server, valid token, the PERSONAL model, sane answers."""
    @classmethod
    def setUpClass(cls):
        cls.srv = HTTPServer(("127.0.0.1", 0), Mock)
        cls.url = f"http://127.0.0.1:{cls.srv.server_port}"
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    def setUp(self):
        Mock.checkpoint = "river://abc/sampler_weights/floodgate-personal-v1"
        Mock.send_probs = {"relevant": 0.05, "new_to_them": 0.8, "timely": 0.07, "appropriate": 0.3}

    def ws(self, token="good-token"):
        return workspace({"url": self.url, "token": token, "expect_model": "floodgate-personal-v1"})

    def test_status_all_green(self):
        r = run(self.ws(), "status")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        for line in ("reachable", "token", "model", "sanity"):
            self.assertRegex(r.stdout, rf"OK +{line}")
        self.assertIn("floodgate-personal-v1", r.stdout)

    def test_status_flags_wrong_model(self):
        Mock.checkpoint = "river://abc/sampler_weights/open-jev-river-v1"
        r = run(self.ws(), "status")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("WRONG MODEL", r.stdout)

    def test_status_flags_bad_token(self):
        r = run(self.ws(token="nope"), "status")
        self.assertNotEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"FAIL +token")

    def test_status_flags_insane_answers(self):
        Mock.send_probs = {"relevant": 0.9, "new_to_them": 0.9, "timely": 0.9, "appropriate": 0.9}  # says SEND celebrity gossip
        r = run(self.ws(), "status")
        self.assertNotEqual(r.returncode, 0)
        self.assertRegex(r.stdout, r"FAIL +sanity")

    def test_every_send_answer_names_the_model(self):
        r = run(self.ws(), "send", "--article", "x", "--person", "y")
        self.assertIn("model: floodgate-personal-v1", r.stdout)

    def test_skill_says_run_status_first_and_never_fake_it(self):
        md = (SKILL / "SKILL.md").read_text()
        self.assertIn("python3 skills/floodgate/floodgate.py status", md)
        self.assertRegex(md, r"(?i)never (substitute|replace|fake)")

@unittest.skipUnless(os.environ.get("LIVE"), "set LIVE=1 to hit the real public endpoint")
class Live(unittest.TestCase):
    def test_real_endpoint_with_shipped_config(self):
        ws = workspace(None)  # use the config.json exactly as shipped to QM
        r = run(ws, "ask", "Hey Aditya, merged your PR! Also have you seen the GTA 6 trailer?",
                "Does this message stay on the goal of getting Aditya to test the extension before 4:15?")
        self.assertEqual(r.returncode, 0, r.stderr)
        p = float(r.stdout.split("P(yes) = ")[1].split()[0])
        self.assertLess(p, 0.5, r.stdout)

@unittest.skipUnless(os.environ.get("LIVE"), "set LIVE=1 to hit the real public endpoint")
class LiveSend(unittest.TestCase):
    def test_real_send_decision_separates_good_and_bad_matches(self):
        ws = workspace(None)
        # Must be NEW to him: an article about the thing he already builds on is correctly a HOLD (new_to_them ~0.13).
        good = run(ws, "send", "--article", "SemIf: run Jev-style typed decisions fully in the browser with WebGPU, no server (GitHub, released this week)",
                   "--person", "Aditya: ML engineer on my hackathon team, building the Floodgate Chrome extension, which currently needs my laptop as a server",
                   "--why", "it could let the extension run the model without my laptop")
        bad = run(ws, "send", "--article", "Top 10 celebrity wedding dresses of 2026",
                  "--person", "Aditya: ML engineer on my hackathon team, building the Floodgate extension on Open-Jev")
        self.assertEqual(good.returncode, 0, good.stderr); self.assertEqual(bad.returncode, 0, bad.stderr)
        self.assertIn("SEND", good.stdout); self.assertNotIn("DON'T SEND", good.stdout)
        self.assertIn("DON'T SEND", bad.stdout)

    def test_already_seen_article_is_held_not_sent(self):
        ws = workspace(None)
        r = run(ws, "send", "--article", "Open-Jev: typed, calibrated decisions from open models (GitHub)",
                "--person", "Aditya: ML engineer on my hackathon team, building the Floodgate extension on Open-Jev")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("HOLD", r.stdout)


if __name__ == "__main__":
    unittest.main()
