"""Offline self-check: DB round-trip, FileStore sanity, frontend build presence.

Usage:
    uv run python -m scripts.selfcheck
    uv run python -m scripts.selfcheck --data-dir /path/to/data

Exit codes:
    0 — all components healthy
    2 — one or more components failed; details printed to stderr
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from systems.settings import Settings
from systems.store import Store


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _frontend_ready(frontend_dir: Path) -> bool:
    return frontend_dir.is_dir() and (frontend_dir / 'index.html').is_file()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='OneShot offline self-check')
    parser.add_argument('--data-dir', type=Path, default=None,
                        help='Data directory to check (defaults to the one Settings would resolve).')
    parser.add_argument('--frontend-dir', type=Path, default=None,
                        help='Frontend dist directory (defaults to <repo>/frontend/dist).')
    parser.add_argument('--token', type=str, default='x' * 32,
                        help='API token used only to construct Settings; never sent anywhere.')
    args = parser.parse_args(argv)

    data_dir = args.data_dir or _repo_root() / 'data'
    frontend_dir = args.frontend_dir or _repo_root() / 'frontend' / 'dist'
    components: dict[str, str] = {}

    data_dir.mkdir(parents=True, exist_ok=True)
    try:
        settings = Settings(data_dir=data_dir, api_token=args.token)
        store = Store(settings.data_dir)
        store.one('SELECT 1 AS ok')
        components['storage'] = 'ok'
    except Exception as exc:  # noqa: BLE001 — report any failure, not raise
        components['storage'] = f'unavailable: {exc}'

    try:
        store = Store(data_dir)
        store.files.sanity()
        components['file_store'] = 'ok'
    except Exception as exc:  # noqa: BLE001
        components['file_store'] = f'unavailable: {exc}'

    components['frontend'] = 'ok' if _frontend_ready(frontend_dir) else 'not_built'

    ok = components['storage'] == 'ok' and components['file_store'] == 'ok'
    report = {'ok': ok, 'components': components,
              'data_dir': str(data_dir), 'frontend_dir': str(frontend_dir)}
    print(json.dumps(report, indent=2))
    if not ok:
        print('selfcheck failed; see components above', file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
