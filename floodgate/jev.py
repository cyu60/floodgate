"""Real Jev (TypeSafe /v1/systemone) client: the baseline to beat and the teacher for labels.

  python -m floodgate.jev "state text" "question"     # one noul
Needs TYPESAFE_API_KEY (repo .env or shell).
"""
import json
import os
import sys
import urllib.request

URL = "https://api.typesafe.ai/v1/systemone"


def ask(state, questions: dict, model: str = "jev-latest", timeout: float = 30) -> dict:
    key = os.environ.get("TYPESAFE_API_KEY")
    if not key:
        raise SystemExit("TYPESAFE_API_KEY not set")
    req = urllib.request.Request(URL, data=json.dumps({"model": model, "state": state, "questions": questions}).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


if __name__ == "__main__":
    import floodgate  # noqa: F401  (loads .env)
    print(json.dumps(ask(sys.argv[1], {"q": {"type": "noul", "instructions": sys.argv[2]}}), indent=2))
