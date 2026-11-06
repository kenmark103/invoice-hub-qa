"""Invoice pricing behavior through the HTTP API."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.models import Tenant


STANDARD_TIERS = (
    pytest.param("499.99", "0", "0.00", "80.00", "579.99", id="below-500"),
    pytest.param("500.00", "5", "25.00", "76.00", "551.00", id="at-500"),
    pytest.param("1999.99", "5", "100.00", "304.00", "2203.99", id="below-2000"),
    pytest.param("2000.00", "10", "200.00", "288.00", "2088.00", id="at-2000"),
    pytest.param("9999.99", "10", "1000.00", "1440.00", "10439.99", id="below-10000"),
    pytest.param("10000.00", "15", "1500.00", "1360.00", "9860.00", id="at-10000"),
)

PRO_TIERS = (
    pytest.param("500.00", "7", "35.00", "74.40", "539.40", id="pro-five-plus-two"),
    pytest.param("2000.00", "12", "240.00", "281.60", "2041.60", id="pro-ten-plus-two"),
    pytest.param("10000.00", "15", "1500.00", "1360.00", "9860.00", id="pro-cap"),
)


def _create_invoice(client, headers, lines):
    return client.post(
        "/invoices",
        json={
            "customer_id": 1,
            "due_date": str(date.today() + timedelta(days=7)),
            "lines": lines,
        },
        headers=headers,
    )


def _assert_amounts(invoice, subtotal, rate, discount, tax, total):
    assert Decimal(str(invoice["subtotal"])) == Decimal(subtotal)
    assert Decimal(str(invoice["discount_rate"])) == Decimal(rate)
    assert Decimal(str(invoice["discount_amount"])) == Decimal(discount)
    assert Decimal(str(invoice["tax"])) == Decimal(tax)
    assert Decimal(str(invoice["total"])) == Decimal(total)


@pytest.mark.parametrize(
    ("amount", "rate", "discount", "tax", "total"),
    STANDARD_TIERS,
)
def test_standard_plan_invoice_pricing_tiers(
    api_client, amount, rate, discount, tax, total
):
    client, headers = api_client("staff")

    response = _create_invoice(
        client,
        headers,
        [{"description": "Tier boundary", "qty": 1, "unit_price": amount}],
    )

    assert response.status_code == 201, response.text
    invoice = response.json()
    _assert_amounts(invoice, amount, rate, discount, tax, total)
    assert invoice["status"] == "draft"


@pytest.mark.parametrize(
    ("amount", "rate", "discount", "tax", "total"),
    PRO_TIERS,
)
def test_pro_plan_invoice_pricing_bonus_and_cap(
    api_client, db, amount, rate, discount, tax, total
):
    tenant = db.query(Tenant).filter(Tenant.name == "Acme Ltd").one()
    tenant.plan = "pro"
    db.commit()
    client, headers = api_client("staff")

    response = _create_invoice(
        client,
        headers,
        [{"description": "Pro tier", "qty": 1, "unit_price": amount}],
    )

    assert response.status_code == 201, response.text
    _assert_amounts(response.json(), amount, rate, discount, tax, total)


def test_invoice_pricing_uses_combined_subtotal_for_multiple_lines(api_client):
    client, headers = api_client("staff")
    lines = [
        {"description": "First", "qty": 1, "unit_price": "33.33"},
        {"description": "Second", "qty": 2, "unit_price": "10.00"},
        {"description": "Third", "qty": 1, "unit_price": "46.67"},
    ]

    response = _create_invoice(client, headers, lines)

    assert response.status_code == 201, response.text
    invoice = response.json()
    _assert_amounts(invoice, "100.00", "0", "0.00", "16.00", "116.00")
    assert {
        line["description"]: (line["qty"], Decimal(str(line["unit_price"])))
        for line in invoice["lines"]
    } == {
        "First": (1, Decimal("33.33")),
        "Second": (2, Decimal("10.00")),
        "Third": (1, Decimal("46.67")),
    }
