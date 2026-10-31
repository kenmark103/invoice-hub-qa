# InvoiceHub — system under test (16-week QA practice)

Multi-tenant invoicing SaaS built for testability: easy to run, reset, and break on purpose.

## Setup

```bash
pip install -r requirements.txt
docker compose up          # app :8010, Postgres 16  (or run locally below)
python scripts/seed.py     # deterministic seed
python -m pytest           # 27 passed, 1 skipped (browser test needs Playwright)
```

Local run without Docker: `uvicorn app.main:app --reload` (uses `invoicehub.db` SQLite).

- UI: http://localhost:8010/ui/ · API docs: http://localhost:8010/docs · health: `/health`
- `make seed` / `make reset` / `make test`

## Seed credentials (all passwords `Passw0rd!`)

| Tenant | Plan | admin | manager | staff |
| --- | --- | --- | --- | --- |
| Acme Ltd | standard | admin@acme.test | manager@acme.test | staff@acme.test (+staff1/staff2 in full seed) |
| Beta Corp | pro | admin@beta.test | … | … |
| Nuru NGO | standard | admin@nuru.test | … | … |

Full seed (`scripts/seed.py`): 3 tenants × (1 admin, 1 manager, 2 staff, 5 customers, 20 invoices across all statuses).

## Breaking it on purpose

```bash
ACTIVE_BUGS=BUG-003 python -m pytest tests/api/test_tenant_isolation_baseline.py  # watch it fail, then test it
```

IDs: `BUG-001` discount boundary · `BUG-002` per-line tax · `BUG-003` tenant leak ·
`BUG-004` staff self-approve · `BUG-005` paid→draft · `BUG-006` yesterday due date.
Default none active. Answer key: `docs/bug-register.md` (read only after testing).

`POST /test/reset` reseeds the DB but works only with `APP_ENV=test`.

## Test map (every file, what it verifies)

| File | Verifies |
| --- | --- |
| `tests/unit/test_pricing.py` | discount tiers + boundaries, pro +2% capped at 15%, 16% tax half-up at total, BUG-001/002 plantable |
| `tests/api/test_smoke.py` | `/health`, login per role, bad-password envelope, create→submit→approve happy path + totals, error-body shape |
| `tests/api/test_tenant_isolation_baseline.py` | cross-tenant read/list/write → 404 (never 403), no bugs active |
| `tests/test_bug_toggles.py` | each BUG-00x: inactive = correct, active = wrong (leak, self-approve, paid→draft, yesterday, boundary) |
| `tests/ui/test_login_smoke.py` | login page serves with form hooks; with Playwright: login → invoice table visible |
| `tests/conftest.py` | in-memory SQLite, two-tenant seed, `api_client(role)`, `tenant_a/b`, `reset_db` fixtures |

CI (`.gitlab-ci.yml`): lint → unit → api → ui (allow_failure) → report with JUnit artifacts.
