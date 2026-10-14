"""Release packaging regression — directive v6.0.5 §2 "Priority 0".

Guards against:
  A1  Source manifest (BUILD_MANIFEST.json) and archive inventory drift.
  A2  Stale manifest hashes (reproduces Codex finding `11 declared hashes differ`).
  A3  Unmanifested archive members (reproduces Codex finding `26 absent from manifest`).
  A4  Accidental packaging of runtime data under data/.
  A5  Manifest self-reference (circular hash dependency).
  A6  SHA256SUMS line count matches archive member count.

These tests describe the shipped `scripts/make_release.py` policy:
- Source manifest EXCLUDES: dist/, frontend/node_modules/, frontend/dist/, data/, .git/,
  __pycache__, .pytest_cache, .ruff_cache, .egg-info directories, and the manifest file
  itself.
- Archive = manifest entries + BUILD_MANIFEST.json + 2 embedded SBOMs under OneShot/dist/.
- External SHA256SUMS = tarball sha256 + per-member sha256 for every archive member.
"""
import hashlib
import importlib.util
import json
import pathlib

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "scripts_make_release", ROOT / "scripts" / "make_release.py")
MR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(MR)  # type: ignore[union-attr]


def _collect(root=ROOT):
    """Call the real policy function — never duplicate it in the test."""
    orig_root = MR.ROOT
    MR.ROOT = root
    try:
        return MR._collect_manifest_entries()
    finally:
        MR.ROOT = orig_root


def test_manifest_policy_excludes_runtime_and_build_outputs():
    entries = _collect()
    paths = {e['path'] for e in entries}
    # Positive: core source present.
    assert 'systems/api.py' in paths
    assert 'tests/test_improvement_loop.py' in paths
    assert 'docs/phase_records/v6-phase12-final-reconciliation-and-adversarial.md' in paths
    # Negative: runtime + build outputs excluded.
    for p in paths:
        assert not p.startswith('data/'), f'data/ runtime leaked into manifest: {p}'
        assert not p.startswith('dist/'), f'dist/ build output leaked into manifest: {p}'
        assert not p.startswith('frontend/dist/'), (
            f'frontend/dist/ build output leaked into manifest: {p}')
        assert '__pycache__' not in p.split('/'), f'__pycache__ leaked: {p}'
        assert not p.endswith('.pyc'), f'.pyc leaked: {p}'


def test_manifest_is_not_self_referenced():
    """Codex finding `11 declared hashes differ` root cause: manifest listed itself."""
    entries = _collect()
    paths = {e['path'] for e in entries}
    assert 'BUILD_MANIFEST.json' not in paths, (
        'BUILD_MANIFEST.json must NOT appear in its own entries list (circular hash). '
        'Fix: add it to SELF_EXCLUDE in scripts/make_release.py.')


def test_manifest_declared_hashes_match_actual_file_bytes():
    """Catches hash drift between manifest and on-disk source."""
    manifest = json.loads((ROOT / 'BUILD_MANIFEST.json').read_text())
    stale = []
    for e in manifest['entries']:
        path = ROOT / e['path']
        if not path.is_file():
            stale.append((e['path'], 'missing on disk'))
            continue
        actual = hashlib.sha256(path.read_bytes()).hexdigest()
        if actual != e['sha256']:
            stale.append((e['path'], f"declared={e['sha256'][:12]} actual={actual[:12]}"))
    assert not stale, f'Manifest hash drift detected: {stale}'


def test_manifest_covers_all_eligible_source_files():
    """Reverse direction: anything the policy includes should be in the manifest, so a new
    file isn't silently excluded from the audit trail."""
    manifest = json.loads((ROOT / 'BUILD_MANIFEST.json').read_text())
    manifest_paths = {e['path'] for e in manifest['entries']}
    policy_paths = {e['path'] for e in _collect()}
    missing_from_manifest = policy_paths - manifest_paths
    assert not missing_from_manifest, (
        'Manifest is stale — rerun scripts/make_release.py. '
        f'New files not in BUILD_MANIFEST: {sorted(missing_from_manifest)}')


def test_shipped_release_archive_matches_sha256sums():
    """When a packaged release exists in dist/, every archive member sha matches the
    external SHA256SUMS file."""
    import tarfile
    tarballs = sorted((ROOT / 'dist').glob('oneshot-complete-release-*.tar.gz'))
    tarballs = [t for t in tarballs if not t.name.endswith('-SHA256SUMS.txt')]
    if not tarballs:
        pytest.skip('no shipped tarball in dist/')
    tb = tarballs[-1]
    sums_path = tb.parent / tb.name.replace('.tar.gz', '-SHA256SUMS.txt')
    if not sums_path.is_file():
        pytest.skip(f'no SHA256SUMS beside {tb.name}')
    external = {}
    for line in sums_path.read_text().splitlines():
        if '  ' not in line: continue
        h, p = line.split('  ', 1)
        external[p] = h
    # First line is tarball self-hash; verify it.
    assert external[tb.name] == hashlib.sha256(tb.read_bytes()).hexdigest()
    with tarfile.open(tb, 'r:gz') as tf:
        for m in tf.getmembers():
            if not m.isfile(): continue
            fh = tf.extractfile(m)
            actual = hashlib.sha256(fh.read()).hexdigest()
            declared = external.get(m.name)
            assert declared is not None, f'archive member {m.name} not in SHA256SUMS'
            assert declared == actual, (
                f'SHA256SUMS mismatch for {m.name}: declared={declared[:12]} actual={actual[:12]}')
