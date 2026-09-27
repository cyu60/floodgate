"""Habitect Gate: an open Jev on River AI. Shared config."""
import os

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
