"""One chat completion against a base model, with thinking mode OFF.

Gotcha (verified 2026-09-22): Qwen reasoning models spend the whole max_tokens budget
inside <think> by default. Passing chat_template_kwargs={"enable_thinking": False}
through chat_complete's kwargs fixes it (1 completion token for "pong").

Usage: python -m habitect_gate.chat "your prompt" [--think]
"""
import argparse
import json

from habitect_gate import BASE_MODEL, NO_THINK, client


def ask(prompt: str, base_model: str = BASE_MODEL, think: bool = False, max_tokens: int = 400) -> dict:
    c = client()
    kwargs = {} if think else NO_THINK
    r = c.chat_complete(
        [{"role": "user", "content": prompt}], base_model=base_model, max_tokens=max_tokens, **kwargs
    )
    body = r.response_json
    if isinstance(body, str):
        body = json.loads(body)
    return body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prompt")
    ap.add_argument("--base", default=BASE_MODEL)
    ap.add_argument("--think", action="store_true", help="leave reasoning mode on")
    ap.add_argument("--max-tokens", type=int, default=400)
    a = ap.parse_args()
    body = ask(a.prompt, a.base, a.think, a.max_tokens)
    msg = body["choices"][0]["message"]
    if msg.get("reasoning_content"):
        print("[reasoning]", msg["reasoning_content"][:500], "\n")
    print(msg.get("content"))
    print("\nusage:", body.get("usage"))


if __name__ == "__main__":
    main()
