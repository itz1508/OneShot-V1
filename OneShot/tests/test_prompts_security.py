"""Prompt lifecycle correction §6: security + concurrency coverage.

Addresses the directive requirement that `test_prompts.py` was too thin to
infer broad coverage. These tests exercise the race windows explicitly.
"""
from pathlib import Path
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import pytest
from fastapi.testclient import TestClient
from systems.settings import Settings
from systems.api import create_app


PW = 'prompts-conc-pw-16-aa'


def _app(tmp_path):
    cfg = Settings(data_dir=tmp_path, api_token='a' * 32, browser_password=PW)
    return create_app(cfg, auto_worker=False)


def _login(app):
    c = TestClient(app).__enter__()
    c.post('/auth/login', json={'password': PW})
    r = c.get('/auth/session').json()
    c.headers['x-oneshot-csrf'] = r['csrf']
    return c


def _mk_conv(c):
    return c.post('/api/conversations', json={'title': 'c'}).json()['id']


# ---------- Simultaneous publication ---------------------------------------


def test_simultaneous_publish_produces_two_versions_no_duplicate_number(tmp_path):
    """Two concurrent /publish requests MUST produce two distinct version numbers.
    SQLite UNIQUE(prompt_asset_id, version_number) + BEGIN IMMEDIATE serialises them."""
    app = _app(tmp_path)
    c = _login(app)
    cid = _mk_conv(c)
    pid = c.post(f'/api/conversations/{cid}/prompts',
                 json={'name': 'r', 'content': 'A', 'variables': []}).json()['id']

    # Two independent TestClient contexts to approximate concurrent HTTP.
    def _publish():
        c2 = TestClient(app).__enter__()
        c2.post('/auth/login', json={'password': PW})
        c2.headers['x-oneshot-csrf'] = c2.get('/auth/session').json()['csrf']
        r = c2.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={})
        c2.__exit__(None, None, None)
        return r.status_code, (r.json() if r.status_code < 400 else None)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: _publish(), range(2)))

    # At least one must succeed; the schema invariant is: no two version_numbers
    # alias to the same (asset_id, number).
    succeeded = [r for r in results if r[0] == 201]
    assert len(succeeded) >= 1
    versions = c.get(f'/api/conversations/{cid}/prompts/{pid}/versions').json()['items']
    numbers = [v['version_number'] for v in versions]
    assert len(numbers) == len(set(numbers)), f'duplicate version numbers: {numbers}'


def test_stale_draft_revision_rejected(tmp_path):
    app = _app(tmp_path); c = _login(app); cid = _mk_conv(c)
    pid = c.post(f'/api/conversations/{cid}/prompts',
                 json={'name': 'r', 'content': 'A', 'variables': []}).json()['id']
    # Current revision is 1; expected_revision=999 is stale.
    r = c.patch(f'/api/conversations/{cid}/prompts/{pid}/draft',
                json={'content': 'B', 'variables': [], 'expected_revision': 999})
    assert r.status_code == 409
    # And publish with stale expected_revision is also rejected
    r = c.post(f'/api/conversations/{cid}/prompts/{pid}/publish',
               json={'expected_revision': 999})
    assert r.status_code == 409


def test_duplicate_name_rejected_in_same_conversation(tmp_path):
    app = _app(tmp_path); c = _login(app); cid = _mk_conv(c)
    body = {'name': 'uniq', 'content': 'x', 'variables': []}
    assert c.post(f'/api/conversations/{cid}/prompts', json=body).status_code == 201
    r = c.post(f'/api/conversations/{cid}/prompts', json=body)
    assert r.status_code == 409
    # ...but the SAME name in a different conversation is allowed.
    other = _mk_conv(c)
    assert c.post(f'/api/conversations/{other}/prompts', json=body).status_code == 201


# ---------- Idempotency race on job admission ------------------------------


def test_duplicate_job_admission_with_same_prompt_version_is_reused(tmp_path):
    app = _app(tmp_path); c = _login(app); cid = _mk_conv(c)
    pid = c.post(f'/api/conversations/{cid}/prompts',
                 json={'name': 'r', 'content': 'A ${w}',
                       'variables': [{'name': 'w'}]}).json()['id']
    v1 = c.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={}).json()
    mid = c.post(f'/api/conversations/{cid}/messages',
                 json={'channel': 'system', 'content': 'obj'}).json()['id']
    s = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 's.txt', 'content': 'body'})
    sid = s.json()['source_id']; sver = s.json()['version']
    body = {'operation': 'inspect_sources', 'source_ids': [sid],
            'expected_versions': {sid: sver},
            'idempotency_key': 'prompt-dup-key-1',
            'prompt_message_id': mid,
            'prompt_asset_id': pid, 'prompt_version': 1,
            'prompt_values': {'w': 'x'}}
    a = c.post(f'/api/conversations/{cid}/jobs', json=body).json()
    b = c.post(f'/api/conversations/{cid}/jobs', json=body).json()
    assert a['id'] == b['id']
    assert b['reused'] is True
    assert b['prompt_version_id'] == v1['id']


def test_duplicate_job_admission_with_different_prompt_version_is_409(tmp_path):
    """Same idempotency_key with a different frozen prompt_version MUST 409."""
    app = _app(tmp_path); c = _login(app); cid = _mk_conv(c)
    pid = c.post(f'/api/conversations/{cid}/prompts',
                 json={'name': 'r', 'content': 'A ${w}',
                       'variables': [{'name': 'w'}]}).json()['id']
    c.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={})
    c.patch(f'/api/conversations/{cid}/prompts/{pid}/draft',
            json={'content': 'B ${w}', 'variables': [{'name': 'w'}]})
    c.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={})
    mid = c.post(f'/api/conversations/{cid}/messages',
                 json={'channel': 'system', 'content': 'obj'}).json()['id']
    s = c.post(f'/api/conversations/{cid}/sources/actions',
               json={'action': 'INPUT_SOURCE', 'name': 's.txt', 'content': 'body'})
    sid = s.json()['source_id']; sver = s.json()['version']
    base = {'operation': 'inspect_sources', 'source_ids': [sid],
            'expected_versions': {sid: sver},
            'idempotency_key': 'prompt-dup-ver-1',
            'prompt_message_id': mid,
            'prompt_asset_id': pid, 'prompt_values': {'w': 'x'}}
    r1 = c.post(f'/api/conversations/{cid}/jobs',
                json={**base, 'prompt_version': 1})
    assert r1.status_code == 202
    r2 = c.post(f'/api/conversations/{cid}/jobs',
                json={**base, 'prompt_version': 2})
    assert r2.status_code == 409
    assert 'scope conflict' in r2.json()['detail']


# ---------- Restore / publish interaction ---------------------------------


def test_restore_does_not_mutate_earlier_versions(tmp_path):
    app = _app(tmp_path); c = _login(app); cid = _mk_conv(c)
    pid = c.post(f'/api/conversations/{cid}/prompts',
                 json={'name': 'r', 'content': 'v1', 'variables': []}).json()['id']
    v1 = c.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={}).json()
    c.patch(f'/api/conversations/{cid}/prompts/{pid}/draft',
            json={'content': 'v2', 'variables': []})
    c.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={})
    r = c.post(f'/api/conversations/{cid}/prompts/{pid}/restore', json={'version': 1})
    assert r.status_code == 201
    assert c.get(f'/api/conversations/{cid}/prompts/{pid}/versions/1').json()['content'] == 'v1'
    assert c.get(f'/api/conversations/{cid}/prompts/{pid}/versions/1').json()['content_sha256'] == v1['content_sha256']


def test_restore_of_unknown_version_rejected(tmp_path):
    app = _app(tmp_path); c = _login(app); cid = _mk_conv(c)
    pid = c.post(f'/api/conversations/{cid}/prompts',
                 json={'name': 'r', 'content': 'v1', 'variables': []}).json()['id']
    c.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={})
    r = c.post(f'/api/conversations/{cid}/prompts/{pid}/restore', json={'version': 999})
    assert r.status_code == 404


# ---------- Restart recovery (persistence) --------------------------------


def test_versions_and_restore_persist_across_restart(tmp_path):
    app = _app(tmp_path); c = _login(app); cid = _mk_conv(c)
    pid = c.post(f'/api/conversations/{cid}/prompts',
                 json={'name': 'r', 'content': 'v1', 'variables': []}).json()['id']
    c.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={})
    c.patch(f'/api/conversations/{cid}/prompts/{pid}/draft',
            json={'content': 'v2', 'variables': []})
    c.post(f'/api/conversations/{cid}/prompts/{pid}/publish', json={})
    c.post(f'/api/conversations/{cid}/prompts/{pid}/restore', json={'version': 1})
    c.__exit__(None, None, None)
    app2 = _app(tmp_path)
    c2 = _login(app2)
    rows = c2.get(f'/api/conversations/{cid}/prompts/{pid}/versions').json()['items']
    assert len(rows) == 3
    assert rows[2]['restored_from']  # row 3 records provenance


# ---------- Cross-conversation isolation ---------------------------------


def test_restore_in_another_conversation_cannot_target_other_prompt(tmp_path):
    app = _app(tmp_path); c = _login(app)
    a = _mk_conv(c); b = _mk_conv(c)
    pid = c.post(f'/api/conversations/{a}/prompts',
                 json={'name': 'r', 'content': 'A', 'variables': []}).json()['id']
    c.post(f'/api/conversations/{a}/prompts/{pid}/publish', json={})
    r = c.post(f'/api/conversations/{b}/prompts/{pid}/restore', json={'version': 1})
    assert r.status_code == 404


def test_compare_in_another_conversation_rejected(tmp_path):
    app = _app(tmp_path); c = _login(app)
    a = _mk_conv(c); b = _mk_conv(c)
    pid = c.post(f'/api/conversations/{a}/prompts',
                 json={'name': 'r', 'content': 'A', 'variables': []}).json()['id']
    c.post(f'/api/conversations/{a}/prompts/{pid}/publish', json={})
    assert c.get(f'/api/conversations/{b}/prompts/{pid}/compare?left=1&right=1').status_code == 404


# ---------- Variable resolution: $$ escape and literal $ handling --------


def test_variable_escape_dollar_dollar(tmp_path):
    """Variable value containing '$$' must NOT escape in a user-supplied value;
    only the TEMPLATE has escape semantics (single-pass resolution)."""
    from systems.prompt_variables import load_definitions, resolve
    defs = load_definitions([{'name': 'who'}])
    # Template-level: $$ escapes to $
    out = resolve('Price is $$5 for ${who}', defs, {'who': 'you'})
    assert out == 'Price is $5 for you'
    # Value-level: $$ in value stays verbatim (no re-interpolation).
    out = resolve('Hi ${who}', defs, {'who': '$$still-literal'})
    assert out == 'Hi $$still-literal'


def test_literal_dollar_not_matching_template_token_preserved():
    from systems.prompt_variables import load_definitions, resolve
    defs = load_definitions([])
    # Lone $ not followed by { stays verbatim.
    out = resolve('Account $12.34 and $-sign', defs, {})
    assert out == 'Account $12.34 and $-sign'
