"""Smoke test: is the server up, and which base models can this key use?

Verified 2026-09-22: healthy, 13 models. Always read get_capabilities() at runtime;
the docs catalog is larger than any single key's access.
"""
from habitect_gate import client


def main():
    c = client()
    print("healthy:", c.health_check())
    for name in c.get_capabilities():
        print(" ", name)


if __name__ == "__main__":
    main()
