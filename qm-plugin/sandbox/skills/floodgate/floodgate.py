#!/usr/bin/env python3
"""floodgate: ask Chinat's own decision model (an open Jev trained on River) a typed question.

Run it from the agent workspace:
  python3 skills/floodgate/floodgate.py status      -> proves we're using the right things (server, token, PERSONAL model, sane answers)
  python3 skills/floodgate/floodgate.py send --article "<title / summary / url>" --person "<who they are, what they care about>" [--why "<my reason>"]
      -> SEND / HOLD / DON'T SEND with the probability behind each check (Floodgate's core decision)
  python3 skills/floodgate/floodgate.py ask "<text>" "<yes/no question>"                 -> P(yes)
  python3 skills/floodgate/floodgate.py choice "<text>" "<question>" "<opt1>" "<opt2>" ... -> probability per option
  python3 skills/floodgate/floodgate.py distraction "<page title or url>" --task "<task>"  -> P(distraction)
  add --json for the raw Jev-format response.

Endpoint + token come from FLOODGATE_URL / FLOODGATE_TOKEN if set, else from config.json next to this file.
Stdlib only.
"""
import json, os, sys, time, urllib.error, urllib.request
from pathlib import Path


def config():
    f = Path(__file__).resolve().parent / "config.json"
    return json.loads(f.read_text()) if f.exists() else {}


def model_name(checkpoint):
    return (checkpoint or "base model (untrained)").rstrip("/").split("/")[-1]


def status():
    """Check, in order: reachable, token, the expected (personal) model, and a known answer. Exit 1 on any FAIL."""
    url, token = settings()
    expect = config().get("expect_model", "floodgate-personal-v1")
    ok = True
    def line(good, what, detail):
        nonlocal ok
        ok = ok and good
        print(f"{'OK  ' if good else 'FAIL'}  {what:9s} {detail}")
    try:
        with urllib.request.urlopen(urllib.request.Request(url + "/", headers={"ngrok-skip-browser-warning": "1"}), timeout=30) as r:
            info = json.loads(r.read())
        ck = (info.get("models") or [{}])[0].get("checkpoint")
        line(True, "reachable", url)
    except Exception as e:
        line(False, "reachable", f"{url}: {e}")
        print("Floodgate is NOT usable: do not guess a verdict; say the check was skipped.")
        sys.exit(1)
    try:
        req = urllib.request.Request(url + "/v1/systemone", data=json.dumps({"state": "ping", "questions": {"q": {"type": "noul", "instructions": "Is this a ping?"}}}).encode(),
                                     headers={"Content-Type": "application/json", "Authorization": "Bearer " + token, "ngrok-skip-browser-warning": "1"})
        urllib.request.urlopen(req, timeout=60).read()
        line(True, "token", "accepted")
    except urllib.error.HTTPError as e:
        line(False, "token", f"rejected ({e.code})")
    except Exception as e:
        line(False, "token", f"probe failed: {e}")
    name = model_name(ck)
    line(name == expect, "model", name if name == expect else f"WRONG MODEL: serving {name}, expected {expect}")
    if ok:
        out = call({"article": "Top 10 celebrity wedding dresses of 2026", "person": "An ML engineer building a Chrome extension for a hackathon"},
                   {k: {"type": "noul", "instructions": q} for k, q in SEND_QUESTIONS.items()})
        v = send_verdict({k: out["answers"][k]["noul"] for k in SEND_QUESTIONS})
        line(v == "DON'T SEND", "sanity", f"celebrity gossip -> {v} (expected DON'T SEND)")
    print("Floodgate is ready." if ok else "Floodgate is NOT usable as configured: do not guess a verdict; report which check failed.")
    sys.exit(0 if ok else 1)


def settings():
    cfg = {}
    f = Path(__file__).resolve().parent / "config.json"
    if f.exists():
        cfg = json.loads(f.read_text())
    url = os.environ.get("FLOODGATE_URL") or cfg.get("url", "")
    token = os.environ.get("FLOODGATE_TOKEN") or os.environ.get("FLY_RESIDENT_ENV_FLOODGATE_TOKEN") or cfg.get("token", "")
    return url.rstrip("/"), token


def call(state, questions):
    url, token = settings()
    if not url:
        sys.exit("floodgate: no endpoint (set FLOODGATE_URL or skills/floodgate/config.json)")
    req = urllib.request.Request(url + "/v1/systemone", data=json.dumps({"state": state, "questions": questions}).encode(),
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + token,
                                          "ngrok-skip-browser-warning": "1"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        sys.exit(f"floodgate: server said {e.code}: {e.read()[:200].decode(errors='ignore')}")
    except Exception as e:
        sys.exit(f"floodgate: cannot reach {url}: {e}")


SEND_QUESTIONS = {
    "relevant": "Does this article match what this person cares about or works on?",
    "new_to_them": "Is this article likely to be new to this person, rather than something they have probably already seen?",
    "timely": "Is this article useful to this person right now, given what they are currently doing?",
    "appropriate": "Is sending this article appropriate for this relationship (not too salesy, personal, or off-tone)?",
}


def send_verdict(p):
    """Code, not the model, combines the atomic answers (Jev-style composite)."""
    if p["relevant"] < 0.4 or p["appropriate"] < 0.4:
        return "DON'T SEND"
    if all(v >= 0.6 for v in p.values()):
        return "SEND"
    return "HOLD"


def opt(argv, name):
    return argv[argv.index(name) + 1] if name in argv and argv.index(name) + 1 < len(argv) else None


def main(argv):
    raw = "--json" in argv
    argv = [a for a in argv if a != "--json"]
    if argv[:1] == ["status"]:
        status()
    if len(argv) < 2 or argv[0] not in ("send", "ask", "choice", "distraction"):
        sys.exit(__doc__)
    cmd = argv[0]
    if cmd == "send":
        article, person, why = opt(argv, "--article"), opt(argv, "--person"), opt(argv, "--why")
        if not article or not person:
            sys.exit("floodgate send: needs --article and --person")
        state = {"article": article, "person": person}
        if why:
            state["my_reason_for_sending"] = why
        out = call(state, {k: {"type": "noul", "instructions": q} for k, q in SEND_QUESTIONS.items()})
        p = {k: out["answers"][k]["noul"] for k in SEND_QUESTIONS}
        if raw:
            print(json.dumps(out)); return
        print(f"Floodgate: {send_verdict(p)}")
        for k, v in p.items():
            print(f"  {v:.2f}  {k}")
        print(f"  model: {model_name(out.get('checkpoint'))}")
        return
    if cmd == "ask" and len(argv) >= 3:
        out = call(argv[1], {"q": {"type": "noul", "instructions": argv[2]}})
        p = out["answers"]["q"]["noul"]
        print(json.dumps(out) if raw else f"P(yes) = {p:.2f}  ->  {'YES' if p >= 0.5 else 'NO'}")
    elif cmd == "choice" and len(argv) >= 5:
        out = call(argv[1], {"q": {"type": "choice", "instructions": argv[2], "criteria": {o: None for o in argv[3:]}}})
        a = out["answers"]["q"]
        print(json.dumps(out) if raw else "\n".join(f"{p:.2f}  {k}" for k, p in sorted(a["probabilities"].items(), key=lambda x: -x[1]))
              + f"\n-> {a['choice']} (confidence {a['confidence']:.2f})")
    elif cmd == "distraction" and "--task" in argv and argv.index("--task") + 1 < len(argv):
        i = argv.index("--task")
        page, task = argv[1], argv[i + 1]
        url, title = (page, page) if page.startswith("http") else ("(unknown)", page)
        # Same text line the model was trained on: URL / Title / Time / Stated task.
        state = f"URL: {url} Title: {title}. Time: {time.strftime('%H:%M %A')}. Stated task: {task}."
        out = call(state, {"q": {"type": "noul", "instructions": "Is this page a distraction from the stated task?"}})
        p = out["answers"]["q"]["noul"]
        print(json.dumps(out) if raw else f"P(distraction) = {p:.2f}  ->  {'DISTRACTION' if p >= 0.7 else 'unsure' if p >= 0.4 else 'ON TASK'}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
