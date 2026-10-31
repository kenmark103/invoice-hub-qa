"""Deterministic seed: 3 tenants (one pro), each 1 admin + 1 manager + 2 staff,
5 customers, 20 invoices across all statuses. Same data on every run."""
import random
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from .auth import hash_password
from .db import Base, engine
from .models import Customer, Invoice, InvoiceLine, Tenant, User
from .services import next_number
from .pricing import calc_totals

PASSWORD = "Passw0rd!"
STATUSES_20 = (
    ["draft"] * 5 + ["submitted"] * 4 + ["approved"] * 4 + ["paid"] * 4 + ["rejected"] * 2 + ["void"]
)


def seed_db(db: Session) -> dict:
    for tbl in (InvoiceLine, Invoice, Customer, User, Tenant):
        db.query(tbl).delete()
    db.commit()
    rng = random.Random(42)
    creds = {}
    specs = [
        ("Acme Ltd", "standard", "KES"),
        ("Beta Corp", "pro", "KES"),
        ("Nuru NGO", "standard", "KES"),
    ]
    for name, plan, currency in specs:
        slug = "".join(c.lower() if c.isalnum() else "" for c in name.split()[0])
        tenant = Tenant(name=name, plan=plan, currency=currency)
        db.add(tenant)
        db.flush()
        users = {}
        for role in ("admin", "manager", "staff1", "staff2"):
            email = f"{role}@{slug}.test"
            u = User(
                tenant_id=tenant.id,
                email=email,
                password_hash=hash_password(PASSWORD),
                role="staff" if role.startswith("staff") else role,
            )
            db.add(u)
            db.flush()
            users[role] = u
            creds[email] = PASSWORD
        customers = []
        for i in range(1, 6):
            c = Customer(tenant_id=tenant.id, name=f"{name} Customer {i}", email=f"cust{i}@{slug}.test")
            db.add(c)
            customers.append(c)
        db.flush()
        for i, status in enumerate(STATUSES_20):
            owner = users["staff1"] if i % 2 == 0 else users["staff2"]
            lines = [
                (rng.randint(1, 5), Decimal(str(rng.choice([100, 250, 499.99, 1000, 2500]))))
                for _ in range(rng.randint(1, 3))
            ]
            totals = calc_totals(lines, plan=plan)
            inv = Invoice(
                tenant_id=tenant.id,
                customer_id=rng.choice(customers).id,
                number=f"INV-{i + 1:04d}",
                status=status,
                currency=currency,
                due_date=date.today() + timedelta(days=rng.randint(0, 60)),
                created_by=owner.id,
                approved_by=users["manager"].id if status in ("approved", "paid") else None,
                **totals,
            )
            db.add(inv)
            db.flush()
            for qty, price in lines:
                db.add(InvoiceLine(invoice_id=inv.id, description="seed line", qty=qty, unit_price=price))
    db.commit()
    return creds
