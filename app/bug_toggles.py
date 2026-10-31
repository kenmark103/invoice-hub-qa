"""Bug toggles: each Week-0 bug is an isolated branch guarded by its ID.

Read `ACTIVE_BUGS` (comma-separated IDs) from the environment on every call,
so tests can flip bugs with monkeypatch with no reload. Default: none active.
The answer key lives in docs/bug-register.md (do not read until after testing).
"""
import os


def active_bugs() -> set:
    raw = os.getenv("ACTIVE_BUGS", "")
    return {b.strip() for b in raw.split(",") if b.strip()}


def is_active(bug_id: str) -> bool:
    return bug_id in active_bugs()
