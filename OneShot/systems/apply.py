"""Apply is the only disk mutation boundary beyond managed System storage.

Two-step confirmation, optimistic target hash, atomic replace, readback, durable
final-applied-diff. Crashed applying intents are flagged needs_review.
"""
from pathlib import Path
import hashlib,os,difflib,time
from fastapi import HTTPException
from systems.store import uid,timestamp,emit

def digest(raw:bytes)->str:return hashlib.sha256(raw).hexdigest()

def destination(root:Path,name:str)->Path:
    # Single relative file name or directory path. Prevent traversal and symlinks.
    raw=Path(name)
    if raw.is_absolute() or '\\' in name or any(x in ('.','..') for x in raw.parts):raise HTTPException(422,'Invalid destination')
    base=(root/'applied').resolve()
    target=(base/raw).resolve()
    if not target.is_relative_to(base) or target==base:raise HTTPException(422,'Outside allowed output directory')
    return target

def prepare(store,cid,body):
    art=store.one('SELECT * FROM artifacts WHERE id=? AND conversation_id=?',(body.artifact_id,cid))
    if art is None:raise HTTPException(404,'Artifact not found')
    path=destination(store.root,body.destination)
    existing=digest(path.read_bytes()) if path.exists() else None
    if existing!=body.expected_target_sha256:raise HTTPException(409,'Destination baseline hash mismatch')
    if len(art['content'].encode('utf-8'))>500_000:raise HTTPException(413,'Artifact is too large')
    token=uid();expires=time.time()+180
    with store.tx() as con:
        con.execute('INSERT INTO apply_intents VALUES(?,?,?,?,?,?,?)',(token,cid,body.artifact_id,body.destination,existing,expires,'prepared'))
        emit(con,cid,'apply_prepared',payload={'artifact_id':body.artifact_id,'destination':body.destination})
    return {'confirmation_token':token,'expires_in_seconds':180,'destination':body.destination,
            'baseline_sha256':existing,'artifact_id':body.artifact_id}

def confirm(store,cid,body):
    record=store.one('SELECT * FROM apply_intents WHERE id=? AND conversation_id=?',(body.confirmation_token,cid))
    if record is None or record['state']!='prepared' or record['expires_at']<time.time():
        raise HTTPException(403,'Apply confirmation invalid, expired or already used')
    art=store.one('SELECT * FROM artifacts WHERE id=? AND conversation_id=?',(record['artifact_id'],cid))
    if art is None:raise HTTPException(404,'Artifact missing')
    path=destination(store.root,record['destination']);path.parent.mkdir(parents=True,exist_ok=True)
    before=path.read_bytes() if path.exists() else b''
    actual=digest(before) if path.exists() else None
    if actual!=record['expected_hash']:raise HTTPException(409,'Target changed after Apply preparation')
    next_bytes=art['content'].encode('utf-8');expected=digest(next_bytes)
    tmp=path.with_name(path.name+'.'+uid()+'.tmp')
    # Intent state is written before filesystem side effect; restart never assumes completion.
    with store.tx() as con:
        updated=con.execute("UPDATE apply_intents SET state='applying' WHERE id=? AND state='prepared'",(body.confirmation_token,)).rowcount
        if updated!=1:raise HTTPException(409,'Apply already started')
    try:
        with tmp.open('xb') as f:
            f.write(next_bytes);f.flush();os.fsync(f.fileno())
        os.replace(tmp,path)
        readback=path.read_bytes()
        if digest(readback)!=expected:raise RuntimeError('Applied target verification failed')
        diff=''.join(difflib.unified_diff(before.decode('utf-8',errors='replace').splitlines(keepends=True),
                  readback.decode('utf-8',errors='replace').splitlines(keepends=True),fromfile='baseline',tofile='applied'))
        apply_id=uid()
        with store.tx() as con:
            con.execute('INSERT INTO applied VALUES(?,?,?,?,?,?,?,?)',(apply_id,cid,art['id'],record['destination'],actual,expected,diff,timestamp()))
            con.execute("UPDATE apply_intents SET state='verified' WHERE id=?",(body.confirmation_token,))
            emit(con,cid,'apply_verified',payload={'apply_id':apply_id,'result_sha256':expected})
        return {'id':apply_id,'verified':True,'result_sha256':expected,'final_applied_diff':diff}
    except BaseException:
        with store.tx() as con:
            con.execute("UPDATE apply_intents SET state='needs_review' WHERE id=?",(body.confirmation_token,))
        raise
    finally:tmp.unlink(missing_ok=True)


def target_state(store, name: str) -> dict:
    """Read-only target baseline for a user review; no source or output mutation."""
    path = destination(store.root, name)
    if not path.exists():
        return {'destination': name, 'exists': False, 'sha256': None}
    if not path.is_file():
        raise HTTPException(422, 'Apply destination is not a regular file')
    raw = path.read_bytes()
    return {'destination': name, 'exists': True, 'sha256': digest(raw)}


def applied_readback(store, cid: str, apply_id: str) -> dict:
    record = store.one('SELECT * FROM applied WHERE id=? AND conversation_id=?', (apply_id, cid))
    if record is None:
        raise HTTPException(404, 'Applied result not found')
    target = target_state(store, record['destination'])
    if not target['exists'] or target['sha256'] != record['result_hash']:
        raise HTTPException(409, 'Applied destination no longer matches recorded result')
    return {'id': record['id'], 'destination': record['destination'],
            'verified': True, 'result_sha256': target['sha256'],
            'final_applied_diff': record['diff']}
