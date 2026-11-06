"""Request/response schemas. Range rules are enforced in services for a uniform error body."""
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class LoginIn(BaseModel):
    email: str
    password: str


class CustomerIn(BaseModel):
    name: str
    email: str


class LineIn(BaseModel):
    description: str
    qty: int
    unit_price: Decimal


class InvoiceCreate(BaseModel):
    customer_id: int
    due_date: date
    lines: list[LineIn]


class InvoicePatch(BaseModel):
    customer_id: int | None = None
    due_date: date | None = None
    lines: list[LineIn] | None = None
    status: str | None = None


class LineOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    description: str
    qty: int
    unit_price: Decimal


class InvoiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    tenant_id: int
    customer_id: int
    number: str
    status: str
    currency: str
    subtotal: Decimal
    discount_rate: Decimal
    discount_amount: Decimal
    tax: Decimal
    total: Decimal
    due_date: date
    created_by: int
    approved_by: int | None
    lines: list[LineOut] = Field(default_factory=list)
