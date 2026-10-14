"""Verifier evidence-consumption invariants — directive v6.0 §3 and v6.0.7 §1-§2.

Each real-model scenario (P09, P12-real-model, I05-real-model) is proved VERIFIED only
when a signed, non-stale, loopback-only evidence file exists in `data/realmodel_evidence/`
AND the receiver's local SQLite confirms the declared artifact bytes.

Regressions covered:
  (1) Missing evidence must not pass.
  (2) Invalid evidence must not pass (malformed JSON, missing fields).
  (3) Evidence for the wrong scenario must not pass.
  (4) Replayed evidence (stale commit, wrong HMAC) must not pass.
  (5) Non-loopback model endpoints must not pass.
  (6) Each required scenario is evaluated independently.
  (7) Properly signed evidence can satisfy its scenario.
  (8) Nonce replay across runs must not pass. [v6.0.7 §1]
  (9) Second-channel artifact lookup rejects fabricated artifact bytes. [v6.0.7 §1]
 (10) Scenario-operation mismatch must not pass. [v6.0.7 §1]
 (11) Missing release identity (no .git, no BUILD_MANIFEST.git_sha) fails closed. [v6.0.7 §2]
 (12) BUILD_MANIFEST.host.git_sha supplies release identity when .git is absent. [v6.0.7 §2]
"""
import hashlib
import hmac
import importlib.util
import json
import os
import pathlib
import secrets
import sqlite3
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "scripts_verify_release", ROOT / "scripts" / "verify_release.py")
VR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(VR)  # type: ignore[union-attr]


KEY = 'test-hmac-key-for-release-verifier'
FAKE_COMMIT = 'commit-aaaaaaaaaaaa'


def _signed_evidence(scenario, commit=None, overrides=None, artifact_sha=None):
    rec = {
        'scenario': scenario,
        'generated_at': '2026-10-12T00:00:00Z',
        'oneshot_commit': commit or FAKE_COMMIT,
        'model_endpoint': 'http://127.0.0.1:8080/v1/chat/completions',
        'model_name': 'test-model-gguf',
        'job_id': 'j' * 32,
        'artifact_id': 'a' * 32,
        'artifact_sha256': artifact_sha or ('d' * 64),
        'nonce': secrets.token_hex(16),
    }
    if overrides: rec.update(overrides)
    body = '|'.join((rec['scenario'], rec['oneshot_commit'], rec['job_id'],
                     rec['artifact_sha256'], rec['nonce'])).encode('utf-8')
    rec['proof'] = hmac.new(KEY.encode('utf-8'), body, hashlib.sha256).hexdigest()
    return rec


@pytest.fixture
def evidence_dir(tmp_path, monkeypatch):
    d = tmp_path / 'data' / 'realmodel_evidence'
    d.mkdir(parents=True)
    monkeypatch.setattr(VR, '_EVIDENCE_DIR', d)
    monkeypatch.setattr(VR, '_EVIDENCE_NONCE_LEDGER', d / '.nonces.jsonl')
    monkeypatch.setenv('ONESHOT_EVIDENCE_HMAC_KEY', KEY)
    return d


_UNSET = object()


def _state(evidence_dir, sid, *, second_channel=False, data_root=None, current_commit=_UNSET):
    """Call the real _realmodel_scenarios_state helper with unit-test defaults.

    When ``current_commit`` is left at the sentinel, FAKE_COMMIT is used (shape tests).
    Pass ``current_commit=None`` to force VR._release_identity() lookup (portability tests).
    """
    if current_commit is _UNSET:
        commit = FAKE_COMMIT
    else:
        commit = current_commit
    states, _details = VR._realmodel_scenarios_state(
        [], second_channel=second_channel, data_root=data_root,
        evidence_dir=evidence_dir, nonce_ledger=evidence_dir / '.nonces.jsonl',
        current_commit=commit)
    return states.get(sid)


def _write(evidence_dir, scenario, rec):
    (evidence_dir / f'{scenario}.json').write_text(json.dumps(rec))


# ---- (1) Missing evidence must not pass -----------------------------------

def test_missing_evidence_file_is_pending(evidence_dir):
    assert _state(evidence_dir, 'P09') == 'PENDING_REALMODEL_RUNTIME'


# ---- (2) Invalid evidence must not pass -----------------------------------

def test_malformed_json_is_evidence_invalid(evidence_dir):
    (evidence_dir / 'P09.json').write_text('{not json')
    assert _state(evidence_dir, 'P09') == 'EVIDENCE_INVALID'


def test_missing_required_field_is_evidence_invalid(evidence_dir):
    rec = _signed_evidence('P09')
    del rec['model_name']
    _write(evidence_dir, 'P09', rec)
    assert _state(evidence_dir, 'P09') == 'EVIDENCE_INVALID'


# ---- (3) Wrong scenario in file must not pass -----------------------------

def test_scenario_mismatch_is_invalid(evidence_dir):
    """Receiver signed P09 evidence but dropped it under P12-real-model.json."""
    rec = _signed_evidence('P09')
    _write(evidence_dir, 'P12-real-model', rec)  # filename says P12-real-model, body says P09
    assert _state(evidence_dir, 'P12-real-model') == 'EVIDENCE_INVALID'


# ---- (4) Replayed evidence (stale commit / wrong HMAC) must not pass -------

def test_stale_commit_evidence_is_invalid(evidence_dir):
    rec = _signed_evidence('P09', commit='old-commit')
    _write(evidence_dir, 'P09', rec)
    assert _state(evidence_dir, 'P09', current_commit='curr-commit') == 'EVIDENCE_INVALID'


def test_wrong_hmac_key_is_invalid(evidence_dir, monkeypatch):
    rec = _signed_evidence('P09')
    monkeypatch.setenv('ONESHOT_EVIDENCE_HMAC_KEY', 'different-key')
    _write(evidence_dir, 'P09', rec)
    assert _state(evidence_dir, 'P09') == 'EVIDENCE_INVALID'


# ---- (5) Non-loopback endpoint must not pass -------------------------------

def test_non_loopback_endpoint_is_invalid(evidence_dir):
    rec = _signed_evidence('P09', overrides={'model_endpoint': 'https://api.example.com/v1'})
    # Re-sign because overrides changed body
    body = '|'.join((rec['scenario'], rec['oneshot_commit'], rec['job_id'],
                     rec['artifact_sha256'], rec['nonce'])).encode('utf-8')
    rec['proof'] = hmac.new(KEY.encode('utf-8'), body, hashlib.sha256).hexdigest()
    _write(evidence_dir, 'P09', rec)
    assert _state(evidence_dir, 'P09') == 'EVIDENCE_INVALID'


# ---- (6) Each scenario evaluated independently -----------------------------

def test_scenarios_evaluated_independently(evidence_dir):
    _write(evidence_dir, 'P09', _signed_evidence('P09'))
    states, _ = VR._realmodel_scenarios_state(
        [], second_channel=False, evidence_dir=evidence_dir,
        nonce_ledger=evidence_dir / '.nonces.jsonl', current_commit=FAKE_COMMIT)
    assert states['P09'] == 'VERIFIED'
    assert states['P12-real-model'] == 'PENDING_REALMODEL_RUNTIME'
    assert states['I05-real-model'] == 'PENDING_REALMODEL_RUNTIME'


# ---- (7) Properly signed evidence can satisfy its scenario -----------------

def test_valid_evidence_marks_scenario_verified(evidence_dir):
    _write(evidence_dir, 'P09', _signed_evidence('P09'))
    _write(evidence_dir, 'P12-real-model', _signed_evidence('P12-real-model'))
    _write(evidence_dir, 'I05-real-model', _signed_evidence('I05-real-model'))
    states, details = VR._realmodel_scenarios_state(
        [], second_channel=False, evidence_dir=evidence_dir,
        nonce_ledger=evidence_dir / '.nonces.jsonl', current_commit=FAKE_COMMIT)
    assert all(st == 'VERIFIED' for st in states.values()), states
    for sid, det in details.items():
        assert det['model_name'] == 'test-model-gguf', (sid, det)


# ---- (8) Nonce replay rejection (v6.0.7 §1) -------------------------------

def test_nonce_replay_across_runs_is_invalid(evidence_dir):
    rec = _signed_evidence('P09')
    _write(evidence_dir, 'P09', rec)
    # First call records the nonce as consumed.
    assert _state(evidence_dir, 'P09') == 'VERIFIED'
    # Second call sees the exact same nonce — must reject even though the file is
    # otherwise identical and signatures still match.
    assert _state(evidence_dir, 'P09') == 'EVIDENCE_INVALID'


def test_nonce_replay_rejects_cross_scenario_reuse(evidence_dir):
    """A nonce verified under P09 cannot be reused under I05-real-model, even with a
    freshly-computed HMAC for the new scenario."""
    rec = _signed_evidence('P09')
    _write(evidence_dir, 'P09', rec)
    assert _state(evidence_dir, 'P09') == 'VERIFIED'
    # Reuse the same nonce in a different scenario, re-signing.
    rec2 = _signed_evidence('I05-real-model', overrides={'nonce': rec['nonce']})
    _write(evidence_dir, 'I05-real-model', rec2)
    assert _state(evidence_dir, 'I05-real-model') == 'EVIDENCE_INVALID'


# ---- (9)+(10) Second-channel artifact / scenario-operation (v6.0.7 §1) ----

@pytest.fixture
def seeded_data(tmp_path):
    """Build a minimal data/oneshot.sqlite3 so second-channel checks can succeed."""
    from systems.store import Store
    data_dir = tmp_path / 'data'
    Store(data_dir)  # creates & migrates schema
    with sqlite3.connect(data_dir / 'oneshot.sqlite3') as con:
        con.row_factory = sqlite3.Row
        con.execute("INSERT INTO conversations(id,title,agent_active) VALUES('c1','t',0)")
        now = '2026-10-12T00:00:00+00:00'
        con.execute("INSERT INTO jobs(id,conversation_id,operation,scope_json,"
                    "idempotency_key,status,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    ('j' * 32, 'c1', 'auto_generate', '[]', 'k1', 'completed', now, now))
        con.execute("INSERT INTO artifacts(id,conversation_id,job_id,kind,content,"
                    "provider,source_ids_json,limitations_json,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    ('a' * 32, 'c1', 'j' * 32, 'summary',
                     'The real-model output bytes for scenario P09.',
                     'llama', '[]', '[]', now))
        con.commit()
    return tmp_path


def test_second_channel_rejects_fabricated_artifact_bytes(evidence_dir, seeded_data):
    """A signature over fabricated sha fails the SQLite cross-check."""
    rec = _signed_evidence('P09',
                           overrides={'artifact_id': 'a' * 32, 'job_id': 'j' * 32})
    _write(evidence_dir, 'P09', rec)
    states, details = VR._realmodel_scenarios_state(
        [], second_channel=True, data_root=seeded_data, evidence_dir=evidence_dir,
        nonce_ledger=evidence_dir / '.nonces.jsonl', current_commit=FAKE_COMMIT)
    assert states['P09'] == 'EVIDENCE_INVALID'
    assert 'second_channel' in details['P09'], details['P09']


def test_second_channel_accepts_matching_artifact_bytes(evidence_dir, seeded_data):
    content = 'The real-model output bytes for scenario P09.'
    real_sha = hashlib.sha256(content.encode('utf-8')).hexdigest()
    rec = _signed_evidence('P09',
                           overrides={'artifact_id': 'a' * 32, 'job_id': 'j' * 32},
                           artifact_sha=real_sha)
    _write(evidence_dir, 'P09', rec)
    states, _ = VR._realmodel_scenarios_state(
        [], second_channel=True, data_root=seeded_data, evidence_dir=evidence_dir,
        nonce_ledger=evidence_dir / '.nonces.jsonl', current_commit=FAKE_COMMIT)
    assert states['P09'] == 'VERIFIED'


def test_second_channel_rejects_scenario_operation_mismatch(evidence_dir, tmp_path):
    """P09 evidence pointing at an inspect_sources job (not auto_generate/summarize)
    is NOT a P09 pass, no matter how the signature matches."""
    from systems.store import Store
    data_dir = tmp_path / 'data'
    Store(data_dir)
    content = 'contents'
    with sqlite3.connect(data_dir / 'oneshot.sqlite3') as con:
        con.row_factory = sqlite3.Row
        con.execute("INSERT INTO conversations(id,title,agent_active) VALUES('c1','t',0)")
        now = '2026-10-12T00:00:00+00:00'
        con.execute("INSERT INTO jobs(id,conversation_id,operation,scope_json,"
                    "idempotency_key,status,created_at,updated_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    ('j' * 32, 'c1', 'inspect_sources', '[]', 'k2', 'completed', now, now))
        con.execute("INSERT INTO artifacts(id,conversation_id,job_id,kind,content,"
                    "provider,source_ids_json,limitations_json,created_at) "
                    "VALUES(?,?,?,?,?,?,?,?,?)",
                    ('a' * 32, 'c1', 'j' * 32, 'evidence_packet', content, 'evidence',
                     '[]', '[]', now))
    real_sha = hashlib.sha256(content.encode('utf-8')).hexdigest()
    rec = _signed_evidence('P09',
                           overrides={'artifact_id': 'a' * 32, 'job_id': 'j' * 32},
                           artifact_sha=real_sha)
    _write(evidence_dir, 'P09', rec)
    states, details = VR._realmodel_scenarios_state(
        [], second_channel=True, data_root=tmp_path, evidence_dir=evidence_dir,
        nonce_ledger=evidence_dir / '.nonces.jsonl', current_commit=FAKE_COMMIT)
    assert states['P09'] == 'EVIDENCE_INVALID'
    # Mismatch surfaces either as operation-mismatch or synthetic-provider rejection —
    # both are correct refusals.
    sc = details['P09']['second_channel']
    assert ('operation_scenario_mismatch' in sc) or ('synthetic_provider_rejected' in sc), sc


# ---- (11)+(12) Portable release identity (v6.0.7 §2) ----------------------

def test_evidence_fails_closed_when_identity_unavailable(evidence_dir, tmp_path, monkeypatch):
    """No git, no BUILD_MANIFEST → evidence is REFUSED, not silently accepted."""
    rec = _signed_evidence('P09')
    _write(evidence_dir, 'P09', rec)
    # Point ROOT at an empty tmp tree with no .git and no BUILD_MANIFEST.
    empty = tmp_path / 'empty'
    empty.mkdir()
    monkeypatch.setattr(VR, 'ROOT', empty)
    # _release_identity will return ('', 'unknown').
    assert _state(evidence_dir, 'P09', current_commit=None) == 'EVIDENCE_INVALID'


def test_release_identity_uses_build_manifest_when_git_missing(evidence_dir, tmp_path, monkeypatch):
    """A clean extracted release has no .git but has BUILD_MANIFEST.host.git_sha.
    That value feeds the stale-commit check."""
    tree = tmp_path / 'extracted'
    tree.mkdir()
    (tree / 'BUILD_MANIFEST.json').write_text(json.dumps({
        'host': {'git_sha': FAKE_COMMIT}, 'entries': [],
    }))
    monkeypatch.setattr(VR, 'ROOT', tree)
    commit, source = VR._release_identity()
    assert commit == FAKE_COMMIT and source == 'build_manifest'

    # And signed evidence that matches that identity is accepted (second_channel off).
    rec = _signed_evidence('P09', commit=FAKE_COMMIT)
    _write(evidence_dir, 'P09', rec)
    states, _ = VR._realmodel_scenarios_state(
        [], second_channel=False, evidence_dir=evidence_dir,
        nonce_ledger=evidence_dir / '.nonces.jsonl')  # no explicit commit -> use VR._release_identity
    assert states['P09'] == 'VERIFIED'


def test_release_identity_mismatch_build_manifest_rejects(evidence_dir, tmp_path, monkeypatch):
    """Clean release says identity X; evidence signed against identity Y → rejected."""
    tree = tmp_path / 'extracted'
    tree.mkdir()
    (tree / 'BUILD_MANIFEST.json').write_text(json.dumps({
        'host': {'git_sha': 'identity-X'}, 'entries': [],
    }))
    monkeypatch.setattr(VR, 'ROOT', tree)
    rec = _signed_evidence('P09', commit='identity-Y')
    _write(evidence_dir, 'P09', rec)
    states, _ = VR._realmodel_scenarios_state(
        [], second_channel=False, evidence_dir=evidence_dir,
        nonce_ledger=evidence_dir / '.nonces.jsonl')
    assert states['P09'] == 'EVIDENCE_INVALID'


def test_product_release_ready_requires_all_scenarios(evidence_dir, tmp_path, monkeypatch):
    """End-to-end: build a synthetic verdict with structural VALID + only P09 signed.
    Second-channel is OFF for this test (no SQLite); product release must still remain
    FALSE because P12 / I05 are PENDING AND P11-semantic is UNRESOLVED."""
    # Isolate verdict's product_decisions directory into tmp_path so we don't rely on
    # whether docs/product_decisions/P11-semantic.resolved.json exists in-tree.
    monkeypatch.setattr(VR, '_PRODUCT_DECISIONS_DIR', tmp_path / 'product_decisions')
    _write(evidence_dir, 'P09', _signed_evidence('P09'))
    import io, sys
    all_ok = [{'gate': g, 'status': 'OK'} for g in (
        'python311', 'uv', 'node', 'npm', 'reviewed_lockfile',
        'locked_python_environment', 'ruff_lint', 'selfcheck', 'python_diagnostics',
        'workflow_conformance', 'dockerfile_contract', 'frontend_clean_install',
        'frontend_check', 'frontend_tests', 'frontend_build', 'http_integration',
        'multi_provider_protocol', 'chromium_install', 'browser_integrated_e2e',
        'browser_presend_e2e', 'live_model_local_e2e', 'backup_restore_e2e',
        'prompt_workspace_e2e', 'improvement_loop_browser_e2e',
        'improvement_loop_closure_browser_e2e',
    )] + [
        {'gate': 'docker', 'status': 'SKIPPED_PREREQUISITE_MISSING'},
        {'gate': 'docker_compose_config', 'status': 'SKIPPED_PREREQUISITE_MISSING'},
        {'gate': 'live_model_browser_e2e', 'status': 'SKIPPED_PREREQUISITE_MISSING'},
        {'gate': 'vision_local_e2e', 'status': 'SKIPPED_PREREQUISITE_MISSING'},
    ]
    # Pre-isolate VR._realmodel_scenarios_state inputs by monkeypatching the module's
    # dir constants so verdict() reads from our tmp evidence_dir with current_commit=FAKE.
    monkeypatch.setattr(VR, '_EVIDENCE_DIR', evidence_dir)
    monkeypatch.setattr(VR, '_EVIDENCE_NONCE_LEDGER', evidence_dir / '.nonces.jsonl')
    # Force _release_identity to return FAKE_COMMIT by writing a BUILD_MANIFEST
    # near a tmp ROOT.
    tree = tmp_path / 'tree'
    tree.mkdir()
    (tree / 'BUILD_MANIFEST.json').write_text(json.dumps({
        'host': {'git_sha': FAKE_COMMIT}, 'entries': []}))
    monkeypatch.setattr(VR, 'ROOT', tree)
    # Monkeypatch _realmodel_scenarios_state to disable the second-channel SQLite check
    # (this test only exercises the verdict policy — the second-channel path has its
    # own dedicated tests above).
    orig_state = VR._realmodel_scenarios_state
    def no_second_channel(results, **_kw):
        return orig_state(results, second_channel=False, evidence_dir=evidence_dir,
                          nonce_ledger=evidence_dir / '.nonces.jsonl',
                          current_commit=FAKE_COMMIT)
    monkeypatch.setattr(VR, '_realmodel_scenarios_state', no_second_channel)
    buf = io.StringIO()
    old_stdout = sys.stdout; sys.stdout = buf
    try:
        VR.verdict(all_ok, {'python': '3.11.17'}, reason=None)
    finally:
        sys.stdout = old_stdout
    out = json.loads((tree / 'data' / 'verification' / 'last_run.json').read_text())
    assert out['product_release_ready'] is False
    assert out['realmodel_scenarios']['P09'] == 'VERIFIED'
    assert out['blocked_scenarios'] == ['P12-real-model', 'I05-real-model']
    assert 'P11-semantic' in out['blocked_decisions']
