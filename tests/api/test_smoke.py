"""Smoke: health, login per role, and the create -> submit -> approve happy path."""
from tests.conftest import make_draft


def test_health_returns_200(client):
    # Arrange — no auth needed
    # Act
    r = client.get("/health")
    # Assert
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_login_works_for_each_role(api_client):
    # Arrange — seeded admin/manager/staff in tenant A
    # Act / Assert — each role gets a usable bearer token
    for role in ("admin", "manager", "staff"):
        c, headers = api_client(role)
        r = c.get("/invoices", headers=headers)
        assert r.status_code == 200, role


def test_login_rejects_bad_password(client):
    # Arrange — right email, wrong password
    # Act
    r = client.post("/auth/login", json={"email": "admin@acme.test", "password": "nope"})
    # Assert — uniform error envelope
    assert r.status_code == 401
    assert r.json()["code"] == "invalid_credentials"


def test_create_submit_approve_happy_path(api_client):
    # Arrange — staff drafts, manager approves
    staff_c, staff_h = api_client("staff")
    mgr_c, mgr_h = api_client("manager")
    # Act 1 — staff creates a draft (2 x 600 = 1322.40 total, see test_pricing)
    inv = make_draft(staff_c, staff_h)
    assert inv["status"] == "draft"
    assert inv["number"] == "INV-0001"  # per-tenant sequence starts at 0001
    assert float(inv["total"]) == 1322.40
    # Act 2 — staff submits their own draft
    r = staff_c.post(f"/invoices/{inv['id']}/submit", headers=staff_h)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "submitted"
    # Act 3 — manager approves
    r = mgr_c.post(f"/invoices/{inv['id']}/approve", headers=mgr_h)
    # Assert
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "approved"
    assert body["approved_by"] is not None


def test_invoice_line_schemas_expose_line_item_fields(client):
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    expected_ref = {"$ref": "#/components/schemas/LineIn"}

    assert schemas["InvoiceCreate"]["properties"]["lines"]["items"] == expected_ref
    patch_lines = schemas["InvoicePatch"]["properties"]["lines"]["anyOf"]
    assert patch_lines[0]["items"] == expected_ref
    assert patch_lines[1]["type"] == "null"
    assert schemas["LineIn"]["properties"].keys() >= {"description", "qty", "unit_price"}


def test_patch_invoice_lines_accepts_line_item_objects(api_client):
    c, headers = api_client("staff")
    inv = make_draft(c, headers)

    response = c.patch(
        f"/invoices/{inv['id']}",
        json={"lines": [{"description": "Updated service", "qty": 3, "unit_price": "125.50"}]},
        headers=headers,
    )

    assert response.status_code == 200, response.text
    assert response.json()["lines"][0]["description"] == "Updated service"
    assert response.json()["lines"][0]["qty"] == 3


def test_error_body_shape_on_missing_invoice(api_client):
    # Arrange
    c, headers = api_client("staff")
    # Act
    r = c.get("/invoices/9999", headers=headers)
    # Assert — consistent {code, message, details} envelope
    assert r.status_code == 404
    assert set(r.json()) == {"code", "message", "details"}
