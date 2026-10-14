"""Regression: Phase 2-5 improvement loop (reviews + evaluations + proposals)."""
from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient

from systems.settings import Settings
from systems.api import create_app


PW = 'imp-loop-pw-16-chars-aa'


def _app(tmp_path, auto_worker=False):
    cfg = Settings(data_dir=tmp_path, api_token='a' * 32, browser_password=PW)
    return create_app(cfg, auto_worker=auto_worker)


def _login(app):
    c = TestClient(app).__enter__()
    c.post('/auth/login', json={'password': PW})
    c.headers['x-oneshot-csrf'] = c.get('/auth/session').json()['csrf']
    return c


def _terminal_job(app):
    c = _login(app)
    cid = c.post('/api/conversations', json={'title': 'imp'}).json()['id']
    mid = c.post(f'/api/conversations/{cid}/messages',
                 json={'channel': 'system', 'content': 'Objective'}).json()['id']
    s = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'x.txt', 'content': 'body-content'})
    sid = s.json()['source_id']; sver = s.json()['version']
    r = c.post(f'/api/conversations/{cid}/jobs',
               json={'operation': 'inspect_sources', 'source_ids': [sid],
                     'expected_versions': {sid: sver},
                     'idempotency_key': 'imp-aaa-bbb',
                     'prompt_message_id': mid})
    jid = r.json()['id']
    for _ in range(80):
        if c.get(f'/api/conversations/{cid}/jobs/{jid}').json().get('status') in ('completed','failed','blocked'):
            break
        time.sleep(0.1)
    return c, cid, sid, jid


# ---- I01 trace inspection (API-level sanity) -----------------------------

def test_i01_committed_job_has_trace_and_evidence(tmp_path):
    app = _app(tmp_path, auto_worker=True)
    c, cid, sid, jid = _terminal_job(app)
    r = c.get(f'/api/conversations/{cid}/jobs/{jid}/trace')
    assert r.status_code == 200
    tr = r.json()
    assert tr['job_id'] == jid
    assert any(n.get('status') == 'completed' for n in tr['nodes'])


# ---- I03/I04 operator feedback -------------------------------------------

def test_i03_review_persists_and_cannot_mutate_original_job(tmp_path):
    app = _app(tmp_path, auto_worker=True)
    c, cid, sid, jid = _terminal_job(app)
    prejob = c.get(f'/api/conversations/{cid}/jobs/{jid}').json()
    r = c.put(f'/api/conversations/{cid}/jobs/{jid}/review',
              json={'decision': 'observed_defect',
                    'required': 'Must cite source',
                    'prohibited': 'No fabricated numbers',
                    'reason': 'Missing provenance',
                    'evidence_source_ids': [sid]})
    assert r.status_code == 200, r.text
    rev = r.json()
    assert rev['revision'] == 1
    assert rev['decision'] == 'observed_defect'
    postjob = c.get(f'/api/conversations/{cid}/jobs/{jid}').json()
    assert prejob == postjob, 'review must not mutate job row'
    # Revision update increments
    r = c.put(f'/api/conversations/{cid}/jobs/{jid}/review',
              json={'decision': 'potential_defect', 'required': '', 'prohibited': '',
                    'reason': 'promoted to hypothesis', 'evidence_source_ids': [sid],
                    'expected_revision': 1})
    assert r.status_code == 200
    assert r.json()['revision'] == 2
    # Stale revision rejected
    r = c.put(f'/api/conversations/{cid}/jobs/{jid}/review',
              json={'decision': 'reviewer_expectation', 'required': '',
                    'prohibited': '', 'reason': 'stale', 'expected_revision': 1,
                    'evidence_source_ids': []})
    assert r.status_code == 409


def test_i04_review_rejects_cross_conversation_evidence(tmp_path):
    app = _app(tmp_path, auto_worker=True)
    c, cid, sid, jid = _terminal_job(app)
    # Create a 2nd conversation + source
    other = c.post('/api/conversations', json={'title': 'other'}).json()['id']
    s2 = c.post(f'/api/conversations/{other}/sources/actions',
                json={'action': 'INPUT_SOURCE', 'name': 'y.txt', 'content': 'z'})
    other_sid = s2.json()['source_id']
    r = c.put(f'/api/conversations/{cid}/jobs/{jid}/review',
              json={'decision': 'observed_defect',
                    'evidence_source_ids': [other_sid],
                    'required': '', 'prohibited': '', 'reason': ''})
    assert r.status_code == 422
    # Cross-conversation review attempt
    r = c.put(f'/api/conversations/{other}/jobs/{jid}/review',
              json={'decision': 'observed_defect', 'required': '',
                    'prohibited': '', 'reason': ''})
    assert r.status_code == 404


# ---- I06-I08 evaluation lifecycle ----------------------------------------

def test_i06_evaluation_requires_approval_before_run(tmp_path):
    app = _app(tmp_path, auto_worker=True)
    c, cid, sid, jid = _terminal_job(app)
    r = c.post(f'/api/conversations/{cid}/jobs/{jid}/evaluations',
               json={'status': 'proposed',
                     'criteria': [{'kind': 'quality_outcome', 'value': 'completed'},
                                  {'kind': 'has_source_id', 'value': sid},
                                  {'kind': 'absent', 'value': 'FORBIDDEN'}]})
    assert r.status_code == 201
    eid = r.json()['id']
    run = c.post(f'/api/conversations/{cid}/job-evaluations/{eid}/run')
    assert run.status_code == 409
    app_resp = c.post(f'/api/conversations/{cid}/job-evaluations/{eid}/approve')
    assert app_resp.status_code == 200 and app_resp.json()['status'] == 'approved'
    run = c.post(f'/api/conversations/{cid}/job-evaluations/{eid}/run')
    assert run.status_code == 200, run.text
    findings = run.json()['findings']
    assert findings['passed'] == 3 and findings['failed'] == 0


def test_i07_rejected_criteria_do_not_become_runnable(tmp_path):
    app = _app(tmp_path, auto_worker=True)
    c, cid, sid, jid = _terminal_job(app)
    r = c.post(f'/api/conversations/{cid}/jobs/{jid}/evaluations',
               json={'status': 'proposed',
                     'criteria': [{'kind': 'contains', 'value': 'xyz'}]})
    eid = r.json()['id']
    c.post(f'/api/conversations/{cid}/job-evaluations/{eid}/reject')
    run = c.post(f'/api/conversations/{cid}/job-evaluations/{eid}/run')
    assert run.status_code == 409


# ---- I10 improvement proposal (scope + status transitions) ---------------

def test_i10_proposal_round_trip_and_scope_isolation(tmp_path):
    app = _app(tmp_path, auto_worker=True)
    c, cid, sid, jid = _terminal_job(app)
    other = c.post('/api/conversations', json={'title': 'o'}).json()['id']
    # job_id from a different conversation must be rejected
    r = c.post(f'/api/conversations/{other}/improvement-proposals',
               json={'issue_summary': 'x',
                     'affected_responsibility': 'quality',
                     'evidence': {'job_ids': [jid]}})
    assert r.status_code == 422
    r = c.post(f'/api/conversations/{cid}/improvement-proposals',
               json={'issue_summary': 'Fabrication risk',
                     'affected_responsibility': 'quality.coverage',
                     'current_behavior': 'skips validation',
                     'required_behavior': 'always validate',
                     'proposed_correction': 'raise 409 when stale',
                     'evidence': {'job_ids': [jid]}})
    assert r.status_code == 201, r.text
    pid = r.json()['id']
    # Transitions
    for path, expected in [('accept', 'accepted'),
                           ('implemented', 'implemented')]:
        resp = c.post(f'/api/conversations/{cid}/improvement-proposals/{pid}/{path}')
        assert resp.status_code == 200, resp.text
        assert resp.json()['status'] == expected
    # Rejecting an implemented proposal is 409
    resp = c.post(f'/api/conversations/{cid}/improvement-proposals/{pid}/reject')
    assert resp.status_code == 409


# ---- I11 Apply isolation -------------------------------------------------

def test_i11_improvement_flow_does_not_touch_apply_tables(tmp_path):
    import sqlite3
    app = _app(tmp_path, auto_worker=True)
    c, cid, sid, jid = _terminal_job(app)
    c.put(f'/api/conversations/{cid}/jobs/{jid}/review',
          json={'decision': 'observed_defect', 'required': '',
                'prohibited': '', 'reason': '', 'evidence_source_ids': [sid]})
    r = c.post(f'/api/conversations/{cid}/jobs/{jid}/evaluations',
               json={'status': 'approved',
                     'criteria': [{'kind': 'quality_outcome', 'value': 'completed'}]})
    c.post(f'/api/conversations/{cid}/job-evaluations/{r.json()["id"]}/run')
    r = c.post(f'/api/conversations/{cid}/improvement-proposals',
               json={'issue_summary': 'y', 'affected_responsibility': 'z',
                     'evidence': {'job_ids': [jid]}})
    c.post(f'/api/conversations/{cid}/improvement-proposals/{r.json()["id"]}/accept')
    with sqlite3.connect(tmp_path / 'oneshot.sqlite3') as con:
        n_intent = con.execute('SELECT COUNT(*) FROM apply_intents').fetchone()[0]
        n_applied = con.execute('SELECT COUNT(*) FROM applied').fetchone()[0]
    assert n_intent == 0 and n_applied == 0


# ---- Unauth ---------------------------------------------------------------

def test_improvement_endpoints_require_auth(tmp_path):
    app = _app(tmp_path)
    c = TestClient(app)
    for method, path, body in [
        ('put', '/api/conversations/cccccccccccccccccccccccccccccccc/jobs/jjjjjjjjjjjjjjjjjjjjjjjjjjjjjjjj/review', {'decision':'observed_defect'}),
        ('get', '/api/conversations/cccccccccccccccccccccccccccccccc/reviews', None),
        ('post','/api/conversations/cccccccccccccccccccccccccccccccc/improvement-proposals', {'issue_summary':'x','affected_responsibility':'y'}),
        ('get','/api/conversations/cccccccccccccccccccccccccccccccc/recurring-defects', None),
    ]:
        r = getattr(c, method)(path, json=body) if body else getattr(c, method)(path)
        assert r.status_code == 401, (method, path, r.status_code)
