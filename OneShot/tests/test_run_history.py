"""Regression tests for conversation-scoped job search + filter."""
from pathlib import Path
import json
from systems.settings import Settings
from systems.api import create_app
from fastapi.testclient import TestClient
import pytest


@pytest.fixture
def client(tmp_path: Path):
    cfg = Settings(data_dir=tmp_path, api_token='a' * 32, browser_password='rh-pw-test-16-chars-pls')
    app = create_app(cfg, auto_worker=False)
    c = TestClient(app)
    r = c.post('/auth/login', json={'password': 'rh-pw-test-16-chars-pls'})
    assert r.status_code == 200, r.text
    c.headers['x-oneshot-csrf'] = r.json()['csrf']
    return c


def _conv(c, title='t'):
    r = c.post('/api/conversations', json={'title': title}); assert r.status_code == 201, r.text
    return r.json()['id']


def test_list_jobs_requires_authentication(tmp_path):
    cfg = Settings(data_dir=tmp_path, api_token='a' * 32, browser_password='x-pw-16-chars-at-least')
    app = create_app(cfg, auto_worker=False)
    c = TestClient(app)
    r = c.get('/api/conversations/does-not-matter/jobs')
    assert r.status_code == 401


def test_list_jobs_rejects_bad_limits(client):
    cid = _conv(client)
    r = client.get(f'/api/conversations/{cid}/jobs?limit=0')
    assert r.status_code == 422
    r = client.get(f'/api/conversations/{cid}/jobs?limit=51')
    assert r.status_code == 422
    r = client.get(f'/api/conversations/{cid}/jobs?offset=-1')
    assert r.status_code == 422


def test_list_jobs_empty_for_fresh_conversation(client):
    cid = _conv(client)
    r = client.get(f'/api/conversations/{cid}/jobs?limit=10')
    assert r.status_code == 200
    assert r.json() == {'items': [], 'total': 0, 'limit': 10, 'offset': 0}


def test_search_matches_objective_source_name_and_escapes_wildcards(client):
    cid = _conv(client)
    r = client.post(f'/api/conversations/{cid}/messages',
                    json={'channel': 'system', 'content': 'Summarize the harbor Copper Lantern'})
    mid = r.json()['id']
    r = client.post(f'/api/conversations/{cid}/sources/actions',
                    json={'action': 'INPUT_SOURCE', 'name': 'harbor.txt',
                          'content': 'The Copper Lantern illuminated the harbor.'})
    d = r.json(); sid = d['source_id']; sver = d['version']
    r = client.post(f'/api/conversations/{cid}/jobs',
                    json={'operation': 'summarize', 'source_ids': [sid],
                          'expected_versions': {sid: sver},
                          'idempotency_key': 'rh-test-key-6',
                          'prompt_message_id': mid})
    assert r.status_code == 202, r.text
    # List returns 1
    r = client.get(f'/api/conversations/{cid}/jobs?limit=10')
    assert r.json()['total'] == 1
    item = r.json()['items'][0]
    assert item['operation'] == 'summarize'
    assert item['objective_preview'].startswith('Summarize the harbor')
    assert len(item['sources']) == 1
    s = item['sources'][0]
    assert s['id'] == sid
    assert s['name'] == 'harbor.txt'
    assert s['version'] == sver
    assert s['sha256']  # non-empty hex
    # Search by objective text
    r = client.get(f'/api/conversations/{cid}/jobs?query=Copper')
    assert r.json()['total'] == 1
    # Search by source filename
    r = client.get(f'/api/conversations/{cid}/jobs?query=harbor.txt')
    assert r.json()['total'] == 1
    # Status filter -- a POST-only queued job
    r = client.get(f'/api/conversations/{cid}/jobs?status=queued')
    assert r.json()['total'] == 1
    r = client.get(f'/api/conversations/{cid}/jobs?status=completed')
    assert r.json()['total'] == 0
    # Literal wildcard: '%' must not match everything
    r = client.get(f'/api/conversations/{cid}/jobs?query=%25')
    assert r.json()['total'] == 0, 'SQL LIKE wildcard leak: literal % matched everything'
    r = client.get(f'/api/conversations/{cid}/jobs?query=_')
    assert r.json()['total'] == 0, 'SQL LIKE wildcard leak: literal _ matched everything'


def test_cross_conversation_isolation(client):
    a = _conv(client, 'a')
    b = _conv(client, 'b')
    client.post(f'/api/conversations/{a}/messages',
                json={'channel': 'system', 'content': 'Secret-A about zephyrs'})
    r = client.post(f'/api/conversations/{a}/sources/actions',
                    json={'action': 'INPUT_SOURCE', 'name': 'a.txt', 'content': 'zephyr'})
    d = r.json()
    r = client.post(f'/api/conversations/{a}/messages',
                    json={'channel': 'system', 'content': 'process A'})
    mid = r.json()['id']
    r = client.post(f'/api/conversations/{a}/jobs',
                    json={'operation': 'summarize', 'source_ids': [d['source_id']],
                          'expected_versions': {d['source_id']: d['version']},
                          'idempotency_key': 'iso-test-key-abc',
                          'prompt_message_id': mid})
    assert r.status_code == 202, r.text
    # Conversation A sees it
    r = client.get(f'/api/conversations/{a}/jobs?limit=10')
    assert r.json()['total'] == 1
    # Conversation B does NOT, even with a matching search term
    r = client.get(f'/api/conversations/{b}/jobs?limit=10')
    assert r.json()['total'] == 0
    r = client.get(f'/api/conversations/{b}/jobs?query=zephyr')
    assert r.json()['total'] == 0
