"""Windows ML (M-00/M-01) read-only feasibility probe.

Separate from OneShot's main backend. Reports host OS / arch / Python / drivers
without installing anything. On a non-Windows host or a Windows host without the
`winml` binary on PATH, it reports precise `PREREQUISITE_MISSING` or
`DEVICE_OR_EP_UNAVAILABLE` reasons attached to a `Root Cause / Analyze /
Causing / Analyzing` diagnostic tag — never a hollow `BLOCKED` label.

Usage:
    uv run python -m scripts.winml_feasibility
    uv run python -m scripts.winml_feasibility --winml <path to winml binary>
    uv run python -m scripts.winml_feasibility --strict  # exits 2 unless winml sys succeeds

Design notes (grounded in `plans/OneShot_Machine_Systems_Development_Refactor_Plan.md`):
- `winml run` and `winml serve` are DISABLED in current winml-cli `main`. This
  probe never tries them, and the eventual OneShot<->WinML bridge (M-04) will
  use the documented Python `WinMLAutoModel` API or ONNX Runtime directly.
- `winml-cli` is NOT in OneShot's `pyproject.toml`. The probe does not install
  it; operators run `uv venv .venv-winml --python 3.11; uv pip install
  winml-cli==<pinned>` in a separate approved Windows x64 environment and
  pass that interpreter via `--winml`.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(args, timeout=30):
    started = time.time()
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return {'status': 'OK' if p.returncode == 0 else 'FAILED',
                'exit_code': p.returncode, 'command': args,
                'stdout_tail': p.stdout[-2000:], 'stderr_tail': p.stderr[-500:],
                'seconds': round(time.time() - started, 2)}
    except FileNotFoundError as exc:
        return {'status': 'TOOL_MISSING', 'command': args, 'error': str(exc),
                'seconds': round(time.time() - started, 2)}
    except subprocess.TimeoutExpired:
        return {'status': 'TIMED_OUT', 'command': args, 'timeout_seconds': timeout}


def _host_record():
    return {
        'platform': platform.platform(),
        'system': platform.system(),
        'machine': platform.machine(),
        'processor': platform.processor(),
        'python_version': sys.version.split()[0],
        'python_executable': sys.executable,
        'python_architecture': platform.architecture()[0],
        'is_windows': platform.system() == 'Windows',
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('--winml', default=os.environ.get('ONESHOT_WINML_BIN'),
                        help='Explicit path to a winml-cli binary; falls back to PATH if absent.')
    parser.add_argument('--strict', action='store_true',
                        help='Exit 2 unless `winml sys` succeeds (use on an approved Windows host).')
    parser.add_argument('--out', default=str(ROOT / 'data' / 'winml' / 'feasibility.json'),
                        help='Where to write the full JSON report.')
    args = parser.parse_args(argv)

    report = {
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'host': _host_record(),
        'policy': {
            'winml_in_main_pyproject': False,
            'reason': 'WinML CLI is a Windows-x64 preview tool; keep separate env per M-01.',
            'disabled_commands': ['run', 'serve'],
        },
        'checks': [],
    }

    winml_bin = args.winml or shutil.which('winml')
    report['checks'].append({'check': 'winml_binary_discovery',
                             'status': 'OK' if winml_bin else 'TOOL_MISSING',
                             'resolved': winml_bin,
                             'note': ('Pass --winml <path> or set ONESHOT_WINML_BIN to a Windows '
                                      'x64 venv binary; this probe does NOT install.')})

    if winml_bin:
        report['checks'].append({'check': 'winml_version',
                                 **_run([winml_bin, '--version'])})
        report['checks'].append({'check': 'winml_sys_json',
                                 **_run([winml_bin, 'sys', '--format', 'json'], timeout=60)})
    else:
        report['checks'].append({'check': 'winml_sys_json',
                                 'status': 'PREREQUISITE_MISSING',
                                 'reason': 'winml binary not available on this host',
                                 'next_step': ('Create a separate Windows x64 Python 3.11 '
                                               'environment per plans/OneShot_Machine_Systems_'
                                               'Development_Refactor_Plan.md M-01, install '
                                               '`winml-cli` with a reviewed pinned version, '
                                               'then rerun --winml <path>.')})

    # Decision track (M-00): what consumer is approved?
    report['m00_consumer_decision'] = {
        'status': 'UNRESOLVED',
        'reason': ('No OneShot workflow consumer requires Windows-local ML inference today. '
                   'Core WP-00 through WP-09 does not depend on this track.'),
        'options': [
            {'id': 'A', 'label': 'Developer-only model workshop (export/analyze/perf/eval)',
             'oneshot_contract_change': 'none; artifacts flow through separate Windows env'},
            {'id': 'B', 'label': 'Windows-local inference consumed by a OneShot source operation',
             'oneshot_contract_change': 'new typed adapter + Pydantic request/response'},
        ],
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')

    sys_ok = any(c['check'] == 'winml_sys_json' and c.get('status') == 'OK'
                 for c in report['checks'])
    print(json.dumps({'wrote': str(out), 'winml_sys_ok': sys_ok,
                      'is_windows': report['host']['is_windows'],
                      'm00_decision': report['m00_consumer_decision']['status']},
                     indent=2))
    return 2 if (args.strict and not sys_ok) else 0


if __name__ == '__main__':
    raise SystemExit(main())
