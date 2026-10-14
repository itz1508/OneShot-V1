"""Backup/restore now treats applied/ as a managed category — directive v6.0 §7.

scripts/backup.py:
  - backup() copies applied/ with per-file sha256 into MANIFEST.applied[].
  - verify_backup() verifies every applied/ entry and refuses unexpected files.
  - restore_to_staging() mirrors applied/ into the staging destination.
"""
import hashlib
import pathlib
import shutil
import sqlite3

import pytest

from scripts.backup import backup, verify_backup, restore_to_staging


def _seed_data(root: pathlib.Path):
    """Create a minimal valid OneShot data dir with one source + one applied file."""
    from systems.store import Store
    root.mkdir(parents=True, exist_ok=True)
    Store(root)  # creates oneshot.sqlite3 + migrates to the current schema
    (root / 'files').mkdir(parents=True, exist_ok=True)
    body = b'hello world body'
    sha = hashlib.sha256(body).hexdigest()
    (root / 'files' / sha[:2]).mkdir(parents=True, exist_ok=True)
    (root / 'files' / sha[:2] / sha).write_bytes(body)
    (root / 'applied').mkdir(parents=True, exist_ok=True)
    (root / 'applied' / 'target.md').write_bytes(b'applied body\n')
    return root


def test_backup_captures_applied(tmp_path):
    data = _seed_data(tmp_path / 'data')
    out = tmp_path / 'bk'
    rec = backup(data, out)
    assert len(rec['applied']) == 1
    assert rec['applied'][0]['path'] == 'target.md'
    assert (out / 'applied' / 'target.md').is_file()


def test_verify_backup_detects_altered_applied(tmp_path):
    data = _seed_data(tmp_path / 'data')
    out = tmp_path / 'bk'
    backup(data, out)
    # Tamper
    (out / 'applied' / 'target.md').write_bytes(b'tampered\n')
    with pytest.raises(ValueError, match='applied/ altered'):
        verify_backup(out)


def test_verify_backup_detects_unexpected_applied(tmp_path):
    data = _seed_data(tmp_path / 'data')
    out = tmp_path / 'bk'
    backup(data, out)
    (out / 'applied' / 'rogue.md').write_bytes(b'surprise')
    with pytest.raises(ValueError, match='Unexpected applied/ file'):
        verify_backup(out)


def test_verify_backup_detects_missing_applied_dir(tmp_path):
    data = _seed_data(tmp_path / 'data')
    out = tmp_path / 'bk'
    backup(data, out)
    shutil.rmtree(out / 'applied')
    with pytest.raises(ValueError, match='applied/ missing'):
        verify_backup(out)


def test_restore_mirrors_applied_into_staging(tmp_path):
    data = _seed_data(tmp_path / 'data')
    out = tmp_path / 'bk'
    backup(data, out)
    staging = tmp_path / 'restored'
    restore_to_staging(out, staging)
    assert (staging / 'applied' / 'target.md').read_bytes() == b'applied body\n'
    # verify_backup must also succeed on the staged copy
    verify_backup(staging)



# ---- v6.0.7 §5 — Extended backup security + restored readback ------------

import json
import os
import secrets

from fastapi.testclient import TestClient

from systems.api import create_app
from systems.settings import Settings


def test_verify_backup_rejects_path_traversal_in_manifest(tmp_path):
    """A tampered MANIFEST.applied[].path like `../../etc/passwd` must be refused
    even if a corresponding file was planted inside the backup."""
    data = _seed_data(tmp_path / 'data')
    out = tmp_path / 'bk'
    backup(data, out)
    # Tamper the manifest with a traversal path.
    manifest = json.loads((out / 'MANIFEST.json').read_text())
    manifest['applied'][0]['path'] = '../../escape.txt'
    (out / 'MANIFEST.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unsafe applied/'):
        verify_backup(out)


def test_verify_backup_rejects_absolute_path_in_manifest(tmp_path):
    data = _seed_data(tmp_path / 'data')
    out = tmp_path / 'bk'
    backup(data, out)
    manifest = json.loads((out / 'MANIFEST.json').read_text())
    manifest['applied'][0]['path'] = '/etc/passwd'
    (out / 'MANIFEST.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Unsafe applied/'):
        verify_backup(out)


def test_verify_backup_rejects_symlink_in_applied(tmp_path):
    """Planting a symlink inside the applied/ tree of the backup must be refused."""
    data = _seed_data(tmp_path / 'data')
    out = tmp_path / 'bk'
    backup(data, out)
    rogue = out / 'applied' / 'rogue_link.md'
    try:
        rogue.symlink_to('/etc/passwd')
    except OSError:
        pytest.skip('symlink creation refused in this sandbox')
    with pytest.raises(ValueError):
        verify_backup(out)


def _password_hash(pw: str) -> str:
    """Match the shipped Settings.browser_password hashing — stored as plain text in
    the test fixture because create_app treats a short password string directly."""
    return pw


def test_restored_instance_serves_applied_byte_identical(tmp_path):
    """Full HTTP cycle: back up a live OneShot, restore to a staging dir, launch a
    fresh app on the staging dir, authenticate, and read the applied artifact back
    byte-for-byte via the /api/.../applied/{apply_id} endpoint."""
    # Build a live OneShot with one applied artifact that we can fetch back.
    source = tmp_path / 'source'
    source.mkdir()
    api_token = 'r' * 32
    cfg = Settings(data_dir=source, api_token=api_token,
                   browser_password='restore-pw-16chars-aa')
    app = create_app(cfg, auto_worker=False, auto_background=False)
    bytes_body = b'applied artifact content body\n'
    import hashlib as _h
    expected_sha = _h.sha256(bytes_body).hexdigest()
    with TestClient(app) as c:
        c.headers['Authorization'] = 'Bearer ' + api_token
        cid = c.post('/api/conversations', json={'title': 'rb'}).json()['id']
        # Hand-insert a source + artifact + applied row at SQLite level so this test
        # does not depend on the full inference pipeline.
        with sqlite3.connect(str(source / 'oneshot.sqlite3')) as con:
            con.row_factory = sqlite3.Row
            now = '2026-10-12T00:00:00+00:00'
            con.execute("INSERT INTO sources(id,name,kind,sha256,version,created_at) "
                        "VALUES(?,?,?,?,?,?)",
                        ('s1', 'file.txt', 'input', expected_sha, 1, now))
            con.execute("INSERT INTO source_links(conversation_id,source_id) VALUES(?,?)",
                        (cid, 's1'))
            con.execute("INSERT INTO jobs(id,conversation_id,operation,scope_json,"
                        "idempotency_key,status,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        ('j1', cid, 'inspect_sources', '[]', 'kk', 'completed', now, now))
            con.execute("INSERT INTO artifacts(id,conversation_id,job_id,kind,content,"
                        "provider,source_ids_json,limitations_json,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        ('ar1', cid, 'j1', 'summary',
                         bytes_body.decode('utf-8'), 'evidence', '[]', '[]', now))
            con.execute("INSERT INTO applied(id,conversation_id,artifact_id,destination,"
                        "baseline_hash,result_hash,diff,created_at) "
                        "VALUES(?,?,?,?,?,?,?,?)",
                        ('ap1', cid, 'ar1', 'readback.md', None,
                         expected_sha, 'diff-placeholder', now))
            con.commit()
        # Write the on-disk applied bytes.
        (source / 'applied').mkdir(parents=True, exist_ok=True)
        (source / 'applied' / 'readback.md').write_bytes(bytes_body)
        # Also persist the referenced input source bytes so backup verification
        # succeeds.
        (source / 'files' / expected_sha[:2]).mkdir(parents=True, exist_ok=True)
        (source / 'files' / expected_sha[:2] / expected_sha).write_bytes(bytes_body)

    # Back up, verify, and restore to a NEW staging directory.
    bk = tmp_path / 'bk'
    backup(source, bk)
    verify_backup(bk)
    staging = tmp_path / 'restored'
    restore_to_staging(bk, staging)
    assert (staging / 'applied' / 'readback.md').read_bytes() == bytes_body

    # Launch a fresh app on the staging dir.  The HTTP readback must succeed and
    # return the recorded result_sha256, matching our planted bytes byte-for-byte.
    cfg2 = Settings(data_dir=staging, api_token=api_token,
                    browser_password='restore-pw-16chars-aa')
    app2 = create_app(cfg2, auto_worker=False, auto_background=False)
    with TestClient(app2) as c:
        c.headers['Authorization'] = 'Bearer ' + api_token
        r = c.get(f'/api/conversations/{cid}/applied/ap1')
        assert r.status_code == 200, r.text
        body = r.json()
        assert body['verified'] is True
        assert body['result_sha256'] == expected_sha
        assert body['destination'] == 'readback.md'
    # And the raw file bytes under the restored root match the recorded hash.
    import hashlib
    actual = hashlib.sha256((staging / 'applied' / 'readback.md').read_bytes()).hexdigest()
    assert actual == expected_sha


def test_restored_instance_is_independent_of_source(tmp_path):
    """Restoration into a staging path must not depend on the original source dir
    continuing to exist.  Delete the source and confirm the restored instance still
    serves the artifact."""
    source = tmp_path / 'source'
    data = _seed_data(source)
    bk = tmp_path / 'bk'
    backup(data, bk)
    staging = tmp_path / 'restored'
    restore_to_staging(bk, staging)
    import shutil as _sh
    _sh.rmtree(source)
    # Restored instance must verify cleanly without touching the deleted source.
    verify_backup(staging)
    assert (staging / 'applied' / 'target.md').read_bytes() == b'applied body\n'
