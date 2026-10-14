"""M-00/M-01 feasibility probe reports precise prerequisite status.

On a non-Windows build host without `winml` on PATH the probe must:
- exit 0 (optional track, non-fatal to the main-product build)
- write a JSON report whose host.is_windows is False
- record `winml_binary_discovery: TOOL_MISSING`
- record `winml_sys_json: PREREQUISITE_MISSING` with an actionable next_step

The probe must NEVER install `winml-cli` or modify `pyproject.toml`.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_has_no_winml_cli_dependency():
    pyproject = (ROOT / 'pyproject.toml').read_text()
    # pyproject must stay free of winml-cli so OneShot's Linux container keeps
    # working. The Windows env is separate per M-01.
    assert 'winml-cli' not in pyproject, 'pyproject.toml must not install winml-cli'


def test_feasibility_probe_runs_cleanly_on_non_windows(tmp_path):
    out = tmp_path / 'feasibility.json'
    r = subprocess.run([sys.executable, '-m', 'scripts.winml_feasibility',
                        '--out', str(out)],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert out.is_file(), r.stdout
    data = json.loads(out.read_text())
    # On non-Windows: binary missing is expected, probe records it precisely.
    if not data['host']['is_windows']:
        statuses = {c['check']: c['status'] for c in data['checks']}
        assert statuses.get('winml_binary_discovery') == 'TOOL_MISSING'
        assert statuses.get('winml_sys_json') == 'PREREQUISITE_MISSING'
    # Decision track is honestly surfaced as UNRESOLVED when no M-00 consumer
    # is approved; this is not a failure of the probe itself.
    assert data['m00_consumer_decision']['status'] in {'UNRESOLVED', 'ACCEPTED'}


def test_strict_mode_exits_nonzero_on_missing_winml():
    r = subprocess.run([sys.executable, '-m', 'scripts.winml_feasibility',
                        '--strict'],
                       cwd=str(ROOT), capture_output=True, text=True, timeout=60)
    # Strict mode should fail when the binary is missing. This is only used
    # on an approved Windows host where the binary MUST be present.
    import platform
    if platform.system() == 'Windows':
        pytest.skip('Strict-mode negative test is only meaningful off Windows')
    assert r.returncode == 2, r.stdout + r.stderr
