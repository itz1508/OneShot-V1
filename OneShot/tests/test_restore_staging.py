import hashlib
import pytest
from scripts.backup import backup, restore_to_staging
from systems.store import Store


def test_restore_to_new_staging_preserves_identity_and_original(tmp_path):
    source=tmp_path/'active'; db=Store(source)
    raw=b'immutable project evidence'
    sha=db.files.put(raw)
    with db.tx() as con:
        con.execute("INSERT INTO conversations VALUES ('conversation','original',0)")
        con.execute("INSERT INTO sources(id,name,kind,sha256,version,created_at) VALUES(?,?,?,?,1,?)",
                    ('a'*32,'original.md','input',sha,'2026-10-10'))
        con.execute('INSERT INTO source_links VALUES (?,?)', ('conversation','a'*32))
    original_hash=hashlib.sha256((source/'oneshot.sqlite3').read_bytes()).hexdigest()
    b=tmp_path/'backup'; expected=backup(source,b)
    staged=tmp_path/'staged'
    assert restore_to_staging(b,staged)==expected
    from scripts.backup import verify_backup
    assert verify_backup(staged) == expected
    restored=Store(staged)
    assert restored.one("SELECT title FROM conversations WHERE id='conversation'")['title']=='original'
    assert restored.files.read(sha)==raw
    assert hashlib.sha256((source/'oneshot.sqlite3').read_bytes()).hexdigest()==original_hash
    with pytest.raises(FileExistsError):restore_to_staging(b,staged)


def test_invalid_restore_fails_before_target_created(tmp_path):
    source=tmp_path/'source';db=Store(source);sha=db.files.put(b'original')
    with db.tx() as con:
        con.execute("INSERT INTO sources(id,name,kind,sha256,version,created_at) VALUES(?,?,?,?,1,?)",
                    ('b'*32,'source.md','input',sha,'2026-10-10'))
    b=tmp_path/'backup';backup(source,b)
    (b/'files'/sha[:2]/sha).write_bytes(b'tamper')
    output=tmp_path/'staged'
    with pytest.raises(ValueError):restore_to_staging(b,output)
    assert not output.exists()


def test_staging_rejects_symlinked_source_bytes(tmp_path):
    source=tmp_path/'active';store=Store(source)
    raw=b'retained source';sha=store.files.put(raw)
    with store.tx() as con:
        con.execute('INSERT INTO sources(id,name,kind,sha256,version,created_at) VALUES(?,?,?,?,1,?)',
                    ('c'*32,'source.md','input',sha,'2026-10-10'))
    bundle=tmp_path/'bundle';backup(source,bundle)
    original=bundle/'files'/sha[:2]/sha
    hidden=tmp_path/'hidden'
    hidden.write_bytes(raw)
    original.unlink()
    try:
        original.symlink_to(hidden)
    except (OSError,NotImplementedError):
        pytest.skip('symlinks not permitted on this platform')
    from scripts.backup import verify_backup
    with pytest.raises(ValueError,match='symbolic link|Invalid backup file type'):
        verify_backup(bundle)
    target=tmp_path/'staged'
    with pytest.raises(ValueError):
        restore_to_staging(bundle,target)
    assert not target.exists()
