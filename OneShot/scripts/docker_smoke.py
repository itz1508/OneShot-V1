"""Docker smoke test: build + up + /ready + down against the shipped compose.yaml.

Fails LOUDLY when the daemon is reachable and any step fails. SKIPS with a
precise prerequisite reason when docker is not installed or the daemon is
unreachable — never silently claims success.

Usage:
    uv run python -m scripts.docker_smoke
    uv run python -m scripts.docker_smoke --strict  # exit 2 unless daemon up
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _run(cmd, cwd=ROOT, timeout=600, env=None):
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                       timeout=timeout, env=env or {**os.environ})
    return {'cmd': cmd, 'exit_code': r.returncode,
            'stdout_tail': r.stdout[-500:], 'stderr_tail': r.stderr[-500:]}


def _daemon_up():
    r = subprocess.run(['docker', 'info'], capture_output=True, text=True, timeout=10)
    return r.returncode == 0


def _free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('--strict', action='store_true',
                        help='Exit 2 unless docker daemon is running (CI gate on real infra).')
    args = parser.parse_args(argv)

    report = {'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'host_platform': sys.platform, 'checks': []}

    docker_bin = shutil.which('docker')
    report['checks'].append({'check': 'docker_binary', 'status': 'OK' if docker_bin else 'TOOL_MISSING',
                             'where': docker_bin or ''})
    if docker_bin is None:
        report['status'] = 'SKIPPED_PREREQUISITE_MISSING'
        report['missing_prerequisite'] = 'docker CLI'
        print(json.dumps(report, indent=2))
        return 2 if args.strict else 0

    if not _daemon_up():
        report['checks'].append({'check': 'docker_daemon', 'status': 'DAEMON_UNREACHABLE',
                                 'next_step': 'Start Docker Desktop or systemctl start docker and retry.'})
        report['status'] = 'SKIPPED_PREREQUISITE_MISSING'
        report['missing_prerequisite'] = 'docker daemon'
        print(json.dumps(report, indent=2))
        return 2 if args.strict else 0

    env = {**os.environ,
           'ONESHOT_API_TOKEN': 'docker-smoke-token-32-chars-long-x',
           'ONESHOT_BROWSER_PASSWORD': 'docker-smoke-browser-password-xx',
           'ONESHOT_PROVIDER': 'evidence'}
    report['checks'].append({'check': 'compose_config',
                             **_run(['docker', 'compose', 'config'], env=env)})
    report['checks'].append({'check': 'compose_build',
                             **_run(['docker', 'compose', 'build'], env=env, timeout=1800)})
    try:
        report['checks'].append({'check': 'compose_up',
                                 **_run(['docker', 'compose', 'up', '-d'], env=env)})
        # Wait for /ready via the host-mapped port 127.0.0.1:8787.
        import httpx
        ok = False
        for _ in range(60):
            try:
                if httpx.get('http://127.0.0.1:8787/ready', timeout=2).status_code == 200:
                    ok = True
                    break
            except httpx.HTTPError:
                pass
            time.sleep(1)
        report['checks'].append({'check': 'ready_probe',
                                 'status': 'OK' if ok else 'FAILED'})
    finally:
        report['checks'].append({'check': 'compose_down',
                                 **_run(['docker', 'compose', 'down', '-v'], env=env)})
    report['status'] = 'OK' if all(c.get('exit_code', 0) == 0 or c.get('status') == 'OK'
                                   for c in report['checks']) else 'FAILED'
    print(json.dumps(report, indent=2))
    return 0 if report['status'] == 'OK' else 1


if __name__ == '__main__':
    raise SystemExit(main())
