"""Invoice lifecycle transition tests."""
import pytest

from tests.conftest import make_draft


def _create_submitted(api_client):
    staff_client, staff_headers = api_client("staff")
    invoice = make_draft(staff_client, staff_headers)
    response = staff_client.post(
        f"/invoices/{invoice['id']}/submit", headers=staff_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "submitted"
    return invoice


def _create_approved(api_client):
    invoice = _create_submitted(api_client)
    manager_client, manager_headers = api_client("manager")
    response = manager_client.post(
        f"/invoices/{invoice['id']}/approve", headers=manager_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "approved"
    return invoice


def _prepare_status(api_client, target_status):
    staff_client, staff_headers = api_client("staff")
    invoice = make_draft(staff_client, staff_headers)

    if target_status == "draft":
        return invoice
    if target_status == "void":
        response = staff_client.post(
            f"/invoices/{invoice['id']}/void", headers=staff_headers
        )
        assert response.status_code == 200, response.text
        return invoice

    submitted = staff_client.post(
        f"/invoices/{invoice['id']}/submit", headers=staff_headers
    )
    assert submitted.status_code == 200, submitted.text
    if target_status == "submitted":
        return invoice
    if target_status == "rejected":
        manager_client, manager_headers = api_client("manager")
        response = manager_client.post(
            f"/invoices/{invoice['id']}/reject", headers=manager_headers
        )
        assert response.status_code == 200, response.text
        return invoice
    if target_status in ("approved", "paid"):
        manager_client, manager_headers = api_client("manager")
        response = manager_client.post(
            f"/invoices/{invoice['id']}/approve", headers=manager_headers
        )
        assert response.status_code == 200, response.text
        if target_status == "approved":
            return invoice
        response = manager_client.post(
            f"/invoices/{invoice['id']}/pay", headers=manager_headers
        )
        assert response.status_code == 200, response.text
        return invoice
    raise AssertionError(f"Unsupported setup status: {target_status}")


def test_happy_path_transitions_update_status(api_client):
    staff_client, staff_headers = api_client("staff")
    manager_client, manager_headers = api_client("manager")
    invoice = make_draft(staff_client, staff_headers)

    submitted = staff_client.post(
        f"/invoices/{invoice['id']}/submit", headers=staff_headers
    )
    assert submitted.status_code == 200, submitted.text
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["approved_by"] is None

    approved = manager_client.post(
        f"/invoices/{invoice['id']}/approve", headers=manager_headers
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    assert approved.json()["approved_by"] is not None

    response = manager_client.post(
        f"/invoices/{invoice['id']}/pay", headers=manager_headers
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "paid"
    assert response.json()["approved_by"] == approved.json()["approved_by"]


def test_submitted_invoice_can_be_rejected(api_client):
    invoice = _create_submitted(api_client)
    manager_client, manager_headers = api_client("manager")

    response = manager_client.post(
        f"/invoices/{invoice['id']}/reject", headers=manager_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "rejected"


@pytest.mark.parametrize(
    ("starting_status", "action", "actor_role", "body", "error_code"),
    (
        pytest.param("draft", "approve", "manager", None, "illegal_transition", id="draft-cannot-approve"),
        pytest.param("submitted", "pay", "manager", None, "illegal_transition", id="submitted-cannot-pay"),
        pytest.param("approved", "submit", "manager", None, "illegal_transition", id="approved-cannot-resubmit"),
        pytest.param("rejected", "submit", "staff", None, "illegal_transition", id="rejected-terminal"),
        pytest.param("void", "submit", "staff", None, "illegal_transition", id="void-terminal"),
        pytest.param("paid", "patch", "admin", {"status": "draft"}, "illegal_transition", id="paid-cannot-reopen"),
    ),
)
def test_illegal_transitions_return_conflict_and_preserve_state(
    api_client, starting_status, action, actor_role, body, error_code
):
    invoice = _prepare_status(api_client, starting_status)
    actor_client, actor_headers = api_client(actor_role)
    path = (
        f"/invoices/{invoice['id']}"
        if action == "patch"
        else f"/invoices/{invoice['id']}/{action}"
    )

    response = actor_client.request(
        "PATCH" if action == "patch" else "POST",
        path,
        json=body,
        headers=actor_headers,
    )

    assert response.status_code == 409
    assert response.json()["code"] == error_code
    owner_client, owner_headers = api_client("staff")
    current = owner_client.get(f"/invoices/{invoice['id']}", headers=owner_headers)
    assert current.status_code == 200
    assert current.json()["status"] == starting_status


def test_draft_can_be_voided(api_client):
    staff_client, staff_headers = api_client("staff")
    invoice = make_draft(staff_client, staff_headers)

    response = staff_client.post(
        f"/invoices/{invoice['id']}/void", headers=staff_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "void"


def test_approved_invoice_can_be_voided(api_client):
    invoice = _create_approved(api_client)
    admin_client, admin_headers = api_client("admin")

    response = admin_client.post(
        f"/invoices/{invoice['id']}/void", headers=admin_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "void"
    assert response.json()["approved_by"] is not None


@pytest.mark.parametrize(
    ("source_status", "target_status", "expected_status"),
    (
        pytest.param("draft", "submitted", "submitted", id="patch-submit"),
        pytest.param("submitted", "approved", "approved", id="patch-approve"),
        pytest.param("submitted", "rejected", "rejected", id="patch-reject"),
    ),
)
def test_patch_status_uses_valid_lifecycle_transitions(
    api_client, source_status, target_status, expected_status
):
    invoice = _prepare_status(api_client, source_status)
    actor_role = "staff" if target_status == "submitted" else "manager"
    client, headers = api_client(actor_role)

    response = client.patch(
        f"/invoices/{invoice['id']}",
        json={"status": target_status},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["status"] == expected_status
    if target_status == "approved":
        assert response.json()["approved_by"] is not None
