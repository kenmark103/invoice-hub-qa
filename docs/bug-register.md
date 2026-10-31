# Bug register — ANSWER KEY (do not read until after you have tested)

| ID | Description | Affected endpoint(s) | Guard in code |
| --- | --- | --- | --- |
| BUG-001 | Discount tier boundary uses `>` instead of `>=` at 2,000.00: exactly 2000.00 gets 5% instead of 10% | `POST /invoices` (totals), `PATCH` recalc | `app/pricing.py::discount_rate` |
| BUG-002 | Tax rounded per line instead of once at the total (e.g. 3×33.33-ish lines give 15.99 instead of 16.00) | `POST /invoices` (totals), `PATCH` recalc | `app/pricing.py::calc_totals` |
| BUG-003 | `GET /invoices/{id}` returns another tenant's invoice when the id exists (isolation leak) | `GET /invoices/{id}` | `app/main.py::get_invoice` |
| BUG-004 | `staff` can approve their own submitted invoice | `POST /invoices/{id}/approve` (+ PATCH status) | `app/main.py::_check_action_perm` |
| BUG-005 | Illegal transition `paid -> draft` is accepted (via PATCH status, admin) | `PATCH /invoices/{id}` | `app/services.py::check_transition` |
| BUG-006 | `due_date` accepts yesterday | `POST /invoices`, `PATCH /invoices/{id}` | `app/services.py::validate_due_date` |

Activate: `ACTIVE_BUGS=BUG-001,BUG-003` (comma-separated). Prove with `tests/test_bug_toggles.py`.
