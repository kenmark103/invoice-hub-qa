"""Invoice service: validation, totals, transitions, tenant scoping (404, never 403)."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException
from sqlalchemy.orm import Session

from . import bug_toggles
from .models import Customer, Invoice, InvoiceLine, Tenant, User
from .pricing import calc_totals

MAX_LINES = 50
MIN_PRICE = Decimal("0.01")
MAX_PRICE = Decimal("1000000.00")

TRANSITIONS = {
    "draft": {"submitted", "void"},
    "submitted": {"approved", "rejected"},
    "approved": {"paid", "void"},
    "rejected": set(),
    "paid": set(),
    "void": set(),
}


def api_error(status: int, code: str, message: str, details: dict | None = None) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message, "details": details or {}})


def not_found(resource: str = "Not found") -> HTTPException:
    return api_error(404, "not_found", resource)


def validate_lines(lines) -> list:
    if not lines or len(lines) > MAX_LINES:
        raise api_error(422, "invalid_lines", f"Invoice needs 1-{MAX_LINES} lines")
    clean = []
    for ln in lines:
        qty = ln.qty if hasattr(ln, "qty") else ln["qty"]
        price = ln.unit_price if hasattr(ln, "unit_price") else ln["unit_price"]
        if isinstance(qty, bool) or not isinstance(qty, int) or not 1 <= qty <= 999:
            raise api_error(422, "invalid_qty", "qty must be an integer 1-999")
        price = Decimal(str(price))
        if price < MIN_PRICE or price > MAX_PRICE or price != price.quantize(Decimal("0.01")):
            raise api_error(422, "invalid_price", "unit_price must have <=2 decimals within 0.01-1000000.00")
        clean.append((qty, price))
    return clean


def validate_due_date(d: date) -> None:
    today = date.today()
    earliest = today - timedelta(days=1) if bug_toggles.is_active("BUG-006") else today
    # BUG-006: yesterday is accepted while the bug is active.
    if d < earliest or d > today + timedelta(days=365):
        raise api_error(422, "invalid_due_date", "due_date must be today..today+365 days")


def tenant_or_404(db: Session, model, obj_id: int, tenant_id: int, name: str):
    obj = db.get(model, obj_id)
    if obj is None or obj.tenant_id != tenant_id:
        raise not_found(name)  # cross-tenant reads as 404, never 403
    return obj


def next_number(db: Session, tenant_id: int) -> str:
    count = db.query(Invoice).filter(Invoice.tenant_id == tenant_id).count()
    return f"INV-{count + 1:04d}"  # no deletes -> numbers never reused


def totals_for(db: Session, tenant_id: int, lines: list) -> dict:
    tenant = db.get(Tenant, tenant_id)
    return calc_totals(lines, plan=tenant.plan)


def check_transition(inv: Invoice, to: str) -> None:
    if to == inv.status:
        return
    allowed = set(TRANSITIONS.get(inv.status, set()))
    if bug_toggles.is_active("BUG-005") and inv.status == "paid" and to == "draft":
        return  # BUG-005: illegal paid -> draft is accepted while active
    if to not in allowed:
        raise api_error(409, "illegal_transition", f"Cannot move {inv.status} -> {to}")


def create_invoice(db: Session, actor: User, customer_id: int, due: date, raw_lines) -> Invoice:
    customer = tenant_or_404(db, Customer, customer_id, actor.tenant_id, "Customer")
    lines = validate_lines(raw_lines)
    validate_due_date(due)
    tenant = db.get(Tenant, actor.tenant_id)
    totals = calc_totals(lines, plan=tenant.plan)
    inv = Invoice(
        tenant_id=actor.tenant_id,
        customer_id=customer.id,
        number=next_number(db, actor.tenant_id),
        status="draft",
        currency=tenant.currency,
        due_date=due,
        created_by=actor.id,
        **totals,
    )
    db.add(inv)
    db.flush()
    for qty, price in lines:
        desc = ""
        for ln in raw_lines:
            q = ln.qty if hasattr(ln, "qty") else ln["qty"]
            p = Decimal(str(ln.unit_price if hasattr(ln, "unit_price") else ln["unit_price"]))
            if q == qty and p == price and not desc:
                desc = ln.description if hasattr(ln, "description") else ln.get("description", "")
                break
        db.add(InvoiceLine(invoice_id=inv.id, description=desc or "line", qty=qty, unit_price=price))
    db.commit()
    db.refresh(inv)
    return inv


def recalc(db: Session, inv: Invoice, raw_lines) -> None:
    tenant = db.get(Tenant, inv.tenant_id)
    lines = validate_lines(raw_lines)
    totals = calc_totals(lines, plan=tenant.plan)
    for k, v in totals.items():
        setattr(inv, k, v)
    db.query(InvoiceLine).filter(InvoiceLine.invoice_id == inv.id).delete()
    for ln in raw_lines:
        qty = ln.qty if hasattr(ln, "qty") else ln["qty"]
        price = Decimal(str(ln.unit_price if hasattr(ln, "unit_price") else ln["unit_price"]))
        desc = ln.description if hasattr(ln, "description") else ln.get("description", "line")
        db.add(InvoiceLine(invoice_id=inv.id, description=desc or "line", qty=qty, unit_price=price))
