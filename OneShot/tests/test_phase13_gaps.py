"""Regression tests for v5.3 market-practice gap fixes."""
from pathlib import Path
import time
import pytest
from fastapi.testclient import TestClient
from systems.settings import Settings
from systems.api import create_app


PW = 'gap-fix-pw-16-chars-aa'


def _app(tmp_path):
    cfg = Settings(data_dir=tmp_path, api_token='a' * 32, browser_password=PW)
    return create_app(cfg, auto_worker=False)


# G2
def test_g2_request_id_echoed_or_generated(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as c:
        r = c.get('/health')
        assert r.headers.get('x-request-id'), 'X-Request-Id missing from health'
        assert len(r.headers['x-request-id']) >= 16
        r = c.get('/health', headers={'X-Request-Id': 'test-rid-12345678'})
        assert r.headers['x-request-id'] == 'test-rid-12345678'


# G1
def test_g1_rate_limiter_returns_429_with_retry_after(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as c:
        saw_429 = False
        retry_after = None
        for _ in range(80):
            r = c.get('/health')
            if r.status_code == 429:
                saw_429 = True
                retry_after = r.headers.get('retry-after')
                assert r.headers.get('x-request-id')
                break
        assert saw_429
        assert retry_after and retry_after.isdigit() and int(retry_after) > 0


def _metric_value(body: str, name: str) -> int:
    for line in body.splitlines():
        if line.startswith(f'{name} '):
            return int(line.split()[-1])
    raise AssertionError(f'metric {name} not found in body')


# G3
def test_g3_metrics_prometheus_format(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as c:
        c.get('/health')
        c.get('/metrics')
        r = c.get('/metrics')
        assert r.status_code == 200
        assert r.headers['content-type'].startswith('text/plain')
        body = r.text
        for required in ('oneshot_http_requests_total','oneshot_auth_failures_total',
                         'oneshot_rate_limited_total','oneshot_prompt_published_total',
                         'oneshot_jobs_admitted_total'):
            assert required in body


def test_g3_metrics_counts_auth_failures(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as c:
        before = _metric_value(c.get('/metrics').text, 'oneshot_auth_failures_total')
        for _ in range(3):
            assert c.get('/api/capabilities').status_code == 401
        after = _metric_value(c.get('/metrics').text, 'oneshot_auth_failures_total')
        assert after - before >= 3


# G5
def test_g5_compare_runs_requires_auth(tmp_path):
    app = _app(tmp_path)
    c = TestClient(app)
    r = c.get('/api/conversations/cccccccccccccccccccccccccccccccc/compare/runs?left=a&right=b')
    assert r.status_code == 401


def test_g5_compare_runs_returns_both_jobs_and_diff(tmp_path):
    cfg = Settings(data_dir=tmp_path, api_token='a' * 32, browser_password=PW)
    app = create_app(cfg, auto_worker=True)
    with TestClient(app) as c:
        c.post('/auth/login', json={'password': PW})
        c.headers['x-oneshot-csrf'] = c.get('/auth/session').json()['csrf']
        cid = c.post('/api/conversations', json={'title': 'cmp'}).json()['id']
        mid = c.post(f'/api/conversations/{cid}/messages',
                     json={'channel': 'system', 'content': 'Objective CMP'}).json()['id']
        s = c.post(f'/api/conversations/{cid}/sources/actions',
                   json={'action': 'INPUT_SOURCE', 'name': 'x.txt', 'content': 'body-content'})
        sid = s.json()['source_id']; sver = s.json()['version']
        job_ids = []
        for k in ('cmp-aaa-aaa', 'cmp-bbb-bbb'):
            r = c.post(f'/api/conversations/{cid}/jobs',
                       json={'operation': 'inspect_sources', 'source_ids': [sid],
                             'expected_versions': {sid: sver},
                             'idempotency_key': k, 'prompt_message_id': mid})
            job_ids.append(r.json()['id'])
            for _ in range(80):
                if c.get(f'/api/conversations/{cid}/jobs/{job_ids[-1]}').json().get('status') in ('completed','failed','blocked'):
                    break
                time.sleep(0.1)
        r = c.get(f'/api/conversations/{cid}/compare/runs?left={job_ids[0]}&right={job_ids[1]}')
        assert r.status_code == 200, r.text
        body = r.json()
        assert body['left']['job_id'] == job_ids[0]
        assert body['right']['job_id'] == job_ids[1]
        assert body['identical'] is True


# G7
def test_g7_hsts_header_present_only_on_https(tmp_path):
    app = _app(tmp_path)
    with TestClient(app, base_url='http://testserver') as c:
        r = c.get('/health')
        assert 'strict-transport-security' not in {k.lower() for k in r.headers}
    with TestClient(app, base_url='https://testserver') as c:
        r = c.get('/health')
        assert 'strict-transport-security' in {k.lower() for k in r.headers}


def test_g7_csp_includes_report_uri(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as c:
        r = c.get('/health')
        csp = r.headers.get('content-security-policy', '')
        assert 'report-uri /api/security/csp-violation' in csp


def test_g7_csp_violation_sink_accepts_report(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as c:
        r = c.post('/api/security/csp-violation',
                   content=b'{"csp-report":{"violated-directive":"img-src"}}',
                   headers={'content-type': 'application/csp-report'})
        assert r.status_code == 204
