import sqlite3,pytest
from systems.store import Store
from systems.file_store import FileStore
from capabilities.researcher import validate_url,extract_page
from capabilities.scanner import inspect

def test_file_integrity(tmp_path):
    store=FileStore(tmp_path)
    hash=store.put(b'hello');assert store.put(b'hello')==hash
    assert store.read(hash)==b'hello'
    path=tmp_path/hash[:2]/hash;path.write_bytes(b'HELLO')
    with pytest.raises(ValueError):store.read(hash)
    with pytest.raises(ValueError):store.read('../escape')

def test_transaction_rollback_and_fk(tmp_path):
    db=Store(tmp_path)
    with pytest.raises(RuntimeError):
        with db.tx() as con:
            con.execute('INSERT INTO conversations VALUES(?,?,?)',('one','title',0))
            raise RuntimeError('rollback')
    assert db.one('SELECT * FROM conversations WHERE id=?',('one',)) is None
    with pytest.raises(sqlite3.IntegrityError):
        with db.tx() as con:
            con.execute('INSERT INTO source_links VALUES(?,?)',('unknown','unknown'))

def test_scanner_fails_closed_on_unsupported(tmp_path):
    assert inspect('code.py',b'print(1)').coverage=='complete'
    assert inspect('code.pdf',b'not a pdf').coverage=='blocked'
    assert inspect('image.png',b'pixels').limitation.startswith('vision_unreadable:')
    import struct, zlib
    def _tiny_png() -> bytes:
        sig=b'\x89PNG\r\n\x1a\n'
        ihdr_data=struct.pack('>II',1,1)+b'\x08\x02\x00\x00\x00'
        ihdr=b'IHDR'+ihdr_data; ihdr_chunk=struct.pack('>I',len(ihdr_data))+ihdr+struct.pack('>I',zlib.crc32(ihdr))
        idat_data=zlib.compress(b'\x00\xff\x00\x00')
        idat=b'IDAT'+idat_data; idat_chunk=struct.pack('>I',len(idat_data))+idat+struct.pack('>I',zlib.crc32(idat))
        iend_chunk=struct.pack('>I',0)+b'IEND'+struct.pack('>I',zlib.crc32(b'IEND'))
        return sig+ihdr_chunk+idat_chunk+iend_chunk
    unconfigured=inspect('image.png',_tiny_png())
    assert unconfigured.limitation.startswith('vision_not_configured:'), unconfigured
    assert inspect('bad.md',b'\xff').coverage=='blocked'

def test_browser_validation_and_extract():
    assert validate_url('https://docs.python.org/3/')
    for url in ('http://example.org','https://localhost/a','https://127.0.0.1','https://internal.test'):
        with pytest.raises(ValueError):validate_url(url)
    assert extract_page('<p>A</p><script>bad()</script><p>B</p>')=='A\nB'

def test_one_store_two_connections_wal_read_write(tmp_path):
    db=Store(tmp_path)
    with db.connection() as reader:
        reader.execute('BEGIN')
        assert reader.execute('SELECT COUNT(*) FROM conversations').fetchone()[0]==0
        with db.tx() as writer:
            writer.execute("INSERT INTO conversations VALUES('c','hello',0)")
        assert reader.execute('SELECT COUNT(*) FROM conversations').fetchone()[0]==0
        reader.rollback()
    assert db.one('SELECT title FROM conversations WHERE id=?',('c',))['title']=='hello'

def test_backup_fresh_restorable_and_tamper_check(tmp_path):
    from scripts.backup import backup,verify_backup
    source=tmp_path/'source';db=Store(source)
    digest=db.files.put(b'original truth')
    with db.tx() as con:con.execute("INSERT INTO conversations VALUES('a','saved',0)")
    path=tmp_path/'backup'
    result=backup(source,path)
    assert result['copied_files']==1
    assert verify_backup(path)==result
    restored=Store(path)
    assert restored.one('SELECT title FROM conversations WHERE id=?',('a',))['title']=='saved'
    assert restored.files.read(digest)==b'original truth'
    with pytest.raises(FileExistsError):backup(source,path)
    (path/'files'/digest[:2]/digest).write_bytes(b'tamper')
    with pytest.raises(ValueError):verify_backup(path)


def test_backup_rejects_named_source_with_missing_original_bytes(tmp_path):
    from scripts.backup import backup,verify_backup
    source=tmp_path/'source';db=Store(source)
    source_name='config/security_options.py'
    raw=b'session_token = "keep-original"\n'
    digest=db.files.put(raw)
    source_id='b'*32
    with db.tx() as con:
        con.execute('INSERT INTO sources(id,name,kind,sha256,version,created_at) VALUES(?,?,?,?,1,?)',
                    (source_id,source_name,'import',digest,'2026-10-09'))
    source_row=db.one('SELECT name,sha256 FROM sources WHERE id=?',(source_id,))
    assert source_row=={'name':source_name,'sha256':digest}
    # A missing source cannot be disguised by a structurally valid SQLite backup.
    destination=tmp_path/'backup'
    result=backup(source,destination)
    assert verify_backup(destination)==result
    original=source/'files'/digest[:2]/digest
    original.unlink()
    with pytest.raises(ValueError,match='Missing original source bytes'):
        backup(source,tmp_path/'bad-backup')
    assert not (tmp_path/'bad-backup').exists()
    copied=destination/'files'/digest[:2]/digest
    copied.unlink()
    with pytest.raises(ValueError,match='File count differs|Missing original source bytes'):
        verify_backup(destination)
