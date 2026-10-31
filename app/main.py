"""InvoiceHub API. OpenAPI tags by resource; error body is always {code, message, details}."""
import logging
import uuid
from contextvars import ContextVar

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session

from . import bug_toggles
from .auth import create_token, get_current_user, require_roles, verify_password
from .db import get_db, init_db
from .models import Customer, Invoice, InvoiceLine, User
from .schemas import (
    CustomerIn,
    InvoiceCreate,
    InvoiceOut,
    InvoicePatch,
    LoginIn,
)
from .services import (
    TRANSITIONS,
    api_error,
    check_transition,
    create_invoice,
    not_found,
    recalc,
    tenant_or_404,
    validate_due_date,
    validate_lines,
)

logging.basicConfig(level=logging.INFO)
_logger = logging.getLogger("invoicehub")
_request_id: ContextVar[str] = ContextVar("request_id", default="-")

app = FastAPI(title="InvoiceHub", version="0.1.0")


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    rid = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    _request_id.set(rid)
    response = await call_next(request)
    response.headers["X-Request-ID"] = rid
    _logger.info("%s %s -> %s rid=%s", request.method, request.url.path, response.status_code, rid)
    return response


@app.exception_handler(HTTPException)
async def http_error_handler(_: Request, exc: HTTPException):
    detail = exc.detail if isinstance(exc.detail, dict) else {"code": "error", "message": str(exc.detail), "details": {}}
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422, content={"code": "validation_error", "message": "Invalid request", "details": exc.errors()}
    )


# ---------- health ----------
@app.get("/health", tags=["system"])
def health():
    return {"status": "ok"}


# ---------- auth ----------
@app.post("/auth/login", tags=["auth"])
def login(body: LoginIn, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == body.email).first()
    if user is None or not verify_password(body.password, user.password_hash):
        raise api_error(401, "invalid_credentials", "Wrong email or password")
    return {
        "access_token": create_token(user),
        "token_type": "bearer",
        "user": {"id": user.id, "email": user.email, "role": user.role, "tenant_id": user.tenant_id},
    }


# ---------- customers ----------
@app.get("/customers", tags=["customers"])
def list_customers(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    rows = db.query(Customer).filter(Customer.tenant_id == user.tenant_id).order_by(Customer.id).all()
    return [{"id": c.id, "tenant_id": c.tenant_id, "name": c.name, "email": c.email} for c in rows]


@app.post("/customers", tags=["customers"], status_code=201)
def create_customer(
    body: CustomerIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    c = Customer(tenant_id=user.tenant_id, name=body.name, email=body.email)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id, "tenant_id": c.tenant_id, "name": c.name, "email": c.email}


# ---------- invoices ----------
def _serialize(inv: Invoice) -> dict:
    return {
        "id": inv.id,
        "tenant_id": inv.tenant_id,
        "customer_id": inv.customer_id,
        "number": inv.number,
        "status": inv.status,
        "currency": inv.currency,
        "subtotal": inv.subtotal,
        "discount_rate": inv.discount_rate,
        "discount_amount": inv.discount_amount,
        "tax": inv.tax,
        "total": inv.total,
        "due_date": inv.due_date,
        "created_by": inv.created_by,
        "approved_by": inv.approved_by,
        "lines": [
            {"id": ln.id, "description": ln.description, "qty": ln.qty, "unit_price": ln.unit_price}
            for ln in inv.lines
        ],
    }


@app.get("/invoices", tags=["invoices"])
def list_invoices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = db.query(Invoice).filter(Invoice.tenant_id == user.tenant_id)
    if status:
        q = q.filter(Invoice.status == status)
    if date_from:
        q = q.filter(Invoice.due_date >= date_from)
    if date_to:
        q = q.filter(Invoice.due_date <= date_to)
    total = q.count()
    rows = q.order_by(Invoice.id).offset((page - 1) * page_size).limit(page_size).all()
    return {"page": page, "page_size": page_size, "total": total, "items": [_serialize(r) for r in rows]}


@app.post("/invoices", tags=["invoices"], status_code=201)
def post_invoice(body: InvoiceCreate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    inv = create_invoice(db, user, body.customer_id, body.due_date, body.lines)
    return _serialize(inv)


@app.get("/invoices/{inv_id}", tags=["invoices"])
def get_invoice(inv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    inv = db.get(Invoice, inv_id)
    if inv is None:
        raise not_found("Invoice")
    if inv.tenant_id != user.tenant_id and not bug_toggles.is_active("BUG-003"):
        # cross-tenant reads are 404, never 403 — BUG-003 leaks while active
        raise not_found("Invoice")
    return _serialize(inv)


def _can_edit_fields(user: User, inv: Invoice) -> bool:
    if inv.status != "draft":
        return False
    if user.role in ("admin", "manager"):
        return True
    return inv.created_by == user.id


def _check_action_perm(user: User, inv: Invoice, action: str) -> None:
    own = inv.created_by == user.id
    if action == "submit":
        if user.role == "staff" and not own:
            raise api_error(403, "forbidden", "staff can only submit their own drafts")
        if user.role not in ("admin", "manager", "staff"):
            raise api_error(403, "forbidden", "cannot submit")
    elif action == "approve":
        if bug_toggles.is_active("BUG-004") and user.role == "staff" and own:
            return  # BUG-004: staff can approve their own invoice while active
        if user.role not in ("admin", "manager"):
            raise api_error(403, "forbidden", "only manager|admin approve")
    elif action == "reject":
        if user.role not in ("admin", "manager"):
            raise api_error(403, "forbidden", "only manager|admin reject")
    elif action == "void":
        if inv.status == "approved" and user.role != "admin":
            raise api_error(403, "forbidden", "only admin can void an approved invoice")
        if inv.status == "draft" and user.role == "staff" and not own:
            raise api_error(403, "forbidden", "staff can only void their own drafts")
    elif action == "pay":
        if user.role not in ("admin", "manager"):
            raise api_error(403, "forbidden", "only manager|admin mark paid")


def _transition(db: Session, user: User, inv_id: int, action: str, to: str):
    inv = tenant_or_404(db, Invoice, inv_id, user.tenant_id, "Invoice")
    _check_action_perm(user, inv, action)
    check_transition(inv, to)
    inv.status = to
    if to == "approved":
        inv.approved_by = user.id
    db.commit()
    db.refresh(inv)
    return _serialize(inv)


@app.post("/invoices/{inv_id}/submit", tags=["invoices"])
def submit_invoice(inv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _transition(db, user, inv_id, "submit", "submitted")


@app.post("/invoices/{inv_id}/approve", tags=["invoices"])
def approve_invoice(inv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _transition(db, user, inv_id, "approve", "approved")


@app.post("/invoices/{inv_id}/reject", tags=["invoices"])
def reject_invoice(inv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _transition(db, user, inv_id, "reject", "rejected")


@app.post("/invoices/{inv_id}/void", tags=["invoices"])
def void_invoice(inv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _transition(db, user, inv_id, "void", "void")


@app.post("/invoices/{inv_id}/pay", tags=["invoices"])
def pay_invoice(inv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return _transition(db, user, inv_id, "pay", "paid")


@app.patch("/invoices/{inv_id}", tags=["invoices"])
def patch_invoice(body: InvoicePatch, inv_id: int, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    inv = tenant_or_404(db, Invoice, inv_id, user.tenant_id, "Invoice")
    if body.status is not None:
        # status change through PATCH goes through the same guards as the action endpoints.
        # draft-target (e.g. paid -> draft) always reaches check_transition so an
        # illegal reopen is 409 — unless BUG-005 is active, which accepts it.
        if body.status == "draft":
            if user.role != "admin":  # reopening is admin-only; the paid->draft path exists via BUG-005
                raise api_error(403, "forbidden", "cannot reopen to draft")
            check_transition(inv, "draft")
            inv.status = "draft"
        else:
            action = {"submitted": "submit", "approved": "approve", "rejected": "reject", "void": "void", "paid": "pay"}.get(
                body.status
            )
            if action is None:
                raise api_error(422, "invalid_status", f"Unknown status {body.status}")
            _check_action_perm(user, inv, action)
            check_transition(inv, body.status)
            inv.status = body.status
            if body.status == "approved":
                inv.approved_by = user.id
    if body.customer_id is not None or body.due_date is not None or body.lines is not None:
        if not _can_edit_fields(user, inv):
            raise api_error(403, "forbidden", "only drafts are editable (staff: own only)")
        if body.customer_id is not None:
            customer = tenant_or_404(db, Customer, body.customer_id, user.tenant_id, "Customer")
            inv.customer_id = customer.id
        if body.due_date is not None:
            validate_due_date(body.due_date)
            inv.due_date = body.due_date
        if body.lines is not None:
            recalc(db, inv, [InvoiceLine(description=l.description, qty=l.qty, unit_price=l.unit_price) for l in body.lines])
    db.commit()
    db.refresh(inv)
    return _serialize(inv)


# ---------- test helpers ----------
@app.post("/test/reset", tags=["system"])
def test_reset(db: Session = Depends(get_db)):
    from .config import settings as _settings

    if _settings.app_env != "test":
        raise not_found("Not found")
    from .seed_data import seed_db

    seed_db(db)
    return {"status": "reset"}


# ---------- frontend ----------
@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui/")


try:
    app.mount("/ui", StaticFiles(directory="frontend", html=True), name="ui")
except RuntimeError:
    pass  # frontend dir missing in some contexts; API still serves


@app.on_event("startup")
def _startup():
    init_db()
