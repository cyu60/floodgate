"""Habitect Gate dataset: Chrome history -> noul rows "Is this page a distraction from the stated task?"

Reads the local Chrome History SQLite (copied first; Chrome locks the live file) and emits
Open-Jev-style rows: {state, question, kind: "noul", options: ["no","yes"], target: [1-p, p]}.

Labels are SEED labels from domain rules + hour-of-day, meant to be overwritten by a teacher
(Jev via the MentorMates proxy once it is live, or Claude) and by your own corrections in
gbrain. Rule labels alone will teach the model your rules, not your judgment.

  python -m habitect_gate.prep_gate_dataset --stated-task "deep work"     # writes data/gate_rows.jsonl
  python -m habitect_gate.prep_gate_dataset --stats                        # domain histogram only
"""
import argparse
import json
import random
import shutil
import sqlite3
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

HISTORY = Path.home() / "Library/Application Support/Google/Chrome/Default/History"
OUT = Path(__file__).resolve().parent.parent / "data"
QUESTION = "Is this page a distraction from the stated task?"

DISTRACTION = {"youtube.com", "m.youtube.com", "reddit.com", "x.com", "twitter.com", "instagram.com", "netflix.com", "tiktok.com", "twitch.tv", "9gag.com"}  # add your own
WORK = {"github.com", "docs.google.com", "mail.google.com", "calendar.google.com", "notion.so", "vercel.com", "docs.river.ai", "river.ai", "docs.typesafe.ai", "linkedin.com", "huggingface.co", "arxiv.org", "localhost", "127.0.0.1"}  # add your own


def domain(url: str) -> str:
    d = urlparse(url).netloc.lower()
    return d[4:] if d.startswith("www.") else d


def seed_label(dom: str, hour: int, title: str) -> float | None:
    """Return P(distraction) or None when the rules do not know."""
    if dom in DISTRACTION or any(dom.endswith("." + d) for d in DISTRACTION):
        # a Fireship/lecture video at 14:00 is ambiguous; late night is not
        return 0.95 if hour >= 22 or hour < 7 else 0.8
    if dom in WORK or any(dom.endswith("." + d) for d in WORK) or dom.startswith("file"):
        return 0.1 if 7 <= hour < 22 else 0.3
    return None


def load_visits(db: Path):
    tmp = Path(tempfile.mkdtemp()) / "History"
    shutil.copy2(db, tmp)
    con = sqlite3.connect(tmp)
    q = """select u.url, u.title, v.visit_time from visits v join urls u on u.id = v.url
           where u.title is not null and u.title != '' order by v.visit_time"""
    epoch = datetime(1601, 1, 1)
    for url, title, vt in con.execute(q):
        yield url, title, epoch + timedelta(microseconds=vt)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stated-task", default="deep work on the current project")
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--max-rows", type=int, default=3000)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    visits = list(load_visits(HISTORY))
    if a.stats:
        from collections import Counter
        c = Counter(domain(u) for u, _, _ in visits)
        for d, n in c.most_common(30):
            print(f"{n:6d}  {d}  seed={seed_label(d, 12, '')}")
        return

    rows, unknown = [], 0
    for url, title, t in visits:
        dom = domain(url)
        p = seed_label(dom, t.hour, title)
        if p is None:
            unknown += 1
            continue
        state = f"URL: {url[:200]} Title: {title[:120]}. Time: {t:%H:%M %A}. Stated task: {a.stated_task}."
        rows.append({"state": state, "question": QUESTION, "kind": "noul", "options": ["no", "yes"], "target": [round(1 - p, 3), round(p, 3)], "metadata": {"domain": dom, "target_basis": "seed-rule", "visited": t.isoformat()}})
    random.Random(a.seed).shuffle(rows)
    rows = rows[: a.max_rows]
    OUT.mkdir(exist_ok=True)
    with open(OUT / "gate_rows.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    pos = sum(r["target"][1] >= 0.5 for r in rows)
    print(f"{len(visits)} visits -> {len(rows)} labelled rows ({pos} distraction / {len(rows) - pos} work), {unknown} unlabelled by rules -> data/gate_rows.jsonl")


if __name__ == "__main__":
    main()
