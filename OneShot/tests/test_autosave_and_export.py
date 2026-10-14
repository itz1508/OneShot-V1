"""Regression tests for autosave (draft discovery) and CSV export."""
from pathlib import Path
import csv, io, time
from systems.settings import Settings
from systems.api import create_app
from fastapi.testclient import TestClient
import pytest


PW = 'autosave-pw-16-chars-aaaa'


@pytest.fixture
def client(tmp_path: Path):
    cfg = Settings(data_dir=tmp_path, api_token='a' * 32, browser_password=PW)
    app = create_app(cfg, auto_worker=True)
    return app


def _login(app):
    c = TestClient(app).__enter__()
    r = c.post('/auth/login', json={'password': PW})
    assert r.status_code == 200, r.text
    c.headers['x-oneshot-csrf'] = r.json()['csrf']
    return c


# -- Autosave: draft discovery on refresh ---------------------------------


def test_source_draft_latest_returns_404_when_no_draft(client):
    c = _login(client)
    cid = c.post('/api/conversations', json={'title': 'd'}).json()['id']
    r = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'a.txt', 'content': 'original'})
    sid = r.json()['source_id']
    r = c.get(f'/api/conversations/{cid}/sources/{sid}/draft')
    assert r.status_code == 404


def test_source_draft_latest_returns_most_recent_revision(client):
    c = _login(client)
    cid = c.post('/api/conversations', json={'title': 'd'}).json()['id']
    r = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'a.txt', 'content': 'original'})
    sid = r.json()['source_id']
    r = c.post(f'/api/conversations/{cid}/drafts', json={'source_id': sid, 'content': 'rev1'})
    did = r.json()['id']
    c.patch(f'/api/conversations/{cid}/drafts/{did}',
            json={'expected_revision': 1, 'content': 'rev2'})
    c.patch(f'/api/conversations/{cid}/drafts/{did}',
            json={'expected_revision': 2, 'content': 'rev3'})
    r = c.get(f'/api/conversations/{cid}/sources/{sid}/draft')
    assert r.status_code == 200
    assert r.json() == {'id': did, 'revision': 3, 'content': 'rev3'}


def test_source_draft_latest_rejects_cross_conversation(client):
    c = _login(client)
    a = c.post('/api/conversations', json={'title': 'a'}).json()['id']
    b = c.post('/api/conversations', json={'title': 'b'}).json()['id']
    r = c.post(f'/api/conversations/{a}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'x.txt', 'content': 'A'})
    sid = r.json()['source_id']
    c.post(f'/api/conversations/{a}/drafts', json={'source_id': sid, 'content': 'A-rev1'})
    r = c.get(f'/api/conversations/{b}/sources/{sid}/draft')
    # Source not in B's scope -> 404 (not 403) from source() guard
    assert r.status_code == 404


# -- CSV export -----------------------------------------------------------


def _wait_terminal(c, cid, jid, max_s=10):
    for _ in range(int(max_s * 10)):
        st = c.get(f'/api/conversations/{cid}/jobs/{jid}').json().get('status')
        if st in ('completed', 'failed', 'blocked'):
            return st
        time.sleep(0.1)
    raise AssertionError(f'Job {jid} did not terminate within {max_s}s')


def test_export_csv_rfc_4180_shape(client):
    c = _login(client)
    cid = c.post('/api/conversations', json={'title': 't'}).json()['id']
    mid = c.post(f'/api/conversations/{cid}/messages',
                 json={'channel': 'system', 'content': 'Objective, "quoted", 100%'}).json()['id']
    r = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'with,comma.txt', 'content': 'body'})
    sid = r.json()['source_id']; sver = r.json()['version']
    r = c.post(f'/api/conversations/{cid}/jobs',
               json={'operation': 'inspect_sources', 'source_ids': [sid],
                     'expected_versions': {sid: sver},
                     'idempotency_key': 'csv-aaaaaa', 'prompt_message_id': mid})
    jid = r.json()['id']
    _wait_terminal(c, cid, jid)
    r = c.get(f'/api/conversations/{cid}/jobs/export')
    assert r.status_code == 200
    assert r.headers['content-type'].startswith('text/csv')
    assert r.headers['content-disposition'].startswith('attachment; filename="oneshot-run-history-')
    assert r.headers['x-total'] == '1'
    rows = list(csv.reader(io.StringIO(r.text)))
    assert len(rows) == 2, rows
    header, data = rows
    assert header == ['job_id','operation','status','created_at','updated_at',
                      'objective_preview','source_names','source_versions',
                      'source_sha256s','source_ids','artifact_id','artifact_sha256',
                      'artifact_kind','artifact_provider','limitations','reason',
                      'inspection_modes','vision_model_ids'], header
    assert data[0] == jid
    assert data[5].startswith('Objective, "quoted"')  # comma + quote preserved
    assert data[6] == 'with,comma.txt'                # comma preserved in CSV cell
    assert data[8]                                     # source_sha256 present


def test_export_csv_respects_search_filter(client):
    c = _login(client)
    cid = c.post('/api/conversations', json={'title': 't'}).json()['id']
    for i in range(3):
        mid = c.post(f'/api/conversations/{cid}/messages',
                     json={'channel': 'system', 'content': f'Objective {i} zephyr'}).json()['id']
        s = c.post(f'/api/conversations/{cid}/sources/actions',
                   json={'action': 'INPUT_SOURCE', 'name': f's{i}.txt', 'content': f'body-{i}'})
        sid = s.json()['source_id']; sver = s.json()['version']
        c.post(f'/api/conversations/{cid}/jobs',
               json={'operation': 'inspect_sources', 'source_ids': [sid],
                     'expected_versions': {sid: sver},
                     'idempotency_key': f'csv-filter-{i}aa', 'prompt_message_id': mid})
    # Search filter restricts the CSV too
    r = c.get(f'/api/conversations/{cid}/jobs/export?query=Objective 1')
    assert r.status_code == 200
    rows = list(csv.reader(io.StringIO(r.text)))
    assert len(rows) == 2, rows  # header + 1 match
    assert 'Objective 1' in rows[1][5]
    # No match
    r = c.get(f'/api/conversations/{cid}/jobs/export?query=xyznope')
    rows = list(csv.reader(io.StringIO(r.text)))
    assert len(rows) == 1  # header only


def test_export_csv_sanitises_control_chars(client):
    """Any control chars from artifact content must be stripped so CSV stays well-formed."""
    c = _login(client)
    cid = c.post('/api/conversations', json={'title': 't'}).json()['id']
    mid = c.post(f'/api/conversations/{cid}/messages',
                 json={'channel': 'system',
                       'content': 'Obj with\x00NUL and\x1fUS'}).json()['id']
    r = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 'ok.txt', 'content': 'body'})
    sid = r.json()['source_id']; sver = r.json()['version']
    r = c.post(f'/api/conversations/{cid}/jobs',
               json={'operation': 'inspect_sources', 'source_ids': [sid],
                     'expected_versions': {sid: sver},
                     'idempotency_key': 'csv-sanitise-aa', 'prompt_message_id': mid})
    _wait_terminal(c, cid, r.json()['id'])
    r = c.get(f'/api/conversations/{cid}/jobs/export')
    rows = list(csv.reader(io.StringIO(r.text)))
    # The objective preview must NOT contain control chars (except tab).
    assert all(c == '\t' or ord(c) >= 32 for c in rows[1][5]), repr(rows[1][5])


def test_export_requires_authentication(tmp_path):
    cfg = Settings(data_dir=tmp_path, api_token='a' * 32, browser_password=PW)
    app = create_app(cfg, auto_worker=False)
    c = TestClient(app)
    r = c.get('/api/conversations/anything/jobs/export')
    assert r.status_code == 401
