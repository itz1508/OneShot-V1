"""Security headers middleware: assert the complete set is present on every response."""
from __future__ import annotations


def test_security_headers_present_on_unauth_get(setup):
    c, _app = setup
    # /health is unauthenticated and goes through the same middleware.
    r = c.get("/health")
    assert r.status_code in (200, 503)
    assert r.headers.get("X-Content-Type-Options") == "nosniff"
    assert r.headers.get("X-Frame-Options") == "DENY"
    assert r.headers.get("Cache-Control") == "no-store"
    assert r.headers.get("Referrer-Policy") == "no-referrer"
    permissions = r.headers.get("Permissions-Policy", "")
    for directive in ("camera=()", "microphone=()", "geolocation=()"):
        assert directive in permissions, f"missing Permissions-Policy directive: {directive}"
    csp = r.headers.get("Content-Security-Policy", "")
    for term in ("default-src 'self'", "frame-ancestors 'none'", "object-src 'none'"):
        assert term in csp, f"missing CSP term: {term}"


def test_health_reports_components(setup):
    c, _app = setup
    r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert "components" in body
    assert body["components"]["storage"] == "ok"
    assert body["components"]["file_store"] == "ok"
    # frontend may be "not_built" in test environments; just assert the key exists.
    assert "frontend" in body["components"]
