"""Consistent SQLite backup + original source file integrity verification.

No restore overwrite in-place: verify against a fresh destination before any promotion.
"""
from pathlib import Path
import sqlite3,shutil,json,hashlib,argparse,re
from systems.store import Store

def _verify_referenced_sources(source_root:Path)->None:
    """Verify every named source row resolves to its immutable content-addressed bytes.

    Physical FileStore filenames are hashes; user-visible names live in SQLite.
    References with no retrieved content do not have a file to check.
    """
    with sqlite3.connect(source_root/'oneshot.sqlite3') as con:
        rows=con.execute('SELECT id,name,sha256 FROM sources WHERE sha256 IS NOT NULL').fetchall()
    for source_id, source_name, digest in rows:
        if not source_name or not re.fullmatch(r'[0-9a-f]{64}',digest):
            raise ValueError(f'Invalid stored source identity: {source_id}')
        original=source_root/'files'/digest[:2]/digest
        if original.is_symlink():
            raise ValueError('Backup source path must not be a symbolic link')
        try:
            raw=original.read_bytes()
        except FileNotFoundError as exc:
            raise ValueError(f'Missing original source bytes for {source_name!r} ({source_id})') from exc
        if hashlib.sha256(raw).hexdigest()!=digest:
            raise ValueError(f'Original source content mismatch for {source_name!r} ({source_id})')

def backup(source:Path,target:Path)->dict:
    if target.exists():raise FileExistsError('Backup destination must be new')
    src=Store(source)
    _verify_referenced_sources(source)
    target.mkdir(parents=True)
    copied=0
    try:
        with src.connection() as original:
            with sqlite3.connect(target/'oneshot.sqlite3') as dest:original.backup(dest)
        file_source=source/'files'
        if file_source.exists():
            for f in file_source.glob('*/*'):
                if f.is_symlink():raise ValueError('Source file must not be a symbolic link')
                if not f.is_file():continue
                payload=f.read_bytes()
                if hashlib.sha256(payload).hexdigest()!=f.name:raise ValueError('Source integrity error before backup')
                relative=f.relative_to(file_source)
                dest=target/'files'/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload)
                if hashlib.sha256(dest.read_bytes()).hexdigest()!=f.name:raise ValueError('Backup readback error')
                copied+=1
        with sqlite3.connect(target/'oneshot.sqlite3') as con:
            if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database backup failed integrity check')
        _verify_referenced_sources(target)
        # Also back up applied/: Apply writes mutate real target files that must survive a
        # restore under the same documented procedure (directive v6.0 §7).
        applied_source=source/'applied'
        applied_entries=[]
        if applied_source.exists():
            for f in applied_source.rglob('*'):
                if f.is_symlink():raise ValueError('applied/ file must not be a symbolic link')
                if not f.is_file():continue
                payload=f.read_bytes()
                rel=f.relative_to(applied_source)
                dest=target/'applied'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload)
                sha=hashlib.sha256(payload).hexdigest()
                if hashlib.sha256(dest.read_bytes()).hexdigest()!=sha:raise ValueError('applied/ readback error')
                applied_entries.append({'path':str(rel),'sha256':sha,'bytes':len(payload)})
        manifest={'copied_files':copied,
                  'sqlite_sha256':hashlib.sha256((target/'oneshot.sqlite3').read_bytes()).hexdigest(),
                  'applied':applied_entries}
        (target/'MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
        return manifest
    except BaseException:
        shutil.rmtree(target,ignore_errors=True);raise

def verify_backup(path:Path)->dict:
    manifest=json.loads((path/'MANIFEST.json').read_text())
    if hashlib.sha256((path/'oneshot.sqlite3').read_bytes()).hexdigest()!=manifest['sqlite_sha256']:
        raise ValueError('Database content does not match manifest')
    with sqlite3.connect(path/'oneshot.sqlite3') as con:
        if con.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Database corrupt')
    n=0
    for f in (path/'files').glob('*/*') if (path/'files').exists() else []:
        if f.is_symlink() or not f.is_file():raise ValueError('Invalid backup file type')
        if hashlib.sha256(f.read_bytes()).hexdigest()!=f.name:raise ValueError('Backup original altered')
        n+=1
    if n!=manifest['copied_files']:raise ValueError('File count differs')
    applied_entries=manifest.get('applied',[])
    applied_dir=path/'applied'
    if applied_entries and not applied_dir.exists():raise ValueError('applied/ missing from backup')
    # Defence: refuse manifest entries that try to escape applied/ (directive v6.0.7 §5).
    base=applied_dir.resolve() if applied_dir.exists() else None
    seen=set()
    for e in applied_entries:
        rel_name=e['path']
        if not rel_name or rel_name.startswith('/') or '\\' in rel_name:
            raise ValueError(f"Unsafe applied/ path: {rel_name!r}")
        rel_parts=rel_name.split('/')
        if any(part in ('.','..') for part in rel_parts):
            raise ValueError(f"Unsafe applied/ path (traversal): {rel_name!r}")
        f=applied_dir/rel_name
        if base is not None:
            try:
                resolved=f.resolve()
            except Exception as exc:
                raise ValueError(f"applied/ path unresolvable: {rel_name!r}") from exc
            if not resolved.is_relative_to(base):
                raise ValueError(f"applied/ path escapes backup root: {rel_name!r}")
        if f.is_symlink() or not f.is_file():raise ValueError(f"Invalid applied/ file: {e['path']}")
        if hashlib.sha256(f.read_bytes()).hexdigest()!=e['sha256']:raise ValueError(f"applied/ altered: {e['path']}")
        seen.add(e['path'])
    if applied_dir.exists():
        for f in applied_dir.rglob('*'):
            if f.is_symlink():raise ValueError(f"Unexpected applied/ symlink: {f.relative_to(applied_dir)}")
            if not f.is_file():continue
            rel=str(f.relative_to(applied_dir))
            if rel not in seen:raise ValueError(f"Unexpected applied/ file in backup: {rel}")
    _verify_referenced_sources(path)
    return manifest

def restore_to_staging(backup_dir: Path, destination: Path) -> dict:
    """Verify and restore to a NEW directory; never replace active installation.

    Promotion requires a separate explicit authorization and stopped service.
    """
    if destination.exists():
        raise FileExistsError('Restore destination must be new; active data is never overwritten')
    expected = verify_backup(backup_dir)
    destination.mkdir(parents=True)
    try:
        shutil.copy2(backup_dir / 'oneshot.sqlite3', destination / 'oneshot.sqlite3')
        for source in (backup_dir / 'files').glob('*/*') if (backup_dir / 'files').exists() else []:
            if not source.is_file():
                continue
            relative = source.relative_to(backup_dir)
            copied = destination / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, copied)
        applied_src = backup_dir / 'applied'
        if applied_src.exists():
            for source in applied_src.rglob('*'):
                if not source.is_file():
                    continue
                relative = source.relative_to(backup_dir)
                copied = destination / relative
                copied.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, copied)
        (destination / 'MANIFEST.json').write_bytes((backup_dir / 'MANIFEST.json').read_bytes())
        if verify_backup(destination) != expected:
            raise ValueError('Staged restore verification mismatch')
        # A staged copy must remain byte-identical to its hash manifest.
        # The manifest is not signed and does not authenticate its creator.
        # Do not open through Store here: that could upgrade an older schema
        # and invalidate the checkpoint before promotion is authorized.
        staged_database = (destination / 'oneshot.sqlite3').resolve()
        with sqlite3.connect(staged_database.as_uri() + '?mode=ro', uri=True) as con:
            version = con.execute('PRAGMA user_version').fetchone()[0]
            if version > 7 or version < 1:
                raise ValueError(f'Unsupported staged database version {version}')
        if verify_backup(destination) != expected:
            raise ValueError('Staged restore verification mismatch')
        return expected
    except BaseException:
        shutil.rmtree(destination, ignore_errors=True)
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('action_or_source', help='backup | restore | legacy source directory')
    p.add_argument('source_or_destination')
    p.add_argument('destination', nargs='?')
    args=p.parse_args()
    if args.action_or_source == 'restore':
        if not args.destination:p.error('restore requires backup and new destination')
        print(restore_to_staging(Path(args.source_or_destination), Path(args.destination)))
    elif args.action_or_source == 'backup':
        if not args.destination:p.error('backup requires source and new destination')
        print(backup(Path(args.source_or_destination), Path(args.destination)))
    else:
        if args.destination:p.error('legacy backup accepts source and destination only')
        print(backup(Path(args.action_or_source), Path(args.source_or_destination)))
