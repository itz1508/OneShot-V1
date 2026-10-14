"""Independent adversarial fixture matrix — directive v6.0.4 §4.

Each test asserts a specific negative/positive invariant. Expected answers are defined by
the test, not by the system under test. These are NOT a replacement for the existing
regression tests — they complement them with scenarios the directive lists verbatim.
"""
import time

import pytest
from fastapi.testclient import TestClient

from systems.settings import Settings
from systems.api import create_app


PW = 'adv-pw-16chars-aaa0'


def _login(tmp_path, request=None):
    cfg = Settings(data_dir=tmp_path, api_token='s' * 32, browser_password=PW)
    app = create_app(cfg, auto_worker=True)
    tc = TestClient(app).__enter__()
    if request is not None:
        request.addfinalizer(lambda: tc.__exit__(None, None, None))
    tc.post('/auth/login', json={'password': PW})
    tc.headers['x-oneshot-csrf'] = tc.get('/auth/session').json()['csrf']
    return tc


def _mk_terminal_job(c, cid, body='adv body', idem_tag='adv-aaa'):
    mid = c.post(f'/api/conversations/{cid}/messages',
                 json={'channel': 'system', 'content': 'Objective'}).json()['id']
    s = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'adv.txt', 'content': body})
    sid = s.json()['source_id']; sver = s.json()['version']
    jr = c.post(f'/api/conversations/{cid}/jobs',
                json={'operation': 'inspect_sources', 'source_ids': [sid],
                      'expected_versions': {sid: sver},
                      'idempotency_key': idem_tag,
                      'prompt_message_id': mid}).json()
    jid = jr['id']
    for _ in range(80):
        if c.get(f'/api/conversations/{cid}/jobs/{jid}').json().get('status') in (
                'completed', 'failed', 'blocked'):
            break
        time.sleep(0.1)
    return cid, jid, sid


# ---- Admission + CSRF + Auth ------------------------------------------------

def test_csrf_header_required_for_write_operations(tmp_path, request):
    cfg = Settings(data_dir=tmp_path, api_token='t' * 32, browser_password=PW)
    app = create_app(cfg, auto_worker=False)
    with TestClient(app) as c:
        c.post('/auth/login', json={'password': PW})
        # No X-Oneshot-CSRF header: write must be rejected (403), not accepted.
        r = c.post('/api/conversations', json={'title': 'nope'})
        assert r.status_code in (401, 403), r.status_code


# ---- Prompt publication vs draft-only --------------------------------------

def test_draft_only_change_does_not_publish_a_version(tmp_path, request):
    c = _login(tmp_path, request)
    cid = c.post('/api/conversations', json={'title': 'd'}).json()['id']
    pr = c.post(f'/api/conversations/{cid}/prompts',
                json={'name': 'draft-only', 'content': 'placeholder',
                      'variables': []}).json()
    pid = pr['id']
    # Save several draft revisions
    for i, text in enumerate(('draft one', 'draft two', 'draft three'), start=1):
        r = c.patch(f'/api/conversations/{cid}/prompts/{pid}/draft',
                    json={'content': text, 'variables': [], 'expected_revision': i})
        assert r.status_code == 200, r.text
    # No publish — latest_version must remain None.
    detail = c.get(f'/api/conversations/{cid}/prompts/{pid}').json()
    assert detail['latest_version'] is None


# ---- Source + conversation isolation ---------------------------------------

def test_cross_conversation_source_access_is_denied(tmp_path, request):
    c = _login(tmp_path, request)
    cid_a = c.post('/api/conversations', json={'title': 'a'}).json()['id']
    cid_b = c.post('/api/conversations', json={'title': 'b'}).json()['id']
    s = c.post(f'/api/conversations/{cid_a}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'secret.txt', 'content': 'secret'})
    sid = s.json()['source_id']
    r = c.get(f'/api/conversations/{cid_b}/sources/{sid}/content')
    assert r.status_code == 404, r.text


# ---- Duplicate requests + idempotency --------------------------------------

def test_duplicate_job_submission_is_idempotent(tmp_path, request):
    """Replay the EXACT same job body (same scope + same idempotency_key) and verify the
    server returns reused=True rather than creating a second job."""
    c = _login(tmp_path, request)
    import time
    cid = c.post('/api/conversations', json={'title': 'idem'}).json()['id']
    s = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'adv.txt', 'content': 'adv body'}).json()
    mid = c.post(f'/api/conversations/{cid}/messages',
                 json={'channel': 'system', 'content': 'Objective'}).json()['id']
    body = {'operation': 'inspect_sources', 'source_ids': [s['source_id']],
            'expected_versions': {s['source_id']: s['version']},
            'idempotency_key': 'dupe-aaa', 'prompt_message_id': mid}
    r1 = c.post(f'/api/conversations/{cid}/jobs', json=body)
    assert r1.status_code in (200, 202, 201), r1.text
    jid1 = r1.json()['id']
    # Wait for terminal before resubmission so the reuse path exercises the completed row.
    for _ in range(80):
        if c.get(f'/api/conversations/{cid}/jobs/{jid1}').json().get('status') in (
                'completed', 'failed', 'blocked'):
            break
        time.sleep(0.1)
    # Resubmit the EXACT same body.
    r2 = c.post(f'/api/conversations/{cid}/jobs', json=body)
    assert r2.status_code in (200, 202, 201), r2.text
    assert r2.json()['id'] == jid1, (r1.json(), r2.json())
    assert r2.json().get('reused') is True, r2.json()


# ---- Malicious variable content treated strictly as data -------------------

def test_prompt_variable_values_treated_as_data(tmp_path, request):
    """Variable VALUES must never be interpreted as new template directives."""
    c = _login(tmp_path, request)
    cid = c.post('/api/conversations', json={'title': 'inj'}).json()['id']
    pr = c.post(f'/api/conversations/{cid}/prompts',
                json={'name': 'inj', 'content': 'Summarize ${payload}.',
                      'variables': [{'name': 'payload'}]}).json()
    pid = pr['id']
    pub = c.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={}).json()
    assert pub['version_number'] == 1
    # Resolve with an "injected" payload. The resolver substitutes verbatim; it must not
    # re-parse `${payload}` out of the substituted content.
    r = c.post(f'/api/conversations/{cid}/prompts/{pid}/resolve',
               json={'version': 1, 'values': {'payload': '${hidden} and ${not_a_variable}'}})
    assert r.status_code == 200, r.text
    out = r.json()['resolved_content']
    assert '${hidden}' in out, out
    assert '${not_a_variable}' in out, out


# ---- Unauthorized scope expansion ------------------------------------------

def test_job_cannot_reference_source_from_other_conversation(tmp_path, request):
    c = _login(tmp_path, request)
    cid_a = c.post('/api/conversations', json={'title': 'a'}).json()['id']
    cid_b = c.post('/api/conversations', json={'title': 'b'}).json()['id']
    s_a = c.post(f'/api/conversations/{cid_a}/sources/actions',
                 json={'action': 'INPUT_SOURCE', 'name': 'a.txt', 'content': 'a'}).json()
    # Reference it from cid_b — must be rejected.
    r = c.post(f'/api/conversations/{cid_b}/jobs',
               json={'operation': 'inspect_sources', 'source_ids': [s_a['source_id']],
                     'expected_versions': {s_a['source_id']: s_a['version']},
                     'idempotency_key': 'cross-aaa'})
    assert r.status_code in (400, 404, 422), r.text


# ---- Review + evaluation + proposal lifecycle regressions (gaps) ----------

def test_evaluation_without_approval_cannot_run(tmp_path, request):
    c = _login(tmp_path, request)
    cid, jid, _ = _mk_terminal_job(c, c.post('/api/conversations', json={'title': 'ev'}).json()['id'])
    e = c.post(f'/api/conversations/{cid}/jobs/{jid}/evaluations',
               json={'status': 'proposed', 'criteria': [{'kind': 'contains', 'value': 'x'}]}).json()
    r = c.post(f'/api/conversations/{cid}/job-evaluations/{e["id"]}/run')
    assert r.status_code in (400, 409), r.text


def test_proposal_cannot_jump_to_implemented(tmp_path, request):
    c = _login(tmp_path, request)
    cid = c.post('/api/conversations', json={'title': 'p'}).json()['id']
    p = c.post(f'/api/conversations/{cid}/improvement-proposals',
               json={'issue_summary': 'x', 'affected_responsibility': 'y',
                     'current_behavior': '', 'required_behavior': '',
                     'proposed_correction': '', 'risks': '', 'evidence': {}}).json()
    r = c.post(f'/api/conversations/{cid}/improvement-proposals/{p["id"]}/implemented')
    assert r.status_code in (400, 409), r.text


# ---- Evidence provenance + replay (readback does not advance state) --------

def test_evidence_bundle_lists_scope_sources(tmp_path, request):
    c = _login(tmp_path, request)
    cid, jid, sid = _mk_terminal_job(c, c.post('/api/conversations', json={'title': 'ev'}).json()['id'])
    job = c.get(f'/api/conversations/{cid}/jobs/{jid}').json()
    aid = job.get('artifact_id')
    if aid is None:
        pytest.skip('no artifact produced under evidence provider')
    bundle = c.get(f'/api/conversations/{cid}/artifacts/{aid}/evidence').json()
    assert any(s.get('source_id') == sid or s.get('id') == sid for s in (bundle.get('sources') or [])), bundle


# ---- Provider failure and malformed model output ---------------------------

def test_optimizer_without_configured_provider_returns_503(tmp_path, request):
    c = _login(tmp_path, request)
    cid = c.post('/api/conversations', json={'title': 'opt'}).json()['id']
    pr = c.post(f'/api/conversations/{cid}/prompts',
                json={'name': 'opt', 'content': 'Summarize ${source}.',
                      'variables': [{'name': 'source'}]}).json()
    pid = pr['id']
    c.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={})
    r = c.post(f'/api/conversations/{cid}/prompts/{pid}/optimizations', json={})
    assert r.status_code == 503, r.text
