"""Verifier policy: product_release_ready is strictly True only when all mandatory gates
AND all real-model acceptance scenarios have passed. Directive v6.0.4 §2.
"""
import importlib.util
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "scripts_verify_release", ROOT / "scripts" / "verify_release.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]


def _run_verdict(results, host=None):
    """Invoke `verdict` and read back the serialized output without stdout noise."""
    import io, json, sys
    buf = io.StringIO()
    old_out, sys.stdout = sys.stdout, buf
    try:
        _mod.verdict(results, host or {'python': '3.11.17'}, reason=None)
    finally:
        sys.stdout = old_out
    outfile = ROOT / 'data' / 'verification' / 'last_run.json'
    return json.loads(outfile.read_text())


def test_docker_is_in_optional_gates():
    assert 'docker' in _mod.OPTIONAL_GATES, (
        'docker gate must be optional so its skipped status appears in optional_skipped_gates')


def _ok(gate):
    return {'gate': gate, 'status': 'OK'}


def _skipped(gate):
    return {'gate': gate, 'status': 'SKIPPED_PREREQUISITE_MISSING'}


def _failed(gate):
    return {'gate': gate, 'status': 'FAILED', 'exit_code': 1}


def _structural_ok_results():
    return [_ok(g) for g in (
        'python311', 'uv', 'node', 'npm',
        'reviewed_lockfile', 'locked_python_environment', 'ruff_lint',
        'selfcheck', 'python_diagnostics', 'workflow_conformance',
        'dockerfile_contract', 'frontend_clean_install', 'frontend_check',
        'frontend_tests', 'frontend_build', 'http_integration',
        'multi_provider_protocol', 'chromium_install', 'browser_integrated_e2e',
        'browser_presend_e2e', 'live_model_local_e2e', 'backup_restore_e2e',
        'prompt_workspace_e2e', 'improvement_loop_browser_e2e',
        'improvement_loop_closure_browser_e2e',
    )] + [
        _skipped('docker'),
        _skipped('docker_compose_config'),
        _skipped('live_model_browser_e2e'),
        _skipped('vision_local_e2e'),
    ]


def test_structural_valid_with_realmodel_skipped_is_not_product_ready():
    """§2: a skipped prerequisite is not an executed pass."""
    out = _run_verdict(_structural_ok_results())
    assert out['status'] == 'VALID'            # structural verifier is still VALID
    assert out['release_ready'] is True        # structural verdict is release-ready
    assert out['product_release_ready'] is False
    assert out['blocked_scenarios'] == ['P09', 'P12-real-model', 'I05-real-model']
    assert out['realmodel_scenarios'] == {
        'P09': 'PENDING_REALMODEL_RUNTIME',
        'P12-real-model': 'PENDING_REALMODEL_RUNTIME',
        'I05-real-model': 'PENDING_REALMODEL_RUNTIME',
    }


def test_live_model_gate_ok_without_evidence_file_still_pending():
    """Hardened policy (directive v6.0 §3): a passing gate is NO LONGER sufficient.
    Each required scenario needs a signed evidence file under
    `data/realmodel_evidence/<scenario>.json` AND `ONESHOT_EVIDENCE_HMAC_KEY` set."""
    results = _structural_ok_results()
    for r in results:
        if r['gate'] == 'live_model_browser_e2e':
            r['status'] = 'OK'
            r.pop('note', None); r.pop('missing_prerequisite', None)
    out = _run_verdict(results)
    assert out['status'] == 'VALID'
    assert out['product_release_ready'] is False
    # Without evidence files, every required scenario stays pending.
    assert out['blocked_scenarios'] == ['P09', 'P12-real-model', 'I05-real-model']
    for sid in ('P09', 'P12-real-model', 'I05-real-model'):
        assert out['realmodel_scenarios'][sid] == 'PENDING_REALMODEL_RUNTIME'


def test_mandatory_gate_failure_blocks_product_ready():
    results = _structural_ok_results()
    # Flip one mandatory gate to FAILED
    for r in results:
        if r['gate'] == 'ruff_lint':
            r['status'] = 'FAILED'
            r['exit_code'] = 1
    out = _run_verdict(results)
    assert out['status'] == 'NOT_VALID'
    assert out['release_ready'] is False
    assert out['product_release_ready'] is False
    assert 'ruff_lint' in out['mandatory_failed_gates']


def test_optional_skips_do_not_block_structural_valid():
    results = _structural_ok_results()
    out = _run_verdict(results)
    assert out['status'] == 'VALID'
    for g in ('docker', 'docker_compose_config', 'live_model_browser_e2e', 'vision_local_e2e'):
        assert g in out['optional_skipped_gates'], out['optional_skipped_gates']


def test_realmodel_scenarios_require_actual_execution():
    """A skipped (not executed) real-model gate CANNOT be classified VERIFIED."""
    results = _structural_ok_results()  # live_model_browser_e2e remains SKIPPED
    out = _run_verdict(results)
    assert out['realmodel_scenarios']['P09'] == 'PENDING_REALMODEL_RUNTIME'
    # Confirm the inferred state cannot be set to VERIFIED without an actual OK gate
    assert out['product_release_ready'] is False



# ---- v6.0.7 §3 — P11-semantic product decision gate ----------------------

def _resolved_sentinel(did):
    return {
        'decision': did,
        'approved_by': 'test-operator',
        'approved_at': '2026-10-12T00:00:00Z',
        'summary': 'controlled fixture for release-policy testing only',
    }


def _patch_decisions_dir(monkeypatch, tmp_path, sentinels=None):
    import json
    d = tmp_path / 'decisions'
    d.mkdir()
    for did, rec in (sentinels or {}).items():
        (d / f'{did}.resolved.json').write_text(json.dumps(rec))
    monkeypatch.setattr(_mod, '_PRODUCT_DECISIONS_DIR', d)
    return d


def test_p11_unresolved_blocks_product_release(monkeypatch, tmp_path):
    """Even with all three real-model scenarios VERIFIED, unresolved P11-semantic blocks
    product_release_ready. The agent must not invent a P11 threshold (directive §3)."""
    _patch_decisions_dir(monkeypatch, tmp_path, sentinels={})
    # Stub real-model state to all-VERIFIED without needing actual evidence files.
    monkeypatch.setattr(_mod, '_realmodel_scenarios_state',
                        lambda results, **_kw: (
                            {'P09': 'VERIFIED', 'P12-real-model': 'VERIFIED',
                             'I05-real-model': 'VERIFIED'}, {}))
    out = _run_verdict(_structural_ok_results())
    assert out['status'] == 'VALID'
    assert out['release_ready'] is True
    assert out['product_release_ready'] is False
    assert out['blocked_decisions'] == ['P11-semantic']
    assert out['product_decisions']['P11-semantic'] == 'UNRESOLVED'


def test_p11_resolved_sentinel_clears_decision_block(monkeypatch, tmp_path):
    """Fixture: a properly-formed resolution sentinel clears the P11 block for
    policy testing — this is NOT a semantic acceptance claim."""
    _patch_decisions_dir(monkeypatch, tmp_path,
                         sentinels={'P11-semantic': _resolved_sentinel('P11-semantic')})
    monkeypatch.setattr(_mod, '_realmodel_scenarios_state',
                        lambda results, **_kw: (
                            {'P09': 'VERIFIED', 'P12-real-model': 'VERIFIED',
                             'I05-real-model': 'VERIFIED'}, {}))
    out = _run_verdict(_structural_ok_results())
    assert out['status'] == 'VALID'
    assert out['product_release_ready'] is True, out
    assert out['blocked_decisions'] == []
    assert out['product_decisions']['P11-semantic'] == 'RESOLVED'


def test_p11_malformed_sentinel_still_blocks(monkeypatch, tmp_path):
    """A sentinel file that exists but is malformed or mislabeled MUST NOT bypass the
    decision gate — directive §3 'do not invent P11 acceptance'."""
    import json
    d = tmp_path / 'decisions'
    d.mkdir()
    (d / 'P11-semantic.resolved.json').write_text('{not json')
    monkeypatch.setattr(_mod, '_PRODUCT_DECISIONS_DIR', d)
    monkeypatch.setattr(_mod, '_realmodel_scenarios_state',
                        lambda results, **_kw: (
                            {'P09': 'VERIFIED', 'P12-real-model': 'VERIFIED',
                             'I05-real-model': 'VERIFIED'}, {}))
    out = _run_verdict(_structural_ok_results())
    assert out['product_release_ready'] is False
    assert 'P11-semantic' in out['blocked_decisions']


def test_p11_sentinel_without_approval_fields_still_blocks(monkeypatch, tmp_path):
    import json
    d = tmp_path / 'decisions'
    d.mkdir()
    (d / 'P11-semantic.resolved.json').write_text(json.dumps({
        'decision': 'P11-semantic',  # no approved_by, no approved_at
    }))
    monkeypatch.setattr(_mod, '_PRODUCT_DECISIONS_DIR', d)
    monkeypatch.setattr(_mod, '_realmodel_scenarios_state',
                        lambda results, **_kw: (
                            {'P09': 'VERIFIED', 'P12-real-model': 'VERIFIED',
                             'I05-real-model': 'VERIFIED'}, {}))
    out = _run_verdict(_structural_ok_results())
    assert out['product_release_ready'] is False
    assert out['product_decisions']['P11-semantic'] == 'UNRESOLVED'


def test_missing_realmodel_evidence_still_blocks_even_with_p11_resolved(monkeypatch, tmp_path):
    """Resolving P11 does NOT paper over missing real-model execution evidence."""
    _patch_decisions_dir(monkeypatch, tmp_path,
                         sentinels={'P11-semantic': _resolved_sentinel('P11-semantic')})
    # Default real-model state (no evidence files) → everything PENDING.
    out = _run_verdict(_structural_ok_results())
    assert out['product_release_ready'] is False
    assert out['blocked_scenarios'] == ['P09', 'P12-real-model', 'I05-real-model']


def test_mandatory_gate_failure_still_blocks_even_with_everything_resolved(monkeypatch, tmp_path):
    _patch_decisions_dir(monkeypatch, tmp_path,
                         sentinels={'P11-semantic': _resolved_sentinel('P11-semantic')})
    monkeypatch.setattr(_mod, '_realmodel_scenarios_state',
                        lambda results, **_kw: (
                            {'P09': 'VERIFIED', 'P12-real-model': 'VERIFIED',
                             'I05-real-model': 'VERIFIED'}, {}))
    results = _structural_ok_results()
    for r in results:
        if r['gate'] == 'ruff_lint':
            r['status'] = 'FAILED'; r['exit_code'] = 1
    out = _run_verdict(results)
    assert out['status'] == 'NOT_VALID'
    assert out['release_ready'] is False
    assert out['product_release_ready'] is False
