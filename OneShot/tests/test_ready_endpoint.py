"""/ready endpoint: 200 iff storage, file_store, and frontend are all ok."""
from __future__ import annotations

import json


def test_ready_200_when_frontend_built(setup):
    c, _app = setup
    r = c.get('/ready')
    # frontend/dist/index.html is present in the shipped tree; selfcheck
    # confirms this in the same environment. If this returns 503 the suite
    # correctly refuses to claim readiness.
    assert r.status_code == 200, r.text
    body = r.json()
    assert body['ready'] is True
    assert body['components']['storage'] == 'ok'
    assert body['components']['file_store'] == 'ok'
    assert body['components']['frontend'] == 'ok'


def test_ready_503_when_frontend_missing(tmp_path):
    # Point the app at a non-existent frontend dir to prove /ready refuses to
    # claim readiness. /health continues to answer 200 because storage and
    # file_store are still healthy — the liveness/readiness split is honored.
    from fastapi.testclient import TestClient
    from systems.api import create_app
    from systems.settings import Settings

    settings = Settings(
        data_dir=tmp_path,
        api_token='x' * 32,
        frontend_dir=tmp_path / 'does-not-exist',
    )
    app = create_app(settings, auto_worker=False)
    with TestClient(app) as c:
        c.headers.update({'Authorization': 'Bearer ' + 'x' * 32})
        ready = c.get('/ready')
        assert ready.status_code == 503, ready.text
        # FastAPI serializes HTTPException.detail dicts into {"detail": {...}}
        body = ready.json()
        detail = body.get('detail', body)
        assert detail['ready'] is False
        assert detail['components']['frontend'] == 'not_built'
        # /health remains healthy (storage + file_store ok) — liveness unchanged.
        live = c.get('/health')
        assert live.status_code == 200
        assert live.json()['components']['frontend'] == 'not_built'


def test_ready_carries_security_headers(setup):
    c, _ = setup
    r = c.get('/ready')
    assert r.headers.get('X-Content-Type-Options') == 'nosniff'
    assert r.headers.get('Referrer-Policy') == 'no-referrer'
    assert 'camera=()' in r.headers.get('Permissions-Policy', '')
