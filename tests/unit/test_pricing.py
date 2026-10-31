"""Unit tests for pricing: discount tiers, pro bonus + cap, 16% tax half-up at total."""
from decimal import Decimal

import pytest

from app import pricing


def _total(*amounts, plan="standard"):
    # Arrange — one line per amount at qty 1
    lines = [(1, Decimal(str(a))) for a in amounts]
    # Act
    return pricing.calc_totals(lines, plan=plan)


def test_below_500_no_discount():
    # Arrange / Act
    out = _total("499.99")
    # Assert — tier <500 -> 0%
    assert out["discount_rate"] == Decimal("0")
    assert out["subtotal"] == Decimal("499.99")
    assert out["tax"] == Decimal("80.00")  # 499.99 * 0.16, half-up
    assert out["total"] == Decimal("579.99")


def test_tier_boundaries():
    # Arrange / Act / Assert — each boundary lands in the higher tier
    assert _total("500")["discount_rate"] == Decimal("5")
    assert _total("1999.99")["discount_rate"] == Decimal("5")
    assert _total("2000")["discount_rate"] == Decimal("10")
    assert _total("9999.99")["discount_rate"] == Decimal("10")
    assert _total("10000")["discount_rate"] == Decimal("15")
    assert _total("25000")["discount_rate"] == Decimal("15")


def test_pro_plan_adds_two_percent_capped_at_15():
    # Arrange / Act / Assert
    assert _total("1000", plan="pro")["discount_rate"] == Decimal("7")  # 5 + 2
    assert _total("5000", plan="pro")["discount_rate"] == Decimal("12")  # 10 + 2
    assert _total("10000", plan="pro")["discount_rate"] == Decimal("15")  # capped, never exceeds 15


def test_happy_path_math():
    # Arrange — 2 x 600 = 1200 -> 5% -> taxable 1140 -> tax 182.40 -> total 1322.40
    # Act
    out = pricing.calc_totals([(2, Decimal("600.00"))])
    # Assert
    assert out == {
        "subtotal": Decimal("1200.00"),
        "discount_rate": Decimal("5"),
        "discount_amount": Decimal("60.00"),
        "tax": Decimal("182.40"),
        "total": Decimal("1322.40"),
    }


def test_tax_rounds_half_up_at_total_only():
    # Arrange — 3 lines whose exact tax is 15.996 -> rounds to 16.00 once at the total
    # Act
    out = pricing.calc_totals(
        [(1, Decimal("33.33")), (1, Decimal("33.33")), (1, Decimal("33.34"))]
    )
    # Assert
    assert out["subtotal"] == Decimal("100.00")
    assert out["tax"] == Decimal("16.00")
    assert out["total"] == Decimal("116.00")


def test_bug001_boundary_drops_to_5_percent(monkeypatch):
    # Arrange — exactly 2000.00 with the bug active
    monkeypatch.setenv("ACTIVE_BUGS", "BUG-001")
    # Act
    out = _total("2000")
    # Assert — wrong tier (5% instead of 10%) proves the planted branch runs
    assert out["discount_rate"] == Decimal("5")


def test_bug002_per_line_rounding_differs(monkeypatch):
    # Arrange — same 100.00 split across 3 lines; per-line rounding gives 15.99
    monkeypatch.setenv("ACTIVE_BUGS", "BUG-002")
    # Act
    out = pricing.calc_totals(
        [(1, Decimal("33.33")), (1, Decimal("33.33")), (1, Decimal("33.34"))]
    )
    # Assert — differs from the correct 16.00, proving the bug is plantable
    assert out["tax"] == Decimal("15.99")
    assert out["tax"] != Decimal("16.00")
