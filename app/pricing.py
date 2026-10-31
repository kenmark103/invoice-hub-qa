"""Pricing service (pure logic — unit-testable, no DB).

Rules:
- discount tiers on subtotal: <500 -> 0%, 500-1999.99 -> 5%,
  2000-9999.99 -> 10%, >=10000 -> 15%. Plan `pro` adds +2%, capped at 15%.
- tax 16% after discount, rounded HALF_UP to 2 decimals at the total only.
"""
from decimal import Decimal, ROUND_HALF_UP

from . import bug_toggles

TAX_RATE = Decimal("0.16")
TWO_PLACES = Decimal("0.01")


def _q(value: Decimal) -> Decimal:
    return value.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def discount_rate(subtotal: Decimal, plan: str = "standard") -> Decimal:
    if subtotal >= Decimal("10000"):
        base = Decimal("15")
    elif subtotal >= Decimal("2000") if not bug_toggles.is_active("BUG-001") else subtotal > Decimal("2000"):
        # BUG-001: boundary uses `>` instead of `>=` at 2000.00,
        # so exactly 2000.00 drops to the 5% tier while the bug is active.
        if subtotal >= Decimal("10000"):
            base = Decimal("15")
        else:
            base = Decimal("10")
    elif subtotal >= Decimal("500"):
        base = Decimal("5")
    else:
        base = Decimal("0")
    if plan == "pro":
        base = min(base + Decimal("2"), Decimal("15"))
    return base


def calc_totals(lines: list, plan: str = "standard") -> dict:
    """lines: iterable of (qty:int, unit_price:Decimal|str|float). All money as Decimal."""
    norm = [(int(q), Decimal(str(p))) for q, p in lines]
    subtotal = sum((q * p for q, p in norm), Decimal("0"))
    rate = discount_rate(subtotal, plan)
    discounted = subtotal * (Decimal("1") - rate / Decimal("100"))
    if bug_toggles.is_active("BUG-002"):
        # BUG-002: tax rounded per line instead of once at the total.
        factor = (Decimal("1") - rate / Decimal("100")) * TAX_RATE
        tax = sum((_q(q * p * factor) for q, p in norm), Decimal("0"))
    else:
        tax = _q(discounted * TAX_RATE)
    discount_amount = _q(subtotal - discounted)
    total = _q(discounted + tax)
    return {
        "subtotal": _q(subtotal),
        "discount_rate": rate,
        "discount_amount": discount_amount,
        "tax": tax,
        "total": total,
    }
