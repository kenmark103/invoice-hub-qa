"""Invoice create and update request validation through the HTTP API."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tests.conftest import make_draft


def _invoice_body(customer_id=1, **overrides):
    body = {
        "customer_id": customer_id,
        "due_date": str(date.today() + timedelta(days=7)),
        "lines": [{"description": "Validation item", "qty": 1, "unit_price": "10.00"}],
    }
    body.update(overrides)
    return body


def _assert_error(response, code):
    assert response.status_code == 422
    assert response.json()["code"] == code


@pytest.mark.parametrize(
    "body",
    (
        pytest.param(
            {"due_date": "2026-11-13", "lines": [{"description": "x", "qty": 1, "unit_price": "1.00"}]},
            id="missing-customer-id",
        ),
        pytest.param(
            {"customer_id": 1, "lines": [{"description": "x", "qty": 1, "unit_price": "1.00"}]},
            id="missing-due-date",
        ),
        pytest.param(
            {"customer_id": 1, "due_date": "2026-11-13"},
            id="missing-lines",
        ),
        pytest.param(
            _invoice_body(due_date="not-a-date"),
            id="malformed-date",
        ),
        pytest.param(
            _invoice_body(lines=[{"qty": 1, "unit_price": "1.00"}]),
            id="missing-line-description",
        ),
        pytest.param(
            _invoice_body(lines=[{"description": "x", "unit_price": "1.00"}]),
            id="missing-line-quantity",
        ),
        pytest.param(
            _invoice_body(lines=[{"description": "x", "qty": 1}]),
            id="missing-line-price",
        ),
    ),
)
def test_invoice_create_rejects_missing_or_malformed_fields(
    api_client, seeded_ids, body
):
    request_client, headers = api_client("staff")
    if "customer_id" in body:
        body = {**body, "customer_id": seeded_ids["customer_a"]}

    response = request_client.post("/invoices", json=body, headers=headers)

    _assert_error(response, "validation_error")


@pytest.mark.parametrize(
    ("lines", "expected_status", "expected_code"),
    (
        pytest.param([], 422, "invalid_lines", id="no-lines"),
        pytest.param(
            [{"description": "x", "qty": 1, "unit_price": "1.00"}] * 51,
            422,
            "invalid_lines",
            id="over-50-lines",
        ),
        pytest.param(
            [{"description": "x", "qty": 1, "unit_price": "1.00"}],
            201,
            None,
            id="one-line-minimum",
        ),
        pytest.param(
            [{"description": "x", "qty": 1, "unit_price": "0.01"}] * 50,
            201,
            None,
            id="50-lines-maximum",
        ),
    ),
)
def test_invoice_line_count_boundaries(
    api_client, seeded_ids, lines, expected_status, expected_code
):
    client, headers = api_client("staff")

    response = client.post(
        "/invoices",
        json=_invoice_body(customer_id=seeded_ids["customer_a"], lines=lines),
        headers=headers,
    )

    assert response.status_code == expected_status, response.text
    if expected_code:
        assert response.json()["code"] == expected_code
    else:
        assert len(response.json()["lines"]) == len(lines)


@pytest.mark.parametrize(
    "qty",
    (
        pytest.param(0, id="zero"),
        pytest.param(1000, id="above-maximum"),
    ),
)
def test_invoice_rejects_out_of_range_quantity(api_client, seeded_ids, qty):
    client, headers = api_client("staff")

    response = client.post(
        "/invoices",
        json=_invoice_body(
            customer_id=seeded_ids["customer_a"],
            lines=[{"description": "x", "qty": qty, "unit_price": "1.00"}],
        ),
        headers=headers,
    )

    _assert_error(response, "invalid_qty")


@pytest.mark.parametrize(
    ("qty", "price"),
    (
        pytest.param(1, "0.01", id="minimum-quantity-and-price"),
        pytest.param(999, "1.00", id="maximum-quantity"),
        pytest.param(1, "1000000.00", id="maximum-price"),
    ),
)
def test_invoice_accepts_quantity_and_price_boundaries(
    api_client, seeded_ids, qty, price
):
    client, headers = api_client("staff")
    line = {"description": "Boundary item", "qty": qty, "unit_price": price}

    response = client.post(
        "/invoices",
        json=_invoice_body(customer_id=seeded_ids["customer_a"], lines=[line]),
        headers=headers,
    )

    assert response.status_code == 201, response.text
    created_line = response.json()["lines"][0]
    assert created_line["qty"] == qty
    assert Decimal(str(created_line["unit_price"])) == Decimal(price)


@pytest.mark.parametrize(
    "price",
    (
        pytest.param("0", id="zero"),
        pytest.param("-1.00", id="negative"),
        pytest.param("1000000.01", id="above-maximum"),
        pytest.param("1.001", id="more-than-two-decimals"),
    ),
)
def test_invoice_rejects_invalid_unit_price(api_client, seeded_ids, price):
    client, headers = api_client("staff")

    response = client.post(
        "/invoices",
        json=_invoice_body(
            customer_id=seeded_ids["customer_a"],
            lines=[{"description": "Invalid price", "qty": 1, "unit_price": price}]
        ),
        headers=headers,
    )

    _assert_error(response, "invalid_price")


@pytest.mark.parametrize(
    ("due_date", "expected_status", "expected_code"),
    (
        pytest.param(date.today(), 201, None, id="today"),
        pytest.param(date.today() + timedelta(days=365), 201, None, id="one-year"),
        pytest.param(
            date.today() - timedelta(days=1), 422, "invalid_due_date", id="yesterday"
        ),
        pytest.param(
            date.today() + timedelta(days=366),
            422,
            "invalid_due_date",
            id="beyond-one-year",
        ),
    ),
)
def test_invoice_due_date_boundaries(
    api_client, seeded_ids, due_date, expected_status, expected_code
):
    client, headers = api_client("staff")

    response = client.post(
        "/invoices",
        json=_invoice_body(
            customer_id=seeded_ids["customer_a"], due_date=str(due_date)
        ),
        headers=headers,
    )

    assert response.status_code == expected_status, response.text
    if expected_code:
        assert response.json()["code"] == expected_code


@pytest.mark.parametrize(
    ("patch", "expected_code"),
    (
        pytest.param({"lines": []}, "invalid_lines", id="empty-lines"),
        pytest.param(
            {"lines": [{"description": "x", "qty": 0, "unit_price": "1.00"}]},
            "invalid_qty",
            id="invalid-quantity",
        ),
        pytest.param({"due_date": "not-a-date"}, "validation_error", id="bad-date-type"),
    ),
)
def test_invoice_patch_validation_errors_leave_invoice_unchanged(
    api_client, patch, expected_code
):
    client, headers = api_client("staff")
    invoice = make_draft(client, headers)

    response = client.patch(
        f"/invoices/{invoice['id']}", json=patch, headers=headers
    )

    _assert_error(response, expected_code)
    current = client.get(f"/invoices/{invoice['id']}", headers=headers)
    assert current.status_code == 200
    assert current.json()["lines"] == invoice["lines"]
    assert current.json()["due_date"] == invoice["due_date"]
    assert current.json()["total"] == invoice["total"]
