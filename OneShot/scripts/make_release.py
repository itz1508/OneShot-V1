"""Reproducible release packaging — tarball + SBOMs + manifest + SHA sums.

Writes to ``dist/`` and prints the final SHA-256. The release tarball embeds
``dist/sbom.python.cyclonedx.json`` and ``dist/sbom.frontend.cyclonedx.json``
under ``OneShot/dist/`` so a downstream auditor can verify every pinned
dependency from the shipped artifact alone.

Usage:
    uv run python -m scripts.make_release
    uv run python -m scripts.make_release --output dist/oneshot-release.tar.gz
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / 'dist'

EXCLUDE_PREFIXES = ('dist/', 'frontend/node_modules/', 'frontend/dist/', 'data/', '.git/')
EXCLUDE_NAME_PARTS = {'__pycache__', '.pytest_cache', '.ruff_cache', '.git', '.venv'}
# BUILD_MANIFEST self-exclusion: the manifest describes the source tree; listing itself
# would create a circular hash dependency (new manifest -> new sha -> old sha mismatch).
# It is still packed into the archive and listed in SHA256SUMS, just not inside the
# manifest's own entries[].
SELF_EXCLUDE = {'BUILD_MANIFEST.json'}


def _run(cmd, cwd=ROOT, env=None):
    r = subprocess.run(cmd, cwd=cwd, env=env or {**os.environ},
                       capture_output=True, text=True, timeout=600)
    if r.returncode != 0:
        raise SystemExit(f'command failed: {" ".join(cmd)}\n{r.stderr}')
    return r.stdout


def _is_excluded(rel: str) -> bool:
    if rel in SELF_EXCLUDE:
        return True
    if rel.endswith('.pyc'):
        return True
    if any(rel.startswith(pref) for pref in EXCLUDE_PREFIXES):
        return True
    # pytest tmp cache dirs (created by playwright/pytest sessions at project root)
    parts = rel.split('/')
    if any(part.startswith('pytest-cache-files-') for part in parts):
        return True
    return any(part in EXCLUDE_NAME_PARTS or part.endswith('.egg-info')
               for part in parts)


def _git_sha():
    try:
        r = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(ROOT),
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0:
            return r.stdout.strip()
    except FileNotFoundError:
        pass
    return None


def _generate_sboms():
    DIST.mkdir(parents=True, exist_ok=True)
    # Python SBOM via pip-audit (same tool already in CI; no new dep).
    req = DIST / 'requirements.txt'
    _run(['uv', 'export', '--format', 'requirements-txt', '--no-dev',
          '--no-editable', '--no-emit-workspace', '--no-emit-project',
          '--output-file', str(req)])
    _run(['uv', 'run', '--with', 'pip-audit', 'pip-audit',
          '--requirement', str(req), '--disable-pip',
          '--format', 'cyclonedx-json',
          '--output', str(DIST / 'sbom.python.cyclonedx.json')])
    # Frontend SBOM via `npm sbom` (Node 22+ built-in).
    sb = _run(['npm', 'sbom', '--omit=dev', '--sbom-format=cyclonedx'],
              cwd=ROOT / 'frontend')
    (DIST / 'sbom.frontend.cyclonedx.json').write_text(sb)
    return DIST / 'sbom.python.cyclonedx.json', DIST / 'sbom.frontend.cyclonedx.json'


def _collect_manifest_entries():
    entries = []
    for p in sorted(ROOT.rglob('*')):
        if p.is_dir():
            continue
        rel = str(p.relative_to(ROOT)).replace('\\', '/')
        if _is_excluded(rel):
            continue
        data = p.read_bytes()
        entries.append({
            'path': rel,
            'sha256': hashlib.sha256(data).hexdigest(),
            'bytes': len(data),
        })
    return entries


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument('--output', default=str(DIST / 'oneshot-release.tar.gz'),
                        help='Target tarball path (default dist/oneshot-release.tar.gz)')
    parser.add_argument('--skip-sbom', action='store_true',
                        help='Skip SBOM regeneration (uses previous dist/sbom.*.json).')
    args = parser.parse_args(argv)

    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if not args.skip_sbom:
        _generate_sboms()
    py_sbom = DIST / 'sbom.python.cyclonedx.json'
    fe_sbom = DIST / 'sbom.frontend.cyclonedx.json'
    if not py_sbom.is_file() or not fe_sbom.is_file():
        raise SystemExit('SBOMs missing; rerun without --skip-sbom')

    # Build BUILD_MANIFEST (deterministic, matches tarball contents).
    entries = _collect_manifest_entries()
    manifest = {
        'format': 'oneshot-source-manifest-v2',
        'description': ('OneShot complete System build with embedded CycloneDX '
                        'SBOMs; see dist/sbom.*.cyclonedx.json inside the archive.'),
        'generated_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'host': {
            'python': sys.version.split()[0],
            'platform': platform.platform(),
            'machine': platform.machine(),
            'git_sha': _git_sha(),
        },
        'entries': entries,
    }
    (ROOT / 'BUILD_MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')

    # Build tarball. Embeds dist/sbom.*.cyclonedx.json so auditors get them
    # inside the shipped artifact.
    if output.exists():
        output.unlink()
    with tarfile.open(output, 'w:gz') as tf:
        def add(path: Path, arcname: str):
            tf.add(str(path), arcname=arcname, recursive=False)

        for e in entries:
            add(ROOT / e['path'], f"OneShot/{e['path']}")
        # BUILD_MANIFEST is excluded from entries[] (self-reference), still shipped.
        add(ROOT / 'BUILD_MANIFEST.json', 'OneShot/BUILD_MANIFEST.json')
        # Embed SBOMs under OneShot/dist/ in the tarball (NOT in the source tree).
        add(py_sbom, 'OneShot/dist/sbom.python.cyclonedx.json')
        add(fe_sbom, 'OneShot/dist/sbom.frontend.cyclonedx.json')

    tar_bytes = output.read_bytes()
    tar_sha = hashlib.sha256(tar_bytes).hexdigest()
    sums_path = output.with_suffix(output.suffix + '.SHA256SUMS.txt') \
        if output.suffix != '.gz' else output.with_name(output.name.replace('.tar.gz', '-SHA256SUMS.txt'))
    sums = [f'{tar_sha}  {output.name}']
    for e in entries:
        sums.append(f'{e["sha256"]}  OneShot/{e["path"]}')
    manifest_bytes = (ROOT / 'BUILD_MANIFEST.json').read_bytes()
    sums.append(f'{hashlib.sha256(manifest_bytes).hexdigest()}  OneShot/BUILD_MANIFEST.json')
    for extra, name in ((py_sbom, 'OneShot/dist/sbom.python.cyclonedx.json'),
                        (fe_sbom, 'OneShot/dist/sbom.frontend.cyclonedx.json')):
        sums.append(f'{hashlib.sha256(extra.read_bytes()).hexdigest()}  {name}')
    sums_path.write_text('\n'.join(sums) + '\n')

    print(json.dumps({
        'wrote_tarball': str(output),
        'tarball_sha256': tar_sha,
        'tarball_bytes': len(tar_bytes),
        'sha256sums_file': str(sums_path),
        'manifest_entries': len(entries),
        'embedded_sboms': ['dist/sbom.python.cyclonedx.json',
                           'dist/sbom.frontend.cyclonedx.json'],
        'git_sha': manifest['host']['git_sha'],
    }, indent=2))


if __name__ == '__main__':
    main()
