"""CI workflow pins every runtime-independent E2E suite (directive v6.0.11 C-01).

Each `tests.e2e_*` module below is a supported System E2E suite that must be
executed in CI. The 3 real-model / vision suites that require external
prerequisites (`e2e_live_model`, `e2e_vision_local`) are intentionally
excluded — they are gated by `scripts/verify_release.py` under the real-model
acceptance contract.

If a future change removes an E2E invocation from CI, this test fails so the
drift is caught before deploy.
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
CI = ROOT / '.github' / 'workflows' / 'ci.yml'

REQUIRED_E2E_SUITES = (
    'tests.e2e_http',
    'tests.e2e_presend',
    'tests.e2e_browser',
    'tests.e2e_live_model_local',
    'tests.e2e_backup_restore',
    'tests.e2e_multi_provider_http',
    'tests.e2e_prompt_workspace',
    'tests.e2e_improvement_loop',
    'tests.e2e_improvement_loop_closure',
)


def test_ci_runs_every_runtime_independent_e2e_suite():
    src = CI.read_text()
    missing = [m for m in REQUIRED_E2E_SUITES if f'python -m {m}' not in src]
    assert not missing, (
        f'CI workflow must invoke every runtime-independent E2E suite; missing: {missing}'
    )


def test_ci_e2e_job_declares_a_bounded_timeout():
    """Playwright runs can hang; the e2e job must declare a timeout so a stuck
    worker fails CI rather than consuming the GitHub Actions billing cap."""
    src = CI.read_text()
    # Find the e2e job block
    match = re.search(r'^  e2e:\n(?P<body>(?:    .*\n)+)', src, re.MULTILINE)
    assert match, 'e2e job not found'
    assert 'timeout-minutes' in match.group('body'), (
        'CI e2e job must declare timeout-minutes to bound stuck Playwright runs')


def test_ci_does_not_run_prereq_gated_suites():
    """The two real-model / vision suites that require external prerequisites
    must stay out of CI — they are gated by the release-verifier acceptance
    contract, not by deterministic CI."""
    src = CI.read_text()
    for banned in ('python -m tests.e2e_live_model',
                   'python -m tests.e2e_vision_local'):
        # Exclusion must be exact; e2e_live_model_local is fine (local protocol stub).
        pattern = re.escape(banned) + r'\b'
        assert not re.search(pattern + r'(?!_local)', src), (
            f'CI must not invoke {banned} — it depends on an external runtime '
            'that is tracked separately via the real-model acceptance contract')
