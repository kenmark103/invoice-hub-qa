"""Tenant-isolation baseline (no bugs active): cross-tenant access is 404, never 403."""
from tests.conftest import make_draft


def test_cross_tenant_read_returns_404(api_client, b_client):
    # Arrange — staff in tenant A owns a draft; baseline has no bugs active
    a_c, a_h = api_client("staff")
    inv = make_draft(a_c, a_h)
    b_c, b_h = b_client
    # Act — tenant B asks for A's invoice by id
    r = b_c.get(f"/invoices/{inv['id']}", headers=b_h)
    # Assert — 404 (not 403) so tenants can't probe each other's ids
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_cross_tenant_list_hides_foreign_invoices(api_client, b_client):
    # Arrange
    a_c, a_h = api_client("staff")
    make_draft(a_c, a_h)
    b_c, b_h = b_client
    # Act
    mine = a_c.get("/invoices", headers=a_h).json()
    theirs = b_c.get("/invoices", headers=b_h).json()
    # Assert — each tenant sees only its own rows
    assert mine["total"] == 1
    assert theirs["total"] == 0


def test_cross_tenant_write_returns_404(api_client, b_client):
    # Arrange
    a_c, a_h = api_client("staff")
    inv = make_draft(a_c, a_h)
    b_c, b_h = b_client
    # Act — tenant B tries to patch A's invoice
    r = b_c.patch(f"/invoices/{inv['id']}", json={"status": "submitted"}, headers=b_h)
    # Assert
    assert r.status_code == 404
