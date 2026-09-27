"""Sample Open-Jev's public v1.1 corpus (HF ZefanCai/Open-Jev-v1.1, CC0 + CC-BY-4.0 for WANLI) into
small stratified JSONL splits sized for a River run. Rows keep Open-Jev's schema:
{id, source, kind, state, question, options, target}.

  python -m habitect_gate.open_jev.data --train 1200 --cal 150 --test 240 --ood 120
"""
import argparse
import collections
import json
import random
from pathlib import Path

REPO = "ZefanCai/Open-Jev-v1.1"
CONFIG = "community-hard-mix-v2-redistributable"
OUT = Path(__file__).resolve().parents[2] / "data" / "openjev"


def load_split(split: str) -> list[dict]:
    import pyarrow.parquet as pq
    from huggingface_hub import hf_hub_download

    f = hf_hub_download(REPO, f"data/{CONFIG}/{split}-00000-of-00001.parquet", repo_type="dataset")
    return pq.read_table(f, columns=["id", "source", "kind", "question", "options", "target", "state_json"]).to_pylist()


def usable(r, max_options: int, max_state: int) -> bool:
    return len(r["options"]) <= max_options and len(r["state_json"]) <= max_state


def family(source: str) -> str:
    return source.split("/")[0]


def stratified(rows, n, rng, wanli_share=0.2):
    """Even across task families; WANLI (82K NLI rows) capped at wanli_share of the sample."""
    fams = collections.defaultdict(list)
    for r in rows:
        fams[family(r["source"])].append(r)
    for v in fams.values():
        rng.shuffle(v)
    picked = fams.pop("wanli-decisions-v1", [])[: int(n * wanli_share)]
    per = max(1, (n - len(picked)) // max(1, len(fams)))
    for v in fams.values():
        picked += v[:per]
    rng.shuffle(picked)
    return picked[:n]


def to_record(r) -> dict:
    return {"id": r["id"], "source": r["source"], "kind": r["kind"], "state": json.loads(r["state_json"]),
            "question": r["question"], "options": list(r["options"]), "target": [float(x) for x in r["target"]]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=1200)
    ap.add_argument("--cal", type=int, default=150)
    ap.add_argument("--test", type=int, default=240)
    ap.add_argument("--ood", type=int, default=120)
    ap.add_argument("--max-options", type=int, default=8)
    ap.add_argument("--max-state", type=int, default=2500)
    ap.add_argument("--seed", type=int, default=20260927)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    for split, name, n in (("train", "train", a.train), ("calibration", "cal", a.cal), ("test", "test", a.test), ("ood", "ood", a.ood)):
        rows = [r for r in load_split(split) if usable(r, a.max_options, a.max_state)]
        sample = [to_record(r) for r in stratified(rows, n, rng)]
        with open(OUT / f"{name}.jsonl", "w") as f:
            for rec in sample:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        kinds = collections.Counter(r["kind"] for r in sample)
        fams = len({family(r["source"]) for r in sample})
        print(f"{name:5s} {len(sample):5d} rows  {dict(kinds)}  {fams} task families")


if __name__ == "__main__":
    main()
