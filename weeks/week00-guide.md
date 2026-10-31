# Week 00 — scaffold guide

Goal: `docker compose up` → `/health` 200, seed works, `make test` green with no bugs active.

1. `pip install -r requirements.txt`
2. `docker compose up --build` (or `uvicorn app.main:app` for SQLite-local)
3. `python scripts/seed.py` → log in at `/ui/` as `admin@acme.test` / `Passw0rd!`
4. `python -m pytest` → 27 passed, 1 skipped (browser test needs `playwright install chromium`)
5. Import `postman/collection.json` into Postman; login request stores the token.
6. Week 1: fill `docs/test-plan.md`, then hunt — `docs/bug-register.md` stays unread.
