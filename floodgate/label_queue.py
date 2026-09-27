"""Floodgate label queue: the AMBIGUOUS visits the seed rules cannot judge, one card per URL.

Seed rules (prep_gate_dataset) only know ~15 domains. Everything else — google searches, Wikipedia,
YouTube titles that might be lectures, vercel previews, blogs, course sites — is where the model
has to learn the user's judgment rather than a domain list. This builds that queue for tools/label.html.

  python -m floodgate.label_queue                    # -> data/label_queue.json (ambiguous only)
  python -m floodgate.label_queue --include-known    # also sample rule-labelled domains for checking
  python -m floodgate.label_queue --merge            # hand labels override seed rows -> data/gate_train.jsonl

Buckets (label these in order — each is a different kind of ambiguity):
  unknown   domain the rules have never seen (largest bucket, highest value)
  content   YouTube / Wikipedia / Reddit / X — the TITLE decides, not the domain
  search    google.com queries — the query text decides
  known     rule-labelled, sampled only with --include-known (sanity check of the rules)
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from floodgate.prep_gate_dataset import HISTORY, OUT, QUESTION, domain, load_visits, seed_label

CONTENT = {"youtube.com", "m.youtube.com", "en.wikipedia.org", "reddit.com", "x.com", "twitter.com"}
SKIP = {"", "accounts.google.com", "localhost", "127.0.0.1", "newtab", "chrome", "chrome-extension", "about"}
SKIP_TITLES = {"New Tab", "Untitled", "Sign in - Google Accounts", "Sign in", "Loading..."}


def bucket(dom: str, url: str) -> str:
    if dom == "google.com" and "/search" in url:
        return "search"
    if dom in CONTENT or any(dom.endswith("." + d) for d in CONTENT):
        return "content"
    if seed_label(dom, 12, "") is None:
        return "unknown"
    return "known"


def canonical(url: str, dom: str) -> str:
    url = url.split("#")[0]
    if dom == "google.com" and "/search" in url:
        q = parse_qs(urlparse(url).query).get("q", [""])[0]
        return f"https://www.google.com/search?q={q}"
    if "youtube.com" in dom and "watch" in url:
        v = parse_qs(urlparse(url).query).get("v", [""])[0]
        return f"https://www.youtube.com/watch?v={v}"
    return url[:200]


def build(a):
    groups: dict[str, dict] = {}
    for url, title, t in load_visits(HISTORY):
        dom = domain(url)
        scheme = urlparse(url).scheme
        if dom in SKIP or scheme not in ("http", "https") or title.strip() in SKIP_TITLES:
            continue
        if dom == "google.com" and urlparse(url).path in ("", "/"):  # bare homepage, title is stale
            continue
        b = bucket(dom, url)
        if b == "known" and not a.include_known:
            continue
        key = canonical(url, dom)
        g = groups.setdefault(key, {"id": key, "url": key, "domain": dom, "bucket": b, "visits": 0, "hours": [0] * 24, "first": t.isoformat(timespec="minutes")})
        g["visits"] += 1
        g["hours"][t.hour] += 1
        g["title"] = title[:140]  # latest title wins
        g["last"] = t.isoformat(timespec="minutes")
        g["seed"] = seed_label(dom, t.hour, title)

    per_domain: dict[tuple, list] = defaultdict(list)  # (domain, bucket) -> cards, most visited first
    for g in sorted(groups.values(), key=lambda g: -g["visits"]):
        per_domain[(g["domain"], g["bucket"])].append(g)
    order = {"unknown": 0, "content": 1, "search": 2, "known": 3}
    items = []
    for (dom, b), gs in per_domain.items():
        cap = a.per_domain if b != "known" else a.known_sample
        dom_visits = sum(g["visits"] for g in gs)
        for g in gs[:cap]:
            g["domain_total"], g["domain_visits"] = len(gs), dom_visits
            items.append(g)
    items.sort(key=lambda g: (order[g["bucket"]], -g["domain_visits"], -g["visits"]))
    domain_counts = {d: len(gs) for (d, _), gs in per_domain.items()}
    out = {"question": QUESTION, "stated_tasks": a.tasks, "items": items, "domains": domain_counts}
    OUT.mkdir(exist_ok=True)
    (OUT / "label_queue.json").write_text(json.dumps(out, ensure_ascii=False))
    from collections import Counter
    c = Counter(g["bucket"] for g in items)
    print(f"{len(groups)} unique URLs -> {len(items)} cards: {dict(c)}  ({len(per_domain)} domains) -> data/label_queue.json")


def merge(a):
    hand = [json.loads(l) for l in (OUT / "gate_labels.jsonl").read_text().splitlines() if l.strip()]
    hand_urls = {r["metadata"]["url"] for r in hand}
    hand_domains = {r["metadata"]["domain"] for r in hand if r["metadata"].get("scope") == "domain"}
    seed = [json.loads(l) for l in (OUT / "gate_rows.jsonl").read_text().splitlines() if l.strip()]
    kept = [r for r in seed if r["metadata"]["domain"] not in hand_domains and r["state"].split(" Title:")[0][5:] not in hand_urls]
    rows = hand + kept
    with open(OUT / "gate_train.jsonl", "w") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"{len(hand)} hand rows + {len(kept)} seed rows (dropped {len(seed) - len(kept)} overridden) -> data/gate_train.jsonl")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--include-known", action="store_true")
    ap.add_argument("--per-domain", type=int, default=20, help="max cards per ambiguous domain (label the rest with a domain-wide label in the UI)")
    ap.add_argument("--known-sample", type=int, default=5)
    ap.add_argument("--tasks", nargs="+", default=["deep work on the current project", "prep the River dataset script", "build Floodgate at the River hackathon", "rest / evening wind-down"])
    a = ap.parse_args()
    merge(a) if a.merge else build(a)


if __name__ == "__main__":
    main()
