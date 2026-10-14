"""I05 — Advisory model analysis integration contract (runtime-independent).

With `ONESHOT_PROVIDER='evidence'` (the default) the server MUST refuse to
synthesize advisory evidence: it returns HTTP 503 with the exact
`MODEL_RUNTIME_UNAVAILABLE` marker and the missing-prerequisite string. No
`improvement_proposals` row is written.

Real I05 inference is a separate receiver-side step; see
`docs/phase_records/v6-phase8-advisory-receiver-runbook.md` for the exact
command.
"""
import pytest
from fastapi.testclient import TestClient

from systems.settings import Settings
from systems.api import create_app


PW = 'i05-pw-16-chars-okok'


def _login(tmp_path, request=None):
    cfg = Settings(data_dir=tmp_path, api_token='b' * 32, browser_password=PW)
    app = create_app(cfg, auto_worker=True)
    tc = TestClient(app).__enter__()
    if request is not None:
        request.addfinalizer(lambda: tc.__exit__(None, None, None))
    tc.post('/auth/login', json={'password': PW})
    tc.headers['x-oneshot-csrf'] = tc.get('/auth/session').json()['csrf']
    return tc


def _terminal_job(c):
    cid = c.post('/api/conversations', json={'title': 'i05'}).json()['id']
    mid = c.post(f'/api/conversations/{cid}/messages',
                 json={'channel': 'system', 'content': 'Objective'}).json()['id']
    s = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'x.txt',
                     'content': 'ground truth body'})
    sid = s.json()['source_id']; sver = s.json()['version']
    r = c.post(f'/api/conversations/{cid}/jobs',
               json={'operation': 'inspect_sources', 'source_ids': [sid],
                     'expected_versions': {sid: sver},
                     'idempotency_key': 'i05-aaa',
                     'prompt_message_id': mid})
    jid = r.json()['id']
    import time
    for _ in range(80):
        if c.get(f'/api/conversations/{cid}/jobs/{jid}').json().get('status') \
                in ('completed', 'failed', 'blocked'):
            break
        time.sleep(0.1)
    return cid, jid


def test_i05_advisory_requires_configured_provider(tmp_path, request):
    c = _login(tmp_path, request)
    cid, jid = _terminal_job(c)
    before = c.get(f'/api/conversations/{cid}/improvement-proposals').json()
    pre_count = len(before.get('items', []))

    r = c.post(f'/api/conversations/{cid}/jobs/{jid}/advisory-analysis')
    assert r.status_code == 503, (r.status_code, r.text)
    body = r.json()['detail']
    assert body['detail'] == 'MODEL_RUNTIME_UNAVAILABLE', body
    assert "ONESHOT_PROVIDER" in body['missing_prerequisite'], body

    # No fabricated proposal was written.
    after = c.get(f'/api/conversations/{cid}/improvement-proposals').json()
    assert len(after.get('items', [])) == pre_count


def test_i05_advisory_unknown_job_rejected(tmp_path, request):
    c = _login(tmp_path, request)
    cid, _jid = _terminal_job(c)
    r = c.post(f'/api/conversations/{cid}/jobs/{"j"*32}/advisory-analysis')
    # Must refuse at the server (not fabricate), independent of provider.
    assert r.status_code in (404, 503), (r.status_code, r.text)


def test_i05_advisory_requires_auth(tmp_path, request):
    cfg = Settings(data_dir=tmp_path, api_token='c' * 32, browser_password=PW)
    app = create_app(cfg, auto_worker=False)
    with TestClient(app) as c:
        r = c.post(f'/api/conversations/{"c"*32}/jobs/{"j"*32}/advisory-analysis')
        assert r.status_code in (401, 403, 404), r.text
