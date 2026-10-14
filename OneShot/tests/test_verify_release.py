"""verify_release.py verdict is derived from executed evidence.

Fails if the script unconditionally emits NOT_VALID or VALID. The real integration
run is exercised in `scripts/verify_release.py`; this test uses a tiny harness
to prove the verdict function itself.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path


def _import_verifier():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    return importlib.import_module('scripts.verify_release')


def test_verdict_valid_when_every_mandatory_gate_ok(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.verify_release.ROOT', tmp_path)
    (tmp_path / 'data' / 'verification').mkdir(parents=True, exist_ok=True)
    verifier = _import_verifier()
    results = [
        {'gate': 'python311', 'status': 'OK'},
        {'gate': 'uv', 'status': 'OK'},
        {'gate': 'node', 'status': 'OK'},
        {'gate': 'npm', 'status': 'OK'},
        {'gate': 'reviewed_lockfile', 'status': 'OK'},
        {'gate': 'frontend_tests', 'status': 'OK'},
        {'gate': 'docker_compose_config', 'status': 'SKIPPED_PREREQUISITE_MISSING'},
        {'gate': 'live_model_browser_e2e', 'status': 'SKIPPED_PREREQUISITE_MISSING'},
    ]
    rc = verifier.verdict(results, {'python': '3.11.17', 'platform': 'test'}, reason=None)
    assert rc == 0
    body = (tmp_path / 'data' / 'verification' / 'last_run.json').read_text()
    import json
    data = json.loads(body)
    assert data['status'] == 'VALID'
    assert data['release_ready'] is True
    assert data['mandatory_failed_gates'] == []
    assert data['optional_skipped_gates'] == ['docker_compose_config', 'live_model_browser_e2e']


def test_verdict_not_valid_when_any_mandatory_fails(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.verify_release.ROOT', tmp_path)
    (tmp_path / 'data' / 'verification').mkdir(parents=True, exist_ok=True)
    verifier = _import_verifier()
    results = [
        {'gate': 'python311', 'status': 'OK'},
        {'gate': 'frontend_tests', 'status': 'FAILED', 'exit_code': 1, 'stderr_tail': 'boom'},
        {'gate': 'docker_compose_config', 'status': 'SKIPPED_PREREQUISITE_MISSING'},
    ]
    rc = verifier.verdict(results, {'python': '3.11.17'}, reason=None)
    assert rc == 1
    import json
    data = json.loads((tmp_path / 'data' / 'verification' / 'last_run.json').read_text())
    assert data['status'] == 'NOT_VALID'
    assert data['release_ready'] is False
    assert 'frontend_tests' in data['mandatory_failed_gates']
    # Optional skips do NOT demote the verdict.
    assert 'docker_compose_config' not in data['mandatory_failed_gates']


def test_verdict_not_valid_on_prerequisite_missing(tmp_path, monkeypatch):
    monkeypatch.setattr('scripts.verify_release.ROOT', tmp_path)
    (tmp_path / 'data' / 'verification').mkdir(parents=True, exist_ok=True)
    verifier = _import_verifier()
    results = [{'gate': 'uv', 'status': 'TOOL_MISSING', 'where': ''}]
    rc = verifier.verdict(results, {'python': '3.11.17'}, reason='prerequisite_missing')
    assert rc == 1
    import json
    data = json.loads((tmp_path / 'data' / 'verification' / 'last_run.json').read_text())
    assert data['status'] == 'NOT_VALID'
    assert data['halt_reason'] == 'prerequisite_missing'
