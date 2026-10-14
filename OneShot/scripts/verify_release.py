"""Release gate verifier — evidence-derived verdict.

Each gate runs its real command, records the exit code, stdout/stderr tail, and
elapsed seconds, and the final verdict is derived from executed outcomes:

- Every mandatory gate ends with ``status: 'OK'`` -> ``VALID``.
- Any mandatory gate with ``status: 'FAILED'`` or ``'TOOL_MISSING'`` or
  ``'TIMED_OUT'`` -> ``NOT_VALID`` with the list of unresolved gate ids.
- Optional gates (``docker_*``, ``live_model_browser_e2e``) that cannot run on
  the host are reported as ``SKIPPED_PREREQUISITE_MISSING`` with the exact
  missing binary / env var; they do NOT demote the verdict.

Written output: ``data/verification/last_run.json`` carries the whole record so
operators can retrieve the exact command, host, python version, exit code,
stderr tail and elapsed time for every executed gate — never a bare label.
"""
from __future__ import annotations

import json
# Phase 14: structured verdict vocabulary
from systems.diagnostic_tags import promote_gate_record
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path


def _git_sha(root: Path) -> str | None:
    try:
        r = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(root),
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip()
    except FileNotFoundError:
        pass
    return None

ROOT = Path(__file__).resolve().parents[1]

# Mandatory gates must all return OK before the verdict is VALID.
# Optional gates can SKIP without demoting the verdict when a prerequisite
# that is NOT part of the gate under test is missing (e.g. no Docker daemon,
# no live model credentials).
OPTIONAL_GATES = {'docker', 'docker_compose_config', 'docker_compose_build',
                  'live_model_browser_e2e', 'vision_local_e2e'}


def _tool_missing(args):
    """Return the first argv executable that is not on PATH, else None."""
    executable = args[0]
    if executable in {sys.executable}:
        return None
    return None if shutil.which(executable) else executable


def run(name, args, cwd=ROOT, timeout=600):
    started = time.time()
    missing = _tool_missing(args)
    if missing is not None:
        return {'gate': name, 'status': 'TOOL_MISSING', 'missing_tool': missing,
                'command': args, 'cwd': str(cwd), 'seconds': 0.0}
    try:
        p = subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env={**os.environ})
        return {'gate': name,
                'status': 'OK' if p.returncode == 0 else 'FAILED',
                'exit_code': p.returncode, 'command': args, 'cwd': str(cwd),
                'seconds': round(time.time() - started, 2),
                'stdout_tail': p.stdout[-500:],
                'stderr_tail': p.stderr[-500:]}
    except subprocess.TimeoutExpired as exc:
        return {'gate': name, 'status': 'TIMED_OUT', 'timeout_seconds': timeout,
                'command': args, 'cwd': str(cwd),
                'seconds': round(time.time() - started, 2),
                'stderr_tail': (exc.stderr or '')[-500:] if exc.stderr else ''}
    except OSError as exc:
        return {'gate': name, 'status': 'FAILED', 'error': repr(exc),
                'command': args, 'cwd': str(cwd),
                'seconds': round(time.time() - started, 2)}


def _env_present(*names):
    return all(os.environ.get(n) for n in names)


def main():
    host = {'python': sys.version.split()[0], 'platform': platform.platform(),
            'machine': platform.machine(), 'cwd': str(ROOT),
            'git_sha': _git_sha(ROOT),
            'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    results = []

    # Prerequisites: interpreter + tool availability. 3.11 is pinned by
    # pyproject.toml and .python-version; a mismatch is a FAILED gate, not a
    # silent "ok with 3.13 fallback".
    py311 = sys.version_info[:2] == (3, 11)
    results.append({'gate': 'python311',
                    'status': 'OK' if py311 else 'FAILED',
                    'actual': sys.version.split()[0]})
    for executable in ('uv', 'node', 'npm'):
        results.append({'gate': executable,
                        'status': 'OK' if shutil.which(executable) else 'TOOL_MISSING',
                        'where': shutil.which(executable) or ''})
    docker_available = shutil.which('docker') is not None
    results.append({'gate': 'docker',
                    'status': 'OK' if docker_available else 'SKIPPED_PREREQUISITE_MISSING',
                    'where': shutil.which('docker') or '',
                    'note': 'Docker is an optional target; verdict is not demoted when absent.'})
    results.append({'gate': 'reviewed_lockfile',
                    'status': 'OK' if (ROOT / 'uv.lock').is_file() else 'FAILED',
                    'path': str((ROOT / 'uv.lock').relative_to(ROOT))})

    # If any mandatory prereq is missing, skip rest and compute verdict now.
    mandatory_prereqs = [r for r in results
                        if r['gate'] in {'python311', 'uv', 'node', 'npm', 'reviewed_lockfile'}
                        and r['status'] != 'OK']
    if mandatory_prereqs:
        return verdict(results, host, reason='prerequisite_missing')

    # Install + build + run every gate exactly as declared.
    frontend = ROOT / 'frontend'
    gates = [
        ('locked_python_environment', ['uv', 'sync', '--locked', '--extra', 'test', '--python', '3.11'], ROOT),
        ('ruff_lint',                  ['uv', 'run', '--locked', '--with', 'ruff==0.14.0', 'ruff', 'check', '.'], ROOT),
        ('selfcheck',                  ['uv', 'run', '--locked', 'python', '-m', 'scripts.selfcheck'], ROOT),
        ('python_diagnostics',         ['uv', 'run', '--locked', 'python', '-m', 'pytest', '-q'], ROOT),
        ('workflow_conformance',       ['uv', 'run', '--locked', 'python', '-m', 'pytest', 'tests/test_workflow_conformance.py'], ROOT),
        ('dockerfile_contract',        ['uv', 'run', '--locked', 'python', '-m', 'pytest', 'tests/test_dockerfile_contract.py'], ROOT),
        ('frontend_clean_install',     ['npm', 'ci', '--no-audit', '--fund=false'], frontend),
        ('frontend_check',             ['npm', 'run', 'check'], frontend),
        ('frontend_tests',             ['npm', 'test'], frontend),
        ('frontend_build',             ['npm', 'run', 'build'], frontend),
        ('http_integration',           ['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_http'], ROOT),
        ('multi_provider_protocol',    ['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_multi_provider_http'], ROOT),
        ('chromium_install',           ['uv', 'run', '--locked', 'python', '-m', 'playwright', 'install', 'chromium'], ROOT),
        ('browser_integrated_e2e',     ['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_browser'], ROOT),
        ('browser_presend_e2e',        ['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_presend'], ROOT),
        ('live_model_local_e2e',       ['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_live_model_local'], ROOT),
        ('backup_restore_e2e',         ['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_backup_restore'], ROOT),
        ('prompt_workspace_e2e',       ['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_prompt_workspace'], ROOT),
        ('improvement_loop_browser_e2e',['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_improvement_loop'], ROOT),
        ('improvement_loop_closure_browser_e2e',['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_improvement_loop_closure'], ROOT),
    ]
    for name, args, cwd in gates:
        results.append(run(name, args, cwd))

    # Optional gates — report precise skip reason instead of unconditional FAIL.
    if docker_available:
        results.append(run('docker_compose_config', ['docker', 'compose', 'config'], ROOT))
    else:
        results.append({'gate': 'docker_compose_config', 'status': 'SKIPPED_PREREQUISITE_MISSING',
                        'missing_prerequisite': 'docker',
                        'note': 'docker binary not on PATH; declared optional'})

    live_model_configured = _env_present('ONESHOT_PROVIDER', 'ONESHOT_MODEL_NAME')
    if live_model_configured and os.environ.get('ONESHOT_PROVIDER') != 'evidence':
        results.append(run('live_model_browser_e2e',
                           ['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_live_model'], ROOT))
    else:
        results.append({'gate': 'live_model_browser_e2e',
                        'status': 'SKIPPED_PREREQUISITE_MISSING',
                        'missing_prerequisite': 'ONESHOT_PROVIDER != evidence + ONESHOT_MODEL_NAME + credentials',
                        'note': 'No real model configured; evidence-mode runs cannot verify model semantics'})

    # Vision E14: mandatory when configured, otherwise optional-skipped with precise reason.
    vision_configured = os.environ.get('ONESHOT_VISION_PROVIDER') == 'llama' and _env_present(
        'ONESHOT_VISION_ENDPOINT', 'ONESHOT_VISION_MODEL')
    if vision_configured:
        results.append(run('vision_local_e2e',
                           ['uv', 'run', '--locked', 'python', '-m', 'tests.e2e_vision_local'], ROOT))
    else:
        results.append({'gate': 'vision_local_e2e',
                        'status': 'SKIPPED_PREREQUISITE_MISSING',
                        'missing_prerequisite': 'ONESHOT_VISION_PROVIDER=llama + ONESHOT_VISION_ENDPOINT + ONESHOT_VISION_MODEL (local llama-server with vision-capable GGUF)',
                        'note': 'No local vision model configured; synthetic responders cannot satisfy E14 per ADR-002'})

    return verdict(results, host, reason=None)


# Mandatory real-model acceptance scenarios (directive §5, §9). These are the exact
# feature-level E2E paths that must have been executed and passed before the product
# release can be declared complete. A verifier run that only reports structural / optional
# skipped success leaves these scenarios in PENDING; promotion requires them to be VERIFIED.
REQUIRED_REALMODEL_SCENARIOS = ('P09', 'P12-real-model', 'I05-real-model')


# Each scenario is produced by a specific operation. The verifier refuses evidence that
# names a scenario inconsistent with its operation (directive v6.0.7 §1). This is NOT a
# semantic acceptance threshold (P11-semantic owns that separately); it is a shape /
# provenance check that prevents a signed receipt from one scenario being filed as
# another.
_SCENARIO_OPERATIONS = {
    # P09 = "Execute System Operation with real model" → auto_generate / summarize with
    # a non-evidence provider; the resulting artifact lives in the `artifacts` table.
    'P09':             {'table': 'artifacts',
                        'operations': {'auto_generate', 'summarize'},
                        'provider_rule': 'not_evidence'},
    # P12-real-model = "Optimize prompt with real provider" → prompts.propose_optimization;
    # the result row is in `prompt_optimizations`.
    'P12-real-model':  {'table': 'prompt_optimizations',
                        'operations': None,  # not a jobs.operation
                        'provider_rule': 'not_evidence'},
    # I05-real-model = "Advisory analysis with real model" → improvement_loop.request_advisory_analysis;
    # the result row is in `improvement_proposals`, with provider in evidence_json.
    'I05-real-model':  {'table': 'improvement_proposals',
                        'operations': None,
                        'provider_rule': 'not_evidence'},
}


# Each required real-model scenario is verified by its OWN independent evidence file under
# `data/realmodel_evidence/<scenario>.json`. The receiver generates one of these files after
# executing the scenario against a real llama.cpp (or an explicitly approved hosted provider)
# via `scripts/receiver_realmodel_evidence.py`. The verifier never claims VERIFIED on its own
# authority: it validates the shape, signature, model-endpoint loopback, source-tree
# fingerprint, AND cross-checks the recorded artifact bytes directly in the local SQLite
# database (second channel). A correctly signed JSON file whose claimed artifact bytes do
# not match the persisted row is EVIDENCE_INVALID, not VERIFIED.
_EVIDENCE_DIR = ROOT / 'data' / 'realmodel_evidence'
_EVIDENCE_NONCE_LEDGER = _EVIDENCE_DIR / '.nonces.jsonl'
_EVIDENCE_SCHEMA_FIELDS = (
    'scenario', 'generated_at', 'oneshot_commit', 'model_endpoint',
    'model_name', 'job_id', 'artifact_id', 'artifact_sha256', 'proof', 'nonce',
)


def _hmac_proof(key, scenario, commit, job_id, artifact_sha256, nonce):
    import hashlib, hmac
    body = '|'.join((scenario, commit, job_id, artifact_sha256, nonce)).encode('utf-8')
    return hmac.new(key.encode('utf-8'), body, hashlib.sha256).hexdigest()


def _release_identity(root=None):
    """Return (commit, source) for the current source tree.

    The verifier runs against an extracted release that is NOT a git working tree in the
    normal distribution case (there is no `.git`). Falling back to `git rev-parse HEAD`
    silently returning '' DISABLES the stale-commit check — a signed-elsewhere receipt
    would be accepted on a cleanly extracted tarball. Directive v6.0.7 §2 requires fail-
    closed behaviour: if `.git` is unavailable AND `BUILD_MANIFEST.json` does not carry a
    `host.git_sha`, the identity is empty and every evidence check with a declared
    oneshot_commit MUST fail. (A receipt that did not declare a commit would also fail at
    the schema level.) The empty-string case is still used by purely-unit test paths that
    sign evidence with their own commit value and never persist a BUILD_MANIFEST.
    """
    import subprocess, json as _json
    root = root or ROOT
    try:
        out = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=str(root),
                                      stderr=subprocess.DEVNULL, timeout=5).decode().strip()
        if out:
            return out, 'git'
    except Exception:
        pass
    manifest = root / 'BUILD_MANIFEST.json'
    if manifest.is_file():
        try:
            rec = _json.loads(manifest.read_text())
            sha = (rec.get('host') or {}).get('git_sha') or ''
            if sha:
                return sha, 'build_manifest'
        except Exception:
            pass
    return '', 'unknown'


def _verify_artifact_second_channel(scenario, rec, data_root=None):
    """Open the LOCAL SQLite and prove that the evidence's artifact actually exists.

    This is the authenticity gate directive v6.0.7 §1 requires: the HMAC signature only
    proves that the signer held the key and that the body matches what was signed; it
    cannot by itself prove the artifact bytes exist, that they came from the claimed
    scenario, or that the job owned the artifact. The verifier re-reads the bytes from
    the receiver's `data/oneshot.sqlite3`, recomputes sha256, and refuses the evidence
    on any mismatch. The policy is scenario-aware and uses `_SCENARIO_OPERATIONS`.

    When `data/oneshot.sqlite3` is absent (e.g. unit-test paths that monkeypatch
    _EVIDENCE_DIR to a tmp path), the second-channel check is DISABLED for that call —
    the test must set up its own SQLite or exercise negative shape cases instead. A
    missing SQLite in a real receiver release is reported as EVIDENCE_INVALID.
    """
    import hashlib, sqlite3, json as _json
    data_root = data_root or ROOT
    policy = _SCENARIO_OPERATIONS.get(scenario)
    if policy is None:
        return False, {'unknown_scenario_policy': scenario}
    db = data_root / 'data' / 'oneshot.sqlite3'
    if not db.is_file():
        return False, {'missing_sqlite': str(db)}
    try:
        with sqlite3.connect(db) as con:
            con.row_factory = sqlite3.Row
            table = policy['table']
            if table == 'artifacts':
                row = con.execute(
                    'SELECT a.content, a.provider, j.operation FROM artifacts a '
                    'JOIN jobs j ON j.id = a.job_id '
                    'WHERE a.id = ? AND a.job_id = ?',
                    (rec['artifact_id'], rec['job_id'])).fetchone()
                if row is None:
                    return False, {'artifact_not_found_in_sqlite': rec['artifact_id']}
                if row['operation'] not in (policy['operations'] or set()):
                    return False, {'operation_scenario_mismatch': {
                        'expected_one_of': sorted(policy['operations']),
                        'actual': row['operation']}}
                if policy['provider_rule'] == 'not_evidence' and row['provider'] == 'evidence':
                    return False, {'synthetic_provider_rejected': row['provider']}
                content = row['content'] or ''
            elif table == 'prompt_optimizations':
                row = con.execute(
                    'SELECT proposed_content, rationale, provider FROM prompt_optimizations '
                    'WHERE id = ?', (rec['artifact_id'],)).fetchone()
                if row is None:
                    return False, {'optimization_not_found_in_sqlite': rec['artifact_id']}
                if policy['provider_rule'] == 'not_evidence' and row['provider'] == 'evidence':
                    return False, {'synthetic_provider_rejected': row['provider']}
                # Receiver signs sha256 of proposed_content for P12-real-model.
                content = row['proposed_content'] or ''
            elif table == 'improvement_proposals':
                row = con.execute(
                    'SELECT issue_summary, evidence_json FROM improvement_proposals '
                    'WHERE id = ? AND conversation_id IN '
                    '  (SELECT id FROM conversations)',
                    (rec['artifact_id'],)).fetchone()
                if row is None:
                    return False, {'proposal_not_found_in_sqlite': rec['artifact_id']}
                try:
                    prov = (_json.loads(row['evidence_json']).get('model_provenance') or {}).get('provider')
                except Exception:
                    prov = None
                if policy['provider_rule'] == 'not_evidence' and (prov is None or prov == 'evidence'):
                    return False, {'synthetic_or_missing_provenance': prov}
                content = row['issue_summary'] or ''
            else:
                return False, {'unsupported_table': table}
        actual_sha = hashlib.sha256(content.encode('utf-8')
                                     if isinstance(content, str) else content).hexdigest()
        if actual_sha != rec['artifact_sha256']:
            return False, {'artifact_sha_mismatch': {
                'declared': rec['artifact_sha256'][:12],
                'actual_in_sqlite': actual_sha[:12]}}
        return True, {'second_channel': 'ok', 'table': table}
    except sqlite3.DatabaseError as exc:
        return False, {'sqlite_error': str(exc)}


def _nonce_seen_before(nonce, scenario, ledger_path=None):
    """Replay rejection — the same nonce must not appear twice across any scenario.

    The ledger file lives next to the evidence files. Each successful VERIFIED call
    appends `{"scenario": ..., "nonce": ..., "verified_at": ...}` as one JSONL line.
    """
    import json as _json
    ledger_path = ledger_path or _EVIDENCE_NONCE_LEDGER
    if not ledger_path.is_file():
        return False
    try:
        for line in ledger_path.read_text().splitlines():
            if not line.strip(): continue
            try: rec = _json.loads(line)
            except Exception: continue
            if rec.get('nonce') == nonce:
                return True
    except Exception:
        pass
    return False


def _record_nonce(nonce, scenario, ledger_path=None):
    """Record the nonce + scenario so a later run cannot replay the same evidence file."""
    import json as _json, time as _time
    ledger_path = ledger_path or _EVIDENCE_NONCE_LEDGER
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    line = _json.dumps({'scenario': scenario, 'nonce': nonce,
                        'verified_at': _time.strftime('%Y-%m-%dT%H:%M:%SZ', _time.gmtime())})
    with ledger_path.open('a') as f:
        f.write(line + '\n')


def _load_evidence(scenario, hmac_key, current_commit,
                   second_channel=True, data_root=None,
                   evidence_dir=None, nonce_ledger=None):
    """Return (state, detail) for a single scenario.

    state   ∈ {VERIFIED, PENDING_REALMODEL_RUNTIME, EVIDENCE_INVALID}
    detail  is a dict with precise cause classification.
    """
    import ipaddress
    import json as _json
    import urllib.parse
    evidence_dir = evidence_dir or _EVIDENCE_DIR
    path = evidence_dir / f'{scenario}.json'
    if not path.is_file():
        return 'PENDING_REALMODEL_RUNTIME', {'missing_evidence_file': str(path)}
    try:
        rec = _json.loads(path.read_text())
    except Exception as exc:
        return 'EVIDENCE_INVALID', {'malformed_json': str(exc)}
    missing = [f for f in _EVIDENCE_SCHEMA_FIELDS if f not in rec]
    if missing:
        return 'EVIDENCE_INVALID', {'missing_fields': missing}
    if rec['scenario'] != scenario:
        return 'EVIDENCE_INVALID', {'scenario_mismatch': {'declared': rec['scenario'],
                                                           'expected': scenario}}
    # Loopback-only endpoint check (ADR-002).
    try:
        parsed = urllib.parse.urlparse(rec['model_endpoint'])
        host = parsed.hostname or ''
        try: ip = ipaddress.ip_address(host); loopback = ip.is_loopback
        except ValueError: loopback = host in ('localhost',)
        if parsed.scheme not in ('http', 'https') or not loopback:
            return 'EVIDENCE_INVALID', {'non_loopback_endpoint': rec['model_endpoint']}
    except Exception as exc:
        return 'EVIDENCE_INVALID', {'endpoint_parse_error': str(exc)}
    # Portable release identity (directive v6.0.7 §2). An empty current_commit on a non-
    # test receiver means neither git nor BUILD_MANIFEST produced an identity, which is a
    # fail-closed condition — evidence is refused rather than silently accepted.
    if not current_commit:
        return 'EVIDENCE_INVALID', {'release_identity_unavailable': True,
                                     'remediation': 'Package BUILD_MANIFEST.json with host.git_sha, or run inside a git tree.'}
    if rec['oneshot_commit'] != current_commit:
        return 'EVIDENCE_INVALID', {'stale_source_commit': {
            'evidence': rec['oneshot_commit'][:12],
            'current': current_commit[:12],
        }}
    # HMAC signature check — replayed evidence from a different source tree or signed with a
    # different key fails here.
    expected = _hmac_proof(hmac_key, rec['scenario'], rec['oneshot_commit'],
                           rec['job_id'], rec['artifact_sha256'], rec['nonce'])
    import hmac as _hmac
    if not _hmac.compare_digest(expected, rec['proof']):
        return 'EVIDENCE_INVALID', {'bad_hmac': True}
    # Replay check — reject nonce reuse across any scenario.
    if _nonce_seen_before(rec['nonce'], scenario, ledger_path=nonce_ledger):
        return 'EVIDENCE_INVALID', {'replayed_nonce': rec['nonce'][:12]}
    # Second channel — artifact bytes exist in local SQLite, match the declared sha,
    # and the scenario's operation/provider policy is satisfied.
    if second_channel:
        ok, detail = _verify_artifact_second_channel(scenario, rec, data_root=data_root)
        if not ok:
            return 'EVIDENCE_INVALID', {'second_channel': detail}
    # Everything matched — record the nonce so a later run cannot replay this exact
    # evidence file.
    _record_nonce(rec['nonce'], scenario, ledger_path=nonce_ledger)
    return 'VERIFIED', {'evidence_file': str(path),
                        'model_name': rec['model_name'],
                        'job_id': rec['job_id'],
                        'artifact_sha256': rec['artifact_sha256']}


def _realmodel_scenarios_state(results, *, second_channel=True, data_root=None,
                               evidence_dir=None, nonce_ledger=None,
                               current_commit=None):
    """Each required scenario is evaluated independently from its own evidence file.

    If `ONESHOT_EVIDENCE_HMAC_KEY` is unset, no evidence can be validated and every scenario
    reports PENDING_REALMODEL_RUNTIME (same as before the hardening).
    """
    import os
    hmac_key = os.environ.get('ONESHOT_EVIDENCE_HMAC_KEY', '').strip()
    if current_commit is None:
        commit, _src = _release_identity()
    else:
        commit = current_commit
    scenarios = {}
    details = {}
    for sid in REQUIRED_REALMODEL_SCENARIOS:
        if not hmac_key:
            scenarios[sid] = 'PENDING_REALMODEL_RUNTIME'
            details[sid] = {'reason': 'ONESHOT_EVIDENCE_HMAC_KEY unset'}
            continue
        state, detail = _load_evidence(sid, hmac_key, commit,
                                       second_channel=second_channel,
                                       data_root=data_root,
                                       evidence_dir=evidence_dir,
                                       nonce_ledger=nonce_ledger)
        scenarios[sid] = state
        details[sid] = detail
    return scenarios, details


# Mandatory product decisions that must be approved before product_release_ready can be
# true. Each decision is tracked by its own sentinel file; the agent does NOT invent
# acceptance thresholds — the sentinel is written by a human when the decision is signed
# off (directive v6.0.7 §3).
REQUIRED_PRODUCT_DECISIONS = ('P11-semantic',)
_PRODUCT_DECISIONS_DIR = ROOT / 'docs' / 'product_decisions'


def _product_decisions_state(decisions_dir=None):
    """Return (states, details) for every mandatory product decision.

    A decision is RESOLVED only when `docs/product_decisions/<id>.resolved.json` exists,
    is well-formed, and names the decision explicitly. Any other condition (missing,
    malformed, mislabeled) is UNRESOLVED and blocks product_release_ready.
    """
    import json as _json
    decisions_dir = decisions_dir or _PRODUCT_DECISIONS_DIR
    states = {}
    details = {}
    for did in REQUIRED_PRODUCT_DECISIONS:
        sentinel = decisions_dir / f'{did}.resolved.json'
        if not sentinel.is_file():
            states[did] = 'UNRESOLVED'
            details[did] = {'missing_sentinel': str(sentinel)}
            continue
        try:
            rec = _json.loads(sentinel.read_text())
        except Exception as exc:
            states[did] = 'UNRESOLVED'
            details[did] = {'malformed_sentinel': str(exc)}
            continue
        if rec.get('decision') != did:
            states[did] = 'UNRESOLVED'
            details[did] = {'decision_mismatch': {'in_file': rec.get('decision'),
                                                   'expected': did}}
            continue
        if not rec.get('approved_by') or not rec.get('approved_at'):
            states[did] = 'UNRESOLVED'
            details[did] = {'missing_approval_fields': True}
            continue
        states[did] = 'RESOLVED'
        details[did] = {'approved_by': rec['approved_by'],
                        'approved_at': rec['approved_at']}
    return states, details


def verdict(results, host, reason):
    mandatory_failed = [r for r in results
                        if r['gate'] not in OPTIONAL_GATES
                        and r['status'] not in {'OK', 'SKIPPED_PREREQUISITE_MISSING'}]
    optional_skipped = [r for r in results
                        if r['gate'] in OPTIONAL_GATES
                        and r['status'] == 'SKIPPED_PREREQUISITE_MISSING']
    status = 'VALID' if not mandatory_failed else 'NOT_VALID'
    # `release_ready` = structural verifier verdict. The product release decision adds
    # mandatory real-model acceptance AND mandatory product decisions on top;
    # see `product_release_ready` and `blocked_decisions`.
    release_ready = status == 'VALID'
    results = [promote_gate_record(r) for r in results]
    realmodel, realmodel_details = _realmodel_scenarios_state(results)
    blocked = [sid for sid, st in realmodel.items() if st != 'VERIFIED']
    decisions, decision_details = _product_decisions_state()
    blocked_decisions = [did for did, st in decisions.items() if st != 'RESOLVED']
    product_release_ready = release_ready and not blocked and not blocked_decisions
    out = {'status': status,
           'release_ready': release_ready,
           'product_release_ready': product_release_ready,
           'blocked_scenarios': blocked,
           'blocked_decisions': blocked_decisions,
           'realmodel_scenarios': realmodel,
           'realmodel_scenarios_detail': realmodel_details,
           'product_decisions': decisions,
           'product_decisions_detail': decision_details,
           'host': host,
           'gates': results,
           'mandatory_failed_gates': [r['gate'] for r in mandatory_failed],
           'optional_skipped_gates': [r['gate'] for r in optional_skipped]}
    if reason:
        out['halt_reason'] = reason
    outfile = ROOT / 'data' / 'verification' / 'last_run.json'
    outfile.parent.mkdir(parents=True, exist_ok=True)
    outfile.write_text(json.dumps(out, indent=2) + '\n', encoding='utf-8')
    if status == 'VALID':
        print(f'VALID (structural) — all mandatory gates passed; evidence at {outfile}')
        print(f'Optional skipped: {out["optional_skipped_gates"]}')
        if product_release_ready:
            print('product_release_ready: True — all mandatory scenarios + decisions resolved')
        else:
            msg = []
            if blocked: msg.append(f'blocked_scenarios={blocked}')
            if blocked_decisions: msg.append(f'blocked_decisions={blocked_decisions}')
            print('product_release_ready: False — ' + '; '.join(msg))
        return 0
    print(f'NOT_VALID — mandatory failures: {out["mandatory_failed_gates"]}')
    print(f'Evidence at {outfile}')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
