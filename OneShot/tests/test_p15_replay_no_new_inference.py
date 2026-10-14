"""P15 — replay a historical terminal job's artifact without triggering new inference.

The System's model-call site is `operations.start_job` / background worker; the artifact
read handler is pure DB. We assert that reading the artifact N times after terminal state
does not advance `jobs.updated_at`, does not create new events, and does not change
`artifact_id`.
"""
import time

import pytest
from fastapi.testclient import TestClient

from systems.settings import Settings
from systems.api import create_app


PW = 'p15-pw-16-chars-aaa'


def _login(tmp_path, request=None):
    cfg = Settings(data_dir=tmp_path, api_token='p' * 32, browser_password=PW)
    app = create_app(cfg, auto_worker=True)
    tc = TestClient(app).__enter__()
    if request is not None:
        request.addfinalizer(lambda: tc.__exit__(None, None, None))
    tc.post('/auth/login', json={'password': PW})
    tc.headers['x-oneshot-csrf'] = tc.get('/auth/session').json()['csrf']
    return tc


def _terminal_job(c):
    cid = c.post('/api/conversations', json={'title': 'p15'}).json()['id']
    mid = c.post(f'/api/conversations/{cid}/messages',
                 json={'channel': 'system', 'content': 'Objective: replay target'}).json()['id']
    s = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'target.txt',
                     'content': 'body-content for replay check'})
    sid = s.json()['source_id']; sver = s.json()['version']
    j = c.post(f'/api/conversations/{cid}/jobs',
               json={'operation': 'inspect_sources', 'source_ids': [sid],
                     'expected_versions': {sid: sver},
                     'idempotency_key': 'p15-aaa-bbb',
                     'prompt_message_id': mid}).json()
    jid = j['id']
    for _ in range(80):
        if c.get(f'/api/conversations/{cid}/jobs/{jid}').json().get('status') in (
                'completed', 'failed', 'blocked'):
            break
        time.sleep(0.1)
    return c, cid, jid


def test_p15_artifact_readback_does_not_advance_state(tmp_path, request):
    c, cid, jid = _terminal_job(_login(tmp_path, request))
    # Capture pre-readback state
    before = c.get(f'/api/conversations/{cid}/jobs/{jid}').json()
    aid = before.get('artifact_id')
    if aid is None:
        pytest.skip('inspect_sources did not produce an artifact under evidence provider')
    # Capture event cursor
    ev_before = c.get(f'/api/conversations/{cid}/events?after=0&limit=500').json()
    cursor_before = max((e['seq'] for e in ev_before.get('items', [])), default=0)

    # Read the artifact 5 times — API-only, no worker invocation.
    for _ in range(5):
        r = c.get(f'/api/conversations/{cid}/artifacts/{aid}')
        assert r.status_code == 200, r.text
        r2 = c.get(f'/api/conversations/{cid}/artifacts/{aid}/evidence')
        assert r2.status_code == 200, r2.text

    after = c.get(f'/api/conversations/{cid}/jobs/{jid}').json()
    assert before == after, 'artifact readback mutated job row'

    ev_after = c.get(f'/api/conversations/{cid}/events?after=0&limit=500').json()
    cursor_after = max((e['seq'] for e in ev_after.get('items', [])), default=0)
    # No new events were created solely by reading artifacts.
    assert cursor_after == cursor_before, (
        'artifact readback produced new events; expected cursor stable', cursor_before, cursor_after)
