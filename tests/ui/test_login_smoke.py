"""UI smoke: login page serves, and (with a browser) login -> invoice list loads.

test_login_page_serves_form runs everywhere via HTTP.
test_login_lists_invoices_browser needs Playwright + Chromium; it skips cleanly
when they are missing so `make test` stays green on machines without browsers.
"""
import threading
import time

import pytest

pytestmark = pytest.mark.ui


def test_login_page_serves_form(client):
    # Arrange — no auth
    # Act
    r = client.get("/ui/")
    # Assert — server-rendered shell with the login hooks the browser test drives
    assert r.status_code == 200
    html = r.text
    for hook in ("id=\"email\"", "id=\"password\"", "id=\"login-btn\"", "id=\"invoice-table\""):
        assert hook in html, hook


def test_invoice_actions_wired(client):
    # Arrange — the UI shell ships the workflow actions the guide asks for
    # Act
    r = client.get("/ui/")
    # Assert — every transition button and the shared action endpoint are wired
    assert r.status_code == 200
    html = r.text
    for hook in (
        'btn("submit", "Submit")',
        'btn("approve", "Approve")',
        'btn("reject", "Reject")',
        'btn("void", "Void")',
        'btn("pay", "Mark paid")',
        "/invoices/${btn.dataset.id}/${btn.dataset.action}",
    ):
        assert hook in html, hook


def test_login_lists_invoices_browser():
    # Arrange — real browser against a live uvicorn on 127.0.0.1:8766
    pw = pytest.importorskip("playwright.sync_api", reason="playwright not installed")
    import uvicorn

    from app.db import get_db
    from app.main import app
    from tests.conftest import TestingSession, seed_minimal
    from app.db import Base
    from tests.conftest import test_engine

    Base.metadata.drop_all(bind=test_engine)
    Base.metadata.create_all(bind=test_engine)
    s = TestingSession()
    seed_minimal(s)
    s.close()

    def _override():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = _override
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8766, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        with pw.sync_playwright() as p:
            try:
                browser = p.chromium.launch()
            except Exception:
                pytest.skip("chromium not available")
            page = browser.new_page()
            # Act — log in as the seeded admin
            page.goto("http://127.0.0.1:8766/ui/", timeout=15000)
            page.fill("#email", "admin@acme.test")
            page.fill("#password", "Passw0rd!")
            page.click("#login-btn")
            page.wait_for_selector("#invoice-body", timeout=15000)
            time.sleep(1)  # allow fetch to render rows
            # Assert — app view visible after login
            assert page.is_visible("#invoice-table")
            browser.close()
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        app.dependency_overrides.clear()
