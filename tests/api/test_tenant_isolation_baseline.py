"""Tenant boundary tests: foreign resources are hidden and cannot be changed."""
from datetime import date, timedelta

import pytest

from tests.conftest import make_draft


def _assert_not_found(response):
    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "not_found"
    assert set(body) == {"code", "message", "details"}


def _invoice_snapshot(invoice):
    return {
        key: invoice[key]
        for key in (
            "id",
            "tenant_id",
            "customer_id",
            "number",
            "status",
            "currency",
            "subtotal",
            "discount_rate",
            "discount_amount",
            "tax",
            "total",
            "due_date",
        )
    } | {
        "lines": sorted(
            (line["description"], line["qty"], str(line["unit_price"]))
            for line in invoice["lines"]
        )
    }


@pytest.mark.parametrize(
    "lookup",
    ("foreign_invoice", "nonexistent_invoice"),
    ids=("foreign-id-is-hidden", "missing-id"),
)
def test_foreign_and_nonexistent_invoice_reads_are_not_found(
    api_client, b_client, seeded_ids, lookup
):
    # Arrange — only the foreign case creates an invoice in Tenant A.
    a_c, a_h = api_client("staff")
    if lookup == "foreign_invoice":
        invoice = make_draft(a_c, a_h, customer_id=seeded_ids["customer_a"])
        invoice_id = invoice["id"]
    else:
        invoice_id = 999999

    b_c, b_h = b_client

    # Act — Tenant B requests the selected ID.
    response = b_c.get(f"/invoices/{invoice_id}", headers=b_h)

    # Assert — callers cannot distinguish a foreign resource from a missing one.
    _assert_not_found(response)


def test_invoice_list_only_returns_the_callers_tenant(
    api_client, b_client, seeded_ids
):
    # Arrange — each tenant owns an invoice; use the corresponding customer.
    a_c, a_h = api_client("staff")
    invoice_a = make_draft(a_c, a_h, customer_id=seeded_ids["customer_a"])
    b_c, b_h = b_client
    invoice_b = make_draft(b_c, b_h, customer_id=seeded_ids["customer_b"])

    # Act
    response_a = a_c.get("/invoices", headers=a_h)
    response_b = b_c.get("/invoices", headers=b_h)

    # Assert — exact IDs catch leaks even when each tenant has its own invoices.
    assert response_a.status_code == 200
    assert response_b.status_code == 200
    body_a = response_a.json()
    body_b = response_b.json()
    assert body_a["total"] == 1
    assert body_b["total"] == 1
    assert {row["id"] for row in body_a["items"]} == {invoice_a["id"]}
    assert {row["id"] for row in body_b["items"]} == {invoice_b["id"]}
    assert all(row["tenant_id"] == seeded_ids["tenant_a"] for row in body_a["items"])
    assert all(row["tenant_id"] == seeded_ids["tenant_b"] for row in body_b["items"])


def test_customer_list_only_returns_the_callers_tenant(
    api_client, b_client, seeded_ids
):
    a_c, a_h = api_client("staff")
    b_c, b_h = b_client

    response_a = a_c.get("/customers", headers=a_h)
    response_b = b_c.get("/customers", headers=b_h)

    assert response_a.status_code == 200
    assert response_b.status_code == 200
    assert {customer["id"] for customer in response_a.json()} == {
        seeded_ids["customer_a"]
    }
    assert {customer["id"] for customer in response_b.json()} == {
        seeded_ids["customer_b"]
    }


@pytest.mark.parametrize(
    ("method", "suffix", "body"),
    (
        pytest.param("PATCH", "", {"status": "submitted"}, id="patch-status"),
        pytest.param("POST", "/submit", None, id="submit"),
        pytest.param("POST", "/approve", None, id="approve"),
        pytest.param("POST", "/reject", None, id="reject"),
        pytest.param("POST", "/void", None, id="void"),
        pytest.param("POST", "/pay", None, id="pay"),
    ),
)
def test_foreign_invoice_mutations_are_hidden_and_leave_invoice_unchanged(
    api_client, b_client, seeded_ids, method, suffix, body
):
    # Arrange — Tenant A owns a valid draft, captured before the foreign attempt.
    a_c, a_h = api_client("staff")
    invoice = make_draft(a_c, a_h, customer_id=seeded_ids["customer_a"])
    before = _invoice_snapshot(invoice)
    b_c, b_h = b_client

    # Act — every endpoint must apply the tenant guard before role/state checks.
    response = b_c.request(
        method,
        f"/invoices/{invoice['id']}{suffix}",
        json=body,
        headers=b_h,
    )

    # Assert — no existence disclosure, and no mutation by a denied request.
    _assert_not_found(response)
    foreign_read = b_c.get(f"/invoices/{invoice['id']}", headers=b_h)
    _assert_not_found(foreign_read)
    owner_response = a_c.get(f"/invoices/{invoice['id']}", headers=a_h)
    assert owner_response.status_code == 200
    assert _invoice_snapshot(owner_response.json()) == before


def test_foreign_customer_cannot_be_used_to_create_invoice(
    api_client, seeded_ids
):
    a_c, a_h = api_client("staff")
    before = a_c.get("/invoices", headers=a_h)
    assert before.status_code == 200
    before_ids = {row["id"] for row in before.json()["items"]}

    response = a_c.post(
        "/invoices",
        json={
            "customer_id": seeded_ids["customer_b"],
            "due_date": str(date.today() + timedelta(days=7)),
            "lines": [
                {"description": "Foreign customer", "qty": 1, "unit_price": "100.00"}
            ],
        },
        headers=a_h,
    )

    _assert_not_found(response)
    after = a_c.get("/invoices", headers=a_h)
    assert after.status_code == 200
    assert {row["id"] for row in after.json()["items"]} == before_ids


def test_foreign_customer_cannot_be_set_on_existing_invoice(
    api_client, seeded_ids
):
    a_c, a_h = api_client("staff")
    invoice = make_draft(a_c, a_h, customer_id=seeded_ids["customer_a"])
    before = _invoice_snapshot(invoice)

    response = a_c.patch(
        f"/invoices/{invoice['id']}",
        json={"customer_id": seeded_ids["customer_b"]},
        headers=a_h,
    )

    _assert_not_found(response)
    owner_response = a_c.get(f"/invoices/{invoice['id']}", headers=a_h)
    assert owner_response.status_code == 200
    assert _invoice_snapshot(owner_response.json()) == before
