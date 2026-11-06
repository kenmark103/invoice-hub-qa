"""Shared fixtures: in-memory SQLite, minimal two-tenant seed, login helpers.

Covers the brief's conftest fixtures: api_client(role), tenant_a, tenant_b, reset_db.
Run from repo root: python -m pytest
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["APP_ENV"] = "test"
os.environ["ACTIVE_BUGS"] = ""  # baseline: no bugs; individual tests flip IDs via monkeypatch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401  (register tables)
from app.auth import hash_password
from app.db import Base, get_db
from app.main import app
from app.models import Customer, Tenant, User

PASSWORD = "Passw0rd!"

test_engine = create_engine(
    "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
)
TestingSession = sessionmaker(bind=test_engine, autoflush=False, autocommit=False)


def seed_minimal(db) -> dict:
    """One standard tenant A (admin/manager/staff), one tenant B (admin), one customer each."""
    # Arrange base data — deterministic, no randomness
    tenant_a = Tenant(name="Acme Ltd", plan="standard", currency="KES")
    tenant_b = Tenant(name="Beta Corp", plan="standard", currency="KES")
    db.add_all([tenant_a, tenant_b])
    db.flush()
    users = {
        "admin": User(tenant_id=tenant_a.id, email="admin@acme.test", password_hash=hash_password(PASSWORD), role="admin"),
        "manager": User(tenant_id=tenant_a.id, email="manager@acme.test", password_hash=hash_password(PASSWORD), role="manager"),
        "staff": User(tenant_id=tenant_a.id, email="staff@acme.test", password_hash=hash_password(PASSWORD), role="staff"),
        "b_admin": User(tenant_id=tenant_b.id, email="admin@beta.test", password_hash=hash_password(PASSWORD), role="admin"),
    }
    db.add_all(users.values())
    db.flush()
    ca = Customer(tenant_id=tenant_a.id, name="Acme Customer 1", email="c1@acme.test")
    cb = Customer(tenant_id=tenant_b.id, name="Beta Customer 1", email="c1@beta.test")
    db.add_all([ca, cb])
    db.commit()
    return {"a": tenant_a.id, "b": tenant_b.id, "ca": ca.id, "cb": cb.id}


@pytest.fixture()
def db():
    # Arrange — fresh schema + seed per test keeps tests independent
    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    session = TestingSession()
    seed_minimal(session)
    yield session
    session.close()


@pytest.fixture()
def tenant_a(db):
    return db.query(Tenant).filter(Tenant.name == "Acme Ltd").one().id


@pytest.fixture()
def tenant_b(db):
    return db.query(Tenant).filter(Tenant.name == "Beta Corp").one().id


@pytest.fixture()
def seeded_ids(db):
    """Named IDs for the tenants and customers created by the default seed."""
    tenant_a = db.query(Tenant).filter(Tenant.name == "Acme Ltd").one()
    tenant_b = db.query(Tenant).filter(Tenant.name == "Beta Corp").one()
    customer_a = db.query(Customer).filter(Customer.email == "c1@acme.test").one()
    customer_b = db.query(Customer).filter(Customer.email == "c1@beta.test").one()
    return {
        "tenant_a": tenant_a.id,
        "tenant_b": tenant_b.id,
        "customer_a": customer_a.id,
        "customer_b": customer_b.id,
    }


@pytest.fixture()
def reset_db(db):
    def _reset():
        for tbl in ("invoice_lines", "invoices", "customers", "users", "tenants"):
            db.execute(__import__("sqlalchemy").text(f"DELETE FROM {tbl}"))
        db.commit()
        return seed_minimal(db)

    return _reset


@pytest.fixture()
def client(db):
    def _override():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def _login(client, email):
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture()
def api_client(client):
    """api_client(role) -> (client, headers) for tenant-A admin|manager|staff."""

    def _for(role: str):
        return client, _login(client, {"admin": "admin@acme.test", "manager": "manager@acme.test", "staff": "staff@acme.test"}[role])

    return _for


@pytest.fixture()
def b_client(client):
    """Tenant-B admin client, for cross-tenant checks."""
    return client, _login(client, "admin@beta.test")


def make_draft(client, headers, customer_id=1, lines=None, due=None):
    from datetime import date, timedelta

    default_lines = [{"description": "Testing services", "qty": 2, "unit_price": "600.00"}]
    body = {
        "customer_id": customer_id,
        "due_date": str(due or (date.today() + timedelta(days=7))),
        "lines": lines if lines is not None else default_lines,
    }
    r = client.post("/invoices", json=body, headers=headers)
    assert r.status_code == 201, r.text
    return r.json()
