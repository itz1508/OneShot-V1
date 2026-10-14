"""/api/capabilities now reads from the auto-discovered catalog.

Shape must stay a strict superset of the legacy response so existing
consumers (frontend ``api.capabilities()``, E2E assertions) keep working.
"""
from __future__ import annotations


def test_capabilities_preserves_legacy_shape(setup):
    c, _ = setup
    r = c.get('/api/capabilities')
    assert r.status_code == 200
    body = r.json()
    # Legacy keys (frontend reads these):
    assert body['scanner']['tools']['read'] == 'available'
    assert body['scanner']['tools']['view'] == 'unavailable'
    assert body['researcher']['web_browser'] == 'validation_only'
    assert body['researcher']['web_extraction'] == 'available_for_supplied_html'
    assert 'checklist' in body['advisor']['tools']
    assert body['auto_generator']['provider'] == 'evidence'
    assert body['auto_generator']['mode'] == 'evidence_packet'


def test_capabilities_exposes_discovered_catalog(setup):
    c, _ = setup
    body = c.get('/api/capabilities').json()
    cat = body['catalog']
    # Scanner read + view are discovered with real docstrings.
    assert 'read' in cat['scanner'] and cat['scanner']['read']['available'] is True
    assert 'view' in cat['scanner'] and cat['scanner']['view']['available'] is False
    assert cat['scanner']['read']['description']
    assert cat['scanner']['view']['description']
    # Researcher URL validator is validation-only but still a registered tool.
    assert 'validate' in cat['researcher']
    assert cat['researcher']['validate']['description']
    assert 'extract' in cat['researcher']
    # Advisor exposes checklist preparation.
    assert 'prepare' in cat['advisor']
    assert cat['advisor']['prepare']['description']


def test_catalog_discover_is_deterministic():
    from capabilities.catalog import discover
    result = discover()
    assert list(result.keys()) == ['scanner', 'researcher', 'advisor']
    assert {e.name for e in result['scanner']} == {'read', 'view'}
    assert {e.name for e in result['researcher']} == {'validate', 'extract'}
    assert {e.name for e in result['advisor']} == {'prepare'}
