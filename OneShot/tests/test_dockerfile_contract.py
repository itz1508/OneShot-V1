"""Dockerfile + compose.yaml static contract.

Proves the deployment artifacts are coherent against the running code without
needing a Docker daemon on PATH. The live-boot smoke test lives in
`scripts/docker_smoke.py` and runs when a daemon is available.
"""
from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def test_dockerfile_installs_from_pyproject_and_pins_user():
    df = (ROOT / 'Dockerfile').read_text()
    # Must install from the pinned uv.lock (strict reproducibility).
    assert 'uv sync --frozen' in df, 'Dockerfile must install from uv.lock'
    assert 'uv.lock' in df, 'Dockerfile must COPY uv.lock into the image'
    assert 'winml-cli' not in df, 'WinML CLI must stay out of the Linux container'
    # Non-root execution + explicit UID.
    assert re.search(r'USER\s+\d+', df) or 'USER oneshot' in df
    # Frontend build is a multi-stage artifact copied in, not rebuilt on run.
    assert 'FROM node:' in df and 'FROM python:3.11' in df
    assert 'COPY --from=frontend-build' in df


def test_dockerfile_cmd_uses_factory_app():
    df = (ROOT / 'Dockerfile').read_text()
    # The /ready probe needs a reachable Uvicorn with the FastAPI factory.
    assert 'uvicorn' in df and 'systems.api:create_app' in df and '--factory' in df
    assert '--port' in df and '8787' in df


def test_compose_binds_loopback_only_and_requires_envs():
    body = (ROOT / 'compose.yaml').read_text()
    # Server must bind 127.0.0.1 explicitly; must never claim 0.0.0.0 by default.
    assert '"127.0.0.1:8787:8787"' in body
    # Secrets must come from the environment, not baked in.
    assert 'ONESHOT_API_TOKEN: ${ONESHOT_API_TOKEN:?Set server API token}' in body
    assert 'ONESHOT_BROWSER_PASSWORD: ${ONESHOT_BROWSER_PASSWORD:?Set operator sign-in password}' in body
    # Container must stay read-only; data dir is a named volume.
    assert 'read_only: true' in body
    assert 'oneshot_data:/data' in body
    # Healthcheck hits /ready in-container; a readiness failure must drain traffic.
    assert '/ready' in body or '/health' in body, 'compose must have a healthcheck'


def test_compose_healthcheck_targets_ready_endpoint_when_present():
    body = (ROOT / 'compose.yaml').read_text()
    # When /ready exists in the app (it does), the production healthcheck
    # must use it: /health only answers liveness, /ready answers readiness.
    assert '/ready' in body, (
        'compose.yaml healthcheck should hit /ready now that the readiness '
        'endpoint exists; see docs/API.md for the liveness/readiness split.'
    )
