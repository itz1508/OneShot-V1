"""compose.yaml hardening + Dockerfile HEALTHCHECK regression (directive v6.0.10 §gap).

These are market-practice container hardening guarantees:
  * Dockerfile declares a HEALTHCHECK so standalone `docker run` surfaces readiness.
  * compose.yaml refuses privilege escalation via `security_opt: no-new-privileges`.
  * compose.yaml drops all Linux capabilities (the shipped System needs none).

If a future change removes any of these, this test fails.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_declares_healthcheck():
    src = (ROOT / 'Dockerfile').read_text()
    assert 'HEALTHCHECK' in src, 'Dockerfile must carry HEALTHCHECK for standalone docker run'
    # Must probe the /ready endpoint, not /health, per the readiness contract.
    assert '/ready' in src, 'HEALTHCHECK must probe /ready, not /health'


def test_compose_sets_no_new_privileges():
    src = (ROOT / 'compose.yaml').read_text()
    assert 'security_opt' in src
    assert 'no-new-privileges:true' in src, \
        'compose.yaml must set no-new-privileges to block privilege escalation'


def test_compose_drops_all_capabilities():
    src = (ROOT / 'compose.yaml').read_text()
    assert 'cap_drop' in src
    assert '- ALL' in src, 'compose.yaml must drop ALL Linux capabilities'


def test_compose_keeps_read_only_and_tmpfs():
    """Make sure the existing hardening is not accidentally removed alongside the new rules."""
    src = (ROOT / 'compose.yaml').read_text()
    assert 'read_only: true' in src
    assert 'tmpfs' in src
    assert '/tmp' in src
