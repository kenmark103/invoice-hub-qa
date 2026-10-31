"""Bug toggles: each ID, when active, makes its targeted behaviour wrong;
when inactive, behaviour stays correct. Proves every Week-0 bug is plantable."""
from datetime import date, timedelta

import pytest

from tests.conftest import make_draft

LINES_2000 = [{"description": "Boundary box", "qty": 2, "unit_price": "1000.00"}]


def _full_path_to_paid(c, h):
    inv = make_draft(c, h)
    c.post(f"/invoices/{inv['id']}/submit", headers=h)
    return inv


def test_bug003_inactive_stays_404(api_client, b_client, monkeypatch):
    # Arrange — bug explicitly off
    monkeypatch.setenv("ACTIVE_BUGS", "")
    a_c, a_h = api_client("staff")
    inv = make_draft(a_c, a_h)
    b_c, b_h = b_client
    # Act
    r = b_c.get(f"/invoices/{inv['id']}", headers=b_h)
    # Assert — correct isolation
    assert r.status_code == 404


def test_bug003_active_leaks_other_tenant(api_client, b_client, monkeypatch):
    # Arrange — leak toggle on
    monkeypatch.setenv("ACTIVE_BUGS", "BUG-003")
    a_c, a_h = api_client("staff")
    inv = make_draft(a_c, a_h)
    b_c, b_h = b_client
    # Act
    r = b_c.get(f"/invoices/{inv['id']}", headers=b_h)
    # Assert — wrong: tenant B sees tenant A's invoice
    assert r.status_code == 200
    assert r.json()["id"] == inv["id"]


def test_bug004_inactive_staff_cannot_approve(api_client, monkeypatch):
    # Arrange
    monkeypatch.setenv("ACTIVE_BUGS", "")
    c, h = api_client("staff")
    inv = make_draft(c, h)
    c.post(f"/invoices/{inv['id']}/submit", headers=h)
    # Act — staff tries to approve their own submitted invoice
    r = c.post(f"/invoices/{inv['id']}/approve", headers=h)
    # Assert — correctly forbidden
    assert r.status_code == 403


def test_bug004_active_staff_approves_own(api_client, monkeypatch):
    # Arrange
    monkeypatch.setenv("ACTIVE_BUGS", "BUG-004")
    c, h = api_client("staff")
    inv = make_draft(c, h)
    c.post(f"/invoices/{inv['id']}/submit", headers=h)
    # Act
    r = c.post(f"/invoices/{inv['id']}/approve", headers=h)
    # Assert — wrong: staff approved their own invoice
    assert r.status_code == 200
    assert r.json()["status"] == "approved"


def test_bug005_inactive_paid_to_draft_rejected(api_client, monkeypatch):
    # Arrange — invoice walked all the way to paid (staff->manager->pay)
    monkeypatch.setenv("ACTIVE_BUGS", "")
    staff_c, staff_h = api_client("staff")
    mgr_c, mgr_h = api_client("manager")
    inv = _full_path_to_paid(staff_c, staff_h)
    mgr_c.post(f"/invoices/{inv['id']}/approve", headers=mgr_h)
    mgr_c.post(f"/invoices/{inv['id']}/pay", headers=mgr_h)
    admin_c, admin_h = api_client("admin")
    # Act — even admin tries to reopen paid -> draft
    r = admin_c.patch(f"/invoices/{inv['id']}", json={"status": "draft"}, headers=admin_h)
    # Assert — correctly rejected as illegal transition
    assert r.status_code == 409
    assert r.json()["code"] == "illegal_transition"


def test_bug005_active_paid_to_draft_accepted(api_client, monkeypatch):
    # Arrange — same walk to paid, bug on
    monkeypatch.setenv("ACTIVE_BUGS", "BUG-005")
    staff_c, staff_h = api_client("staff")
    mgr_c, mgr_h = api_client("manager")
    inv = _full_path_to_paid(staff_c, staff_h)
    mgr_c.post(f"/invoices/{inv['id']}/approve", headers=mgr_h)
    mgr_c.post(f"/invoices/{inv['id']}/pay", headers=mgr_h)
    admin_c, admin_h = api_client("admin")
    # Act
    r = admin_c.patch(f"/invoices/{inv['id']}", json={"status": "draft"}, headers=admin_h)
    # Assert — wrong: paid invoice reopened to draft
    assert r.status_code == 200
    assert r.json()["status"] == "draft"


def test_bug006_inactive_yesterday_rejected(api_client, monkeypatch):
    # Arrange
    monkeypatch.setenv("ACTIVE_BUGS", "")
    c, h = api_client("staff")
    # Act — due_date yesterday
    r = c.post(
        "/invoices",
        json={"customer_id": 1, "due_date": str(date.today() - timedelta(days=1)),
              "lines": [{"description": "x", "qty": 1, "unit_price": "100.00"}]},
        headers=h,
    )
    # Assert — correctly rejected
    assert r.status_code == 422


def test_bug006_active_yesterday_accepted(api_client, monkeypatch):
    # Arrange
    monkeypatch.setenv("ACTIVE_BUGS", "BUG-006")
    c, h = api_client("staff")
    # Act
    r = c.post(
        "/invoices",
        json={"customer_id": 1, "due_date": str(date.today() - timedelta(days=1)),
              "lines": [{"description": "x", "qty": 1, "unit_price": "100.00"}]},
        headers=h,
    )
    # Assert — wrong: yesterday accepted
    assert r.status_code == 201


@pytest.mark.parametrize("subtotal,expected", [("500", "5"), ("2000", "10"), ("10000", "15")])
def test_bug001_inactive_boundaries_correct(api_client, monkeypatch, subtotal, expected):
    # Arrange — bug off, invoice at an exact tier boundary
    monkeypatch.setenv("ACTIVE_BUGS", "")
    c, h = api_client("staff")
    qty = 2 if subtotal in ("500", "2000") else 1
    price = str(float(subtotal) / qty)
    # Act
    r = c.post("/invoices", json={
        "customer_id": 1, "due_date": str(date.today() + timedelta(days=7)),
        "lines": [{"description": "boundary", "qty": qty, "unit_price": price}]}, headers=h)
    # Assert — correct tier
    assert r.status_code == 201, r.text
    assert str(float(r.json()["discount_rate"])) == expected or r.json()["discount_rate"] == float(expected)
