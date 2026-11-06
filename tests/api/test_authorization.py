"""Role authorization tests for same-tenant invoice operations."""
from datetime import date, timedelta

import pytest

from tests.conftest import make_draft


def _assert_forbidden(response):
    assert response.status_code == 403
    assert response.json()["code"] == "forbidden"


@pytest.mark.parametrize(
    ("action", "initial_status", "allowed_roles"),
    (
        pytest.param("approve", "submitted", {"admin", "manager"}, id="approve"),
        pytest.param("reject", "submitted", {"admin", "manager"}, id="reject"),
        pytest.param("pay", "approved", {"admin", "manager"}, id="pay"),
    ),
)
@pytest.mark.parametrize("role", ("admin", "manager", "staff"))
def test_approval_rejection_and_payment_roles(
    api_client, action, initial_status, allowed_roles, role
):
    actor_client, actor_headers = api_client(role)
    owner_client, owner_headers = api_client("staff")
    invoice = make_draft(owner_client, owner_headers)

    submitted = owner_client.post(f"/invoices/{invoice['id']}/submit", headers=owner_headers)
    assert submitted.status_code == 200
    if initial_status == "approved":
        manager_client, manager_headers = api_client("manager")
        approved = manager_client.post(
            f"/invoices/{invoice['id']}/approve", headers=manager_headers
        )
        assert approved.status_code == 200

    response = actor_client.post(
        f"/invoices/{invoice['id']}/{action}", headers=actor_headers
    )

    if role in allowed_roles:
        assert response.status_code == 200, response.text
        expected_status = {
            "approve": "approved",
            "reject": "rejected",
            "pay": "paid",
        }[action]
        assert response.json()["status"] == expected_status
        if action == "approve":
            assert response.json()["approved_by"] is not None
    else:
        _assert_forbidden(response)
        current = owner_client.get(f"/invoices/{invoice['id']}", headers=owner_headers)
        assert current.status_code == 200
        assert current.json()["status"] == initial_status


def test_staff_can_submit_own_draft_but_not_another_users(api_client):
    staff_client, staff_headers = api_client("staff")
    admin_client, admin_headers = api_client("admin")
    other_users_draft = make_draft(admin_client, admin_headers)
    own_draft = make_draft(staff_client, staff_headers)

    denied = staff_client.post(
        f"/invoices/{other_users_draft['id']}/submit", headers=staff_headers
    )
    _assert_forbidden(denied)
    unchanged = admin_client.get(
        f"/invoices/{other_users_draft['id']}", headers=admin_headers
    )
    assert unchanged.status_code == 200
    assert unchanged.json()["status"] == "draft"

    submitted = staff_client.post(
        f"/invoices/{own_draft['id']}/submit", headers=staff_headers
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"


@pytest.mark.parametrize(
    ("role", "owner_role", "allowed"),
    (
        pytest.param("staff", "staff", True, id="staff-edits-own-draft"),
        pytest.param("staff", "admin", False, id="staff-cannot-edit-others-draft"),
        pytest.param("manager", "staff", True, id="manager-edits-draft"),
        pytest.param("admin", "staff", True, id="admin-edits-draft"),
    ),
)
def test_draft_field_edit_permissions(api_client, role, owner_role, allowed):
    actor_client, actor_headers = api_client(role)
    owner_client, owner_headers = api_client(owner_role)
    invoice = make_draft(owner_client, owner_headers)

    response = actor_client.patch(
        f"/invoices/{invoice['id']}",
        json={"due_date": str(date.today() + timedelta(days=14))},
        headers=actor_headers,
    )

    if allowed:
        assert response.status_code == 200, response.text
        assert response.json()["due_date"] == str(date.today() + timedelta(days=14))
    else:
        _assert_forbidden(response)
        current = owner_client.get(f"/invoices/{invoice['id']}", headers=owner_headers)
        assert current.status_code == 200
        assert current.json()["due_date"] == invoice["due_date"]


@pytest.mark.parametrize(
    ("role", "owner_role", "allowed"),
    (
        pytest.param("staff", "staff", True, id="staff-voids-own-draft"),
        pytest.param("staff", "admin", False, id="staff-cannot-void-others-draft"),
        pytest.param("manager", "staff", True, id="manager-voids-draft"),
        pytest.param("admin", "staff", True, id="admin-voids-draft"),
    ),
)
def test_draft_void_permissions(api_client, role, owner_role, allowed):
    actor_client, actor_headers = api_client(role)
    owner_client, owner_headers = api_client(owner_role)
    invoice = make_draft(owner_client, owner_headers)

    response = actor_client.post(
        f"/invoices/{invoice['id']}/void", headers=actor_headers
    )

    if allowed:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "void"
    else:
        _assert_forbidden(response)
        current = owner_client.get(f"/invoices/{invoice['id']}", headers=owner_headers)
        assert current.status_code == 200
        assert current.json()["status"] == "draft"


@pytest.mark.parametrize(
    ("role", "allowed"),
    (
        pytest.param("admin", True, id="admin-voids-approved"),
        pytest.param("manager", False, id="manager-cannot-void-approved"),
        pytest.param("staff", False, id="staff-cannot-void-approved"),
    ),
)
def test_only_admin_can_void_approved_invoice(api_client, role, allowed):
    staff_client, staff_headers = api_client("staff")
    manager_client, manager_headers = api_client("manager")
    invoice = make_draft(staff_client, staff_headers)
    assert staff_client.post(
        f"/invoices/{invoice['id']}/submit", headers=staff_headers
    ).status_code == 200
    assert manager_client.post(
        f"/invoices/{invoice['id']}/approve", headers=manager_headers
    ).status_code == 200

    actor_client, actor_headers = api_client(role)
    response = actor_client.post(
        f"/invoices/{invoice['id']}/void", headers=actor_headers
    )

    if allowed:
        assert response.status_code == 200, response.text
        assert response.json()["status"] == "void"
    else:
        _assert_forbidden(response)
        current = staff_client.get(f"/invoices/{invoice['id']}", headers=staff_headers)
        assert current.status_code == 200
        assert current.json()["status"] == "approved"


@pytest.mark.parametrize("role", ("admin", "manager", "staff"))
def test_invoice_fields_cannot_be_edited_after_submission(api_client, role):
    staff_client, staff_headers = api_client("staff")
    invoice = make_draft(staff_client, staff_headers)
    submitted = staff_client.post(
        f"/invoices/{invoice['id']}/submit", headers=staff_headers
    )
    assert submitted.status_code == 200
    actor_client, actor_headers = api_client(role)

    response = actor_client.patch(
        f"/invoices/{invoice['id']}",
        json={"due_date": str(date.today() + timedelta(days=14))},
        headers=actor_headers,
    )

    _assert_forbidden(response)
    current = staff_client.get(f"/invoices/{invoice['id']}", headers=staff_headers)
    assert current.status_code == 200
    assert current.json()["due_date"] == invoice["due_date"]
    assert current.json()["status"] == "submitted"
