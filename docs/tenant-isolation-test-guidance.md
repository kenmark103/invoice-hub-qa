# Tenant isolation API test guidance

This document describes the API's tenant boundary, implemented pytest coverage,
and focused next steps for extending the suite.

## Current coverage and contract

The tests in `tests/api/test_tenant_isolation_baseline.py` cover:

- Foreign and nonexistent invoice IDs both return `404 not_found`.
- Invoice and customer lists contain exactly the requesting tenant's records.
- Tenant B cannot GET or mutate Tenant A's invoice; parametrized mutation cases
  include PATCH and all lifecycle action routes.
- The owner can still read an invoice unchanged after a denied foreign
  mutation.
- A tenant cannot create an invoice for another tenant's customer or reassign
  an existing invoice to that customer.

The Postman tenant-isolation folder adds a useful sequence: create as Tenant A,
attempt a foreign GET and submit as Tenant B, then GET again as Tenant A to
confirm the invoice is still a draft. The pytest suite should keep this coverage
independent per test rather than requiring Postman-style request ordering.

The application currently scopes invoice lists by the authenticated user's
`tenant_id`. Invoice reads, PATCH requests, and lifecycle actions use a
tenant-scoped lookup that returns `404 not_found` when the invoice is absent or
belongs to another tenant. Invoice creation and customer replacement also
require the customer to belong to the caller's tenant. The intended behavior is
to conceal whether a foreign resource exists: a foreign ID should look like a
missing ID, not return `403`.

Tenant isolation is separate from same-tenant role authorization. A staff
member's forbidden action on a same-tenant invoice is an authorization
expectation (`403`); a different tenant's admin still gets `404` for that same
invoice. Keep those concerns in separate tests/specifications.

## Test data and fixture plan

### Keep the seed small and explicit

The existing `seed_minimal` seed is a good starting point: two tenants, three
Tenant A roles, one Tenant B admin, and one customer per tenant. Use IDs
returned by the seed (or query them through a fixture) rather than assuming
customer IDs are `1` and `2`; tests should not depend on database insertion
order.

The `seeded_ids` fixture exposes tenant/customer IDs by name, depends on the
existing function-scoped `db` fixture, and reuses its seed without resetting
or reseeding the database. The tests use these IDs instead of assuming
customer insertion order. `api_client(role)` and `b_client` remain compatible
with existing tests. If the suite needs to prove the boundary for more than
Tenant B's admin, extend the Tenant B seed and add a role-selectable tenant-B
client; do not make every isolation test run against every role by default.

Use the existing `make_draft` helper to create invoices through the API. Pass
an explicit customer ID from the fixture, and use dates relative to
`date.today()` (for example, today plus seven days) so test data stays within
the due-date policy. For list tests, create at least one invoice through each
tenant's authenticated client.

`make_draft` uses its default lines only when `lines is None`; explicitly
passing an empty list is preserved so validation tests can exercise that input.

### Fixture responsibilities

| Fixture/helper | Responsibility | Guidance |
| --- | --- | --- |
| `db` | Fresh in-memory database and seed per test | Keep function scope so each test owns isolated state. |
| `seeded_ids` | Stable IDs for both tenants and their customers | Use named keys; avoid magic IDs and a second seed. |
| `client` | Unauthenticated `TestClient` | Use for login and unauthenticated API cases. |
| `api_client(role)` | Tenant A client and bearer headers | Continue using for admin/manager/staff cases. |
| `b_client` | Tenant B admin client and bearer headers | Sufficient for initial cross-tenant checks; admin is a strong boundary check. |
| `make_draft` | Create a valid invoice via the API | Allow explicit `customer_id`, `lines`, and due date; only default when omitted. |

Prefer HTTP helpers for creating test state instead of inserting invoices
directly through SQLAlchemy. This keeps the test setup subject to the same API
contract as a real user and produces realistic line items and totals.

## Implemented and next pytest cases

The first six cases below are implemented. The same invariant is parametrized
across values/endpoints where doing so keeps setup and assertions clear.

| Case | Setup and request | Assertions |
| --- | --- | --- |
| Foreign vs missing invoice GET | Tenant B requests a Tenant A invoice ID or a nonexistent ID. | Both return `404`, `not_found`, and the standard error keys; don't require identical message text. |
| Tenant-scoped invoice list | Create one invoice in each tenant; list as each tenant. | `200`; each `total` and exact ID set contains only that tenant's invoice. |
| Tenant-scoped customer list | List customers as each tenant. | `200`; each exact ID set contains only the seeded customer for that tenant. |
| Foreign invoice mutations | Tenant B attempts PATCH and each lifecycle route on Tenant A's draft. | Every request returns `404` / `not_found`; Tenant A's invoice snapshot remains unchanged. |
| Foreign customer on create | Tenant A creates an invoice using Tenant B's customer ID. | `404` / `not_found`; Tenant A's invoice IDs do not change. |
| Foreign customer on PATCH | Tenant A assigns Tenant B's customer to its draft. | `404` / `not_found`; the invoice snapshot remains unchanged. |
| Same-tenant role authorization (next) | A role attempts an action it is not allowed to perform on a same-tenant invoice. | Assert the specific authorization status/code (normally `403`); implement in `test_authorization.py`. |
| Unauthenticated access (next) | No bearer token is supplied to a protected endpoint. | Assert the auth contract (`401` and its documented error body); do not characterize it as a tenant-isolation failure. |

### Parametrization suggestions

Use a case table with readable IDs so failures say which boundary failed:

- For foreign invoice mutation, parameterize request method/path/body, starting
  with PATCH (`{"status": "submitted"}`) and the lifecycle routes (submit,
  approve, reject, void, and pay). Each case verifies the tenant guard runs
  before role or lifecycle-state checks.
- For resource lookup, parameterize a foreign ID and a nonexistent ID, while
  keeping the expected public result the same (`404`, `not_found`).
- For list filtering, test a small set of explicit ownership layouts (A-only,
  B-only, one invoice each) if those layouts reveal distinct regressions. Avoid
  a Cartesian product of roles, routes, statuses, and data if the assertion is
  identical.
- For customer ownership, parameterize create versus patch only if the setup
  and expected side-effect checks remain clear; separate tests are often easier
  to diagnose because their request and postcondition differ.

Every parametrized case should have a descriptive `ids=` value, and each case
should create its own data inside the test. Do not share an invoice across
tests or depend on test execution order.

## What to compare after a denied mutation

Status alone proves only that the request was rejected. To prove no
cross-tenant side effect occurred:

1. Capture the invoice as Tenant A before Tenant B's attempt.
2. Make the denied request as Tenant B.
3. GET the same invoice as Tenant A.
4. Compare a stable projection of the before/after response:
   `id`, `tenant_id`, `customer_id`, `status`, `due_date`, `lines`, and pricing
   fields (`subtotal`, `discount_rate`, `discount_amount`, `tax`, `total`).
5. Also assert Tenant B still cannot GET the invoice.

For line comparison, compare the line fields (`description`, `qty`,
`unit_price`) rather than relying on database row ordering or generated line
IDs. For a failed create using a foreign customer, compare Tenant A's list IDs
before and after; assert no new invoice was created.

For list isolation, do not assert only `total == 0`: that misses a leak if the
foreign invoice appears alongside a tenant-owned invoice. Use one or more
invoices per tenant and assert exact ID sets and totals.

## Organization and implementation order

1. Keep `test_tenant_isolation_baseline.py` focused on cross-tenant visibility
   and mutations; use `test_authorization.py` for same-tenant role rules.
2. Consider adding a role-selectable Tenant B client only if Tenant B's other
   roles need separate boundary coverage; the current Tenant B admin exercises
   the tenant guard independently from staff permissions.
3. Add more tenant-owned rows to list tests if pagination/filtering coverage is
   added, while continuing to assert exact IDs.
4. Run the focused isolation and authorization modules, then the full test
   suite to catch fixture interactions.

The API test files `test_authorization.py`, `test_price.py`,
`test_validation.py`, and `test_workflow.py` may serve as future module
boundaries; keep tenant isolation cases out of pricing/workflow tests unless a
specific behavior genuinely crosses those concerns.

## Related context

- Current pytest fixtures and helpers: [../tests/conftest.py](../tests/conftest.py)
- Existing tenant-isolation baseline: [../tests/api/test_tenant_isolation_baseline.py](../tests/api/test_tenant_isolation_baseline.py)
- API route behavior: [../app/main.py](../app/main.py)
- Postman tenant-isolation scenario: [../postman/collections/InvoiceHub%20API%20Tests/5%20-%20Tenant%20Isolation](../postman/collections/InvoiceHub%20API%20Tests/5%20-%20Tenant%20Isolation)
