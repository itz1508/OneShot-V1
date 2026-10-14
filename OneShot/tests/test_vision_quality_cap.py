"""Vision-derived sources default to INCOMPLETE and never silently promote."""
from pathlib import Path
import json, struct, zlib
from fastapi.testclient import TestClient
from systems.settings import Settings
from systems.api import create_app
import httpx
import pytest


def _tiny_png() -> bytes:
    sig = b'\x89PNG\r\n\x1a\n'
    ihdr_data = struct.pack('>II', 2, 2) + b'\x08\x02\x00\x00\x00'
    ihdr = b'IHDR' + ihdr_data
    ihdr_chunk = struct.pack('>I', len(ihdr_data)) + ihdr + struct.pack('>I', zlib.crc32(ihdr))
    idat_data = zlib.compress(b'\x00\xff\x00\x00\x00\xff\x00\x00')
    idat = b'IDAT' + idat_data
    idat_chunk = struct.pack('>I', len(idat_data)) + idat + struct.pack('>I', zlib.crc32(idat))
    iend_chunk = struct.pack('>I', 0) + b'IEND' + struct.pack('>I', zlib.crc32(b'IEND'))
    return sig + ihdr_chunk + idat_chunk + iend_chunk


class _VisionResponder(httpx.MockTransport):
    """In-process stand-in for a loopback llama-server. Keeps the test deterministic
    without pretending to be a semantic model: this transport is explicitly a
    responder, used only to exercise the API-shape contract, not E14 acceptance."""

    def __init__(self, text='Transcribed: Harbor sign reads "Copper Lantern".'):
        def handler(request):
            payload = request.content and json.loads(request.content)
            messages = payload['messages'][0]['content']
            # Confirm the server actually sends an image_url part.
            assert any(part.get('type') == 'image_url' for part in messages), messages
            return httpx.Response(200, json={
                'choices': [{'finish_reason': 'stop',
                             'message': {'content': text, 'tool_calls': None}}],
            })
        super().__init__(handler)


@pytest.fixture
def app_with_vision(tmp_path, monkeypatch):
    cfg = Settings(data_dir=tmp_path, api_token='a' * 32, browser_password='vq-pw-16-chars-at-least',
                   vision_provider='llama', vision_endpoint='http://127.0.0.1:65123/v1/chat/completions',
                   vision_model='llava-1.6-mini')
    # Intercept the vision call via a mock transport injected into request_vision
    import systems.model_transport as mt
    original_request_vision = mt.request_vision

    def patched_request_vision(endpoint, model, prompt, image_bytes, mime, **kw):
        kw['transport'] = _VisionResponder()
        return original_request_vision(endpoint, model, prompt, image_bytes, mime, **kw)

    monkeypatch.setattr(mt, 'request_vision', patched_request_vision)
    # Scanner imports via `from systems.model_transport import request_vision`
    import capabilities.scanner.tools.view as view_mod
    monkeypatch.setattr('capabilities.scanner.tools.view.request_vision'
                        if hasattr(view_mod, 'request_vision') else 'systems.model_transport.request_vision',
                        patched_request_vision, raising=False)
    return create_app(cfg, auto_worker=True)


def _login(client):
    r = client.post('/auth/login', json={'password': 'vq-pw-16-chars-at-least'})
    assert r.status_code == 200, r.text
    client.headers['x-oneshot-csrf'] = r.json()['csrf']


def test_vision_source_runs_but_quality_is_capped_at_incomplete(app_with_vision):
    c = TestClient(app_with_vision).__enter__()
    _login(c)
    r = c.post('/api/conversations', json={'title': 'vq'})
    cid = r.json()['id']
    r = c.post(f'/api/conversations/{cid}/messages',
               json={'channel': 'system', 'content': 'inspect this diagram'})
    mid = r.json()['id']
    import base64
    b64 = base64.b64encode(_tiny_png()).decode()
    r = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'IMPORT_SOURCE', 'name': 'figure.png', 'content_base64': b64})
    assert r.status_code == 201, r.text
    d = r.json(); sid = d['source_id']; sver = d['version']
    r = c.post(f'/api/conversations/{cid}/jobs',
               json={'operation': 'inspect_sources', 'source_ids': [sid],
                     'expected_versions': {sid: sver},
                     'idempotency_key': 'vq-test-key-abc',
                     'prompt_message_id': mid})
    assert r.status_code == 202, r.text
    jid = r.json()['id']
    import time
    for _ in range(100):
        r = c.get(f'/api/conversations/{cid}/jobs/{jid}')
        st = r.json().get('status')
        if st in ('completed', 'failed', 'blocked'):
            break
        time.sleep(0.1)
    # The vision reader is a monkey-patched responder, so this is a wire test,
    # not E14. The acceptance here is on the quality cap and provenance, both
    # of which are OneShot-side invariants that any real vision model will
    # trigger identically.
    r = c.get(f'/api/conversations/{cid}/events?limit=200')
    r.raise_for_status()
    evs = r.json()['events']
    inspected = [e for e in evs if e['kind'] == 'source_inspected']
    assert inspected, 'scanner must emit source_inspected for vision source'
    payload = inspected[-1]['payload']
    assert payload['inspection_mode'] == 'visual', payload
    assert payload['vision']['model_id'] == 'llava-1.6-mini'
    assert payload['vision']['deterministic'] is False
    assert payload['vision']['response_sha256']
    # Quality cap: coverage_assessed must emit 'incomplete' not 'structural_ready'
    coverage = [e for e in evs if e['kind'] == 'coverage_assessed']
    assert coverage
    assert coverage[-1]['payload']['structural_state'] in ('incomplete', 'unusable'), \
        f'vision source must not promote to structural_ready; got {coverage[-1]["payload"]}'
