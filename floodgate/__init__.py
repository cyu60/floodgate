"""Floodgate: an open Jev on River AI. Shared config."""
import os
from pathlib import Path


def _load_env():
    """Load KEY=VALUE lines from the repo's .env without overriding the shell environment."""
    f = Path(__file__).resolve().parent.parent / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


_load_env()

BASE_MODEL = os.environ.get("RIVER_BASE_MODEL", "Qwen/Qwen3.6-35B-A3B-FP8")
SMALL_MODEL = "Qwen/Qwen3.5-9B"
NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}


def client():
    """River client from RIVER_API_KEY."""
    import river_client as river

    key = os.environ.get("RIVER_API_KEY")
    if not key:
        raise SystemExit("RIVER_API_KEY not set. export RIVER_API_KEY=rv_...")
    return river.Client(api_key=key)
