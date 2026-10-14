"""OneShot System Background: durable, advisory, read-only evidence evaluation.

No Agent, model, provider, user-source mutation or foreground Worker dependence.
The only writes are versioned evaluation records and observed activity events.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import logging
import time
from typing import Any

from systems.store import Store, emit, timestamp, uid

EVALUATOR_VERSION = 'event-integrity-v1'
TERMINAL = ('completed', 'blocked', 'failed')
MAX_ATTEMPTS = 3
MAX_EVENTS = 10_000
MAX_SCOPE = 50

# Codes are intentionally fixed and contain no source content or provider output.
PROPOSALS = {
    'missing_terminal_event': 'Investigate incomplete terminal event recording and restart recovery.',
    'unfinished_trace_node': 'Inspect real node start/failure/completion transitions for missing closures.',
    'run_status_mismatch': 'Inspect foreground run/job status transitions and their commit boundary.',
    'artifact_scope_mismatch': 'Verify generated artifact provenance against immutable admission scope.',
    'source_integrity_failed': 'Investigate source hash verification; preserve the original source evidence.',
    'missing_artifact': 'Check completed-job artifact storage and admission invariants.',
    'unexpected_artifact': 'Inspect blocked/failed job artifact authorization.',
    'excessive_trace': 'Inspect event volume and establish a bounded trace verification method.',
    'job_failed': 'Group verified failure reasons separately; do not infer semantic correctness.',
    'job_blocked': 'Review recorded unsupported or insufficient evidence, without auto-generating output.',
}


def _stable_id(job_id: str) -> str:
    return sha256(f'{EVALUATOR_VERSION}:{job_id}'.encode('ascii')).hexdigest()[:32]


def _json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(',', ':'))


def admit_terminal(store: Store, limit: int = 32) -> int:
    """Backfill committed terminal jobs with an idempotent versioned identity.

    Runs in background only. Does not become part of foreground transaction or API.
    """
    if not 1 <= limit <= 100:
        raise ValueError('Invalid admission batch limit')
    with store.tx() as con:
        candidates = con.execute('''SELECT id,conversation_id FROM jobs AS j
            WHERE status IN ('completed','blocked','failed') AND NOT EXISTS (
              SELECT 1 FROM background_evaluations AS b
              WHERE b.job_id=j.id AND b.evaluator_version=?)
            ORDER BY created_at,id LIMIT ?''', (EVALUATOR_VERSION,limit)).fetchall()
        for row in candidates:
            con.execute('''INSERT OR IGNORE INTO background_evaluations
                (id,conversation_id,job_id,evaluator_version,status,created_at,updated_at)
                VALUES(?,?,?,?,'queued',?,?)''',
                (_stable_id(row['id']),row['conversation_id'],row['id'],EVALUATOR_VERSION,timestamp(),timestamp()))
            emit(con,row['conversation_id'],'background_queued',job_id=row['id'],
                 payload={'evaluation_id':_stable_id(row['id'])})
    return len(candidates)


def recover_background(store: Store) -> int:
    """Requeue interrupted work at startup in the supported single-server deployment.

    Tokens fence stale workers: a previous claimant cannot commit after recovery.
    """
    with store.tx() as con:
        rows=con.execute("SELECT id,attempt FROM background_evaluations WHERE status='running'").fetchall()
        for row in rows:
            if row['attempt'] >= MAX_ATTEMPTS:
                con.execute('''UPDATE background_evaluations SET status='failed',error_code='retry_exhausted',
                    lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?''',(timestamp(),row['id']))
            else:
                con.execute('''UPDATE background_evaluations SET status='queued',error_code='interrupted',
                    lease_token=NULL,lease_until=NULL,updated_at=? WHERE id=?''',(timestamp(),row['id']))
    return len(rows)


def _claim(store: Store) -> dict | None:
    token=uid()
    with store.tx() as con:
        row=con.execute('''SELECT * FROM background_evaluations
            WHERE status='queued' ORDER BY created_at,id LIMIT 1''').fetchone()
        if not row:return None
        now=time.time()
        changed=con.execute('''UPDATE background_evaluations SET status='running',
            attempt=attempt+1,lease_token=?,lease_until=?,error_code=NULL,updated_at=?
            WHERE id=? AND status='queued' ''',(token,now+60,timestamp(),row['id'])).rowcount
        if changed!=1:return None
        emit(con,row['conversation_id'],'background_started',job_id=row['job_id'],
             payload={'evaluation_id':row['id'],'attempt':row['attempt']+1})
        return {**dict(row),'lease_token':token,'attempt':row['attempt']+1}


def _evaluate(store: Store, row: dict) -> tuple[str, dict]:
    """Deterministic invariant checks, not semantic correctness or training labels."""
    job=store.one('SELECT * FROM jobs WHERE id=? AND conversation_id=?',
                  (row['job_id'],row['conversation_id']))
    if not job or job['status'] not in TERMINAL:
        return 'skipped',{'reason':'evidence_not_terminal','semantic_quality':'not_evaluated'}
    try:
        scope=json.loads(job['scope_json'])
    except (ValueError,TypeError):
        return 'completed',{'outcome':'inconsistent','checks':{'scope_parseable':False},
                            'issue_codes':['invalid_scope'],'semantic_quality':'not_evaluated'}
    if not isinstance(scope,list) or len(scope)>MAX_SCOPE or not all(isinstance(s,dict) for s in scope):
        return 'completed',{'outcome':'inconsistent','checks':{'scope_bounded':False},
                            'issue_codes':['invalid_scope'],'semantic_quality':'not_evaluated'}
    # Tombstoned original sources must not become new learning examples.
    if any('id' not in item or 'version' not in item or 'sha256' not in item for item in scope):
        return 'completed',{'outcome':'inconsistent','checks':{'scope_fields_present':False},
                            'issue_codes':['invalid_scope'],'semantic_quality':'not_evaluated'}
    source_rows=[]
    for item in scope:
        src=store.one('SELECT id,version,sha256,deleted FROM sources WHERE id=?',(item.get('id'),))
        if not src or src['deleted']:
            return 'skipped',{'reason':'source_unavailable_or_deleted','semantic_quality':'not_evaluated'}
        source_rows.append((item,src))

    runs=store.all('SELECT status,attempt FROM runs WHERE job_id=? ORDER BY attempt',(job['id'],))
    event_count=store.one('SELECT COUNT(*) AS n FROM events WHERE job_id=? AND conversation_id=?',
                          (job['id'],job['conversation_id']))['n']
    issues=[]
    if event_count>MAX_EVENTS:
        issues.append('excessive_trace')
        # No unbounded event loading, and no claim that event consistency passed.
        event_kinds=[]
    else:
        event_kinds=[x['kind'] for x in store.all('''SELECT kind FROM events
            WHERE job_id=? AND conversation_id=? ORDER BY seq''',(job['id'],job['conversation_id']))]
    terminal_kind='job_'+job['status']
    # Foreground crash recovery records job_interrupted rather than job_failed.
    terminal_kinds={terminal_kind}
    if job['status']=='failed':terminal_kinds.add('job_interrupted')
    checks={
        'terminal_event':any(kind in event_kinds for kind in terminal_kinds),
        'run_status':bool(runs) and runs[-1]['status']==job['status'],
        'bounded_event_history':event_count<=MAX_EVENTS,
        'scope_source_integrity':True,
        'artifact_provenance':True,
    }
    if not checks['terminal_event'] and event_count<=MAX_EVENTS:issues.append('missing_terminal_event')
    # Node starts must not remain shown as running after a terminal result.
    opened=set()
    if event_count<=MAX_EVENTS:
        node_events=store.all('''SELECT node_id,kind FROM events
            WHERE job_id=? AND conversation_id=? AND node_id IS NOT NULL ORDER BY seq''',
            (job['id'],job['conversation_id']))
        for event in node_events:
            if event['kind']=='node_started':opened.add(event['node_id'])
            elif event['kind'] in ('node_completed','node_failed','node_skipped'):
                opened.discard(event['node_id'])
    checks['no_unfinished_nodes']=not opened and event_count<=MAX_EVENTS
    if not checks['no_unfinished_nodes'] and event_count<=MAX_EVENTS:
        issues.append('unfinished_trace_node')
    if not checks['run_status']:issues.append('run_status_mismatch')
    for snapshot,src in source_rows:
        if (snapshot.get('version')!=src['version'] or snapshot.get('sha256')!=src['sha256']
            or not src['sha256']):
            checks['scope_source_integrity']=False
        else:
            try:store.files.read(src['sha256'])
            except (OSError,ValueError):checks['scope_source_integrity']=False
    if not checks['scope_source_integrity']:issues.append('source_integrity_failed')

    artifact=store.one('SELECT id,source_ids_json FROM artifacts WHERE id=? AND job_id=? AND conversation_id=?',
                       (job['artifact_id'],job['id'],job['conversation_id'])) if job['artifact_id'] else None
    if job['status']=='completed':
        if not artifact:
            checks['artifact_provenance']=False;issues.append('missing_artifact')
        else:
            try:
                ids=json.loads(artifact['source_ids_json'])
                checks['artifact_provenance']=(ids==[x['id'] for x in scope])
            except (ValueError,KeyError,TypeError):checks['artifact_provenance']=False
            if not checks['artifact_provenance']:issues.append('artifact_scope_mismatch')
    elif job['artifact_id'] is not None:
        checks['artifact_provenance']=False;issues.append('unexpected_artifact')

    if job['status']=='failed':issues.append('job_failed')
    if job['status']=='blocked':issues.append('job_blocked')
    failed_integrity=not all(checks.values())
    # A failed/blocked job may be internally consistent; not a successful semantic result.
    outcome='inconsistent' if failed_integrity else 'recorded_consistently'
    fingerprint=sha256(_json({'job':job['id'],'status':job['status'],
                              'scope':scope,'terminal_event':terminal_kind,
                              'event_count':event_count,'artifact_id':job['artifact_id']}).encode()).hexdigest()
    return 'completed',{
        'outcome':outcome,'observed_job_status':job['status'],
        'checks':checks,'issue_codes':sorted(set(issues)),
        'semantic_quality':'not_evaluated',
        'learning_label':'none_verified',
        'evidence_fingerprint':fingerprint,'event_count':event_count,
        'evaluator_version':EVALUATOR_VERSION,
    }


class BackgroundWorker:
    """One evaluation per tick, bounded work; called in its own executor."""
    def __init__(self,store:Store):self.store=store

    def step(self) -> str | None:
        # Priority boundary: never begin optional scans/evaluations while a
        # foreground job is queued or running. This prevents deliberate
        # background contention; in-flight races are measured, not denied.
        foreground_active=self.store.one(
            "SELECT 1 AS active FROM jobs WHERE status IN ('queued','running') LIMIT 1")
        if foreground_active:return None
        admit_terminal(self.store)
        row=_claim(self.store)
        if row is None:return None
        try:
            result_status,result=_evaluate(self.store,row)
            with self.store.tx() as con:
                changed=con.execute('''UPDATE background_evaluations SET status=?,outcome=?,
                    evidence_hash=?,result_json=?,lease_token=NULL,lease_until=NULL,updated_at=?
                    WHERE id=? AND status='running' AND lease_token=?''',
                    (result_status,result.get('outcome'),result.get('evidence_fingerprint'),
                     _json(result),timestamp(),row['id'],row['lease_token'])).rowcount
                if changed==1:
                    emit(con,row['conversation_id'],'background_'+result_status,job_id=row['job_id'],
                         payload={'evaluation_id':row['id'],'outcome':result.get('outcome'),
                                  'reason':result.get('reason'),'issue_codes':result.get('issue_codes',[])})
        except Exception:
            logging.getLogger('oneshot.background').error('Background evaluator failed; see sanitized evaluation status')
            with self.store.tx() as con:
                status='failed' if row['attempt']>=MAX_ATTEMPTS else 'queued'
                changed=con.execute('''UPDATE background_evaluations SET status=?,error_code='evaluation_error',
                    lease_token=NULL,lease_until=NULL,updated_at=?
                    WHERE id=? AND status='running' AND lease_token=?''',
                    (status,timestamp(),row['id'],row['lease_token'])).rowcount
                if changed:
                    emit(con,row['conversation_id'],'background_'+status,job_id=row['job_id'],
                         payload={'evaluation_id':row['id'],'reason':'evaluation_error'})
        return row['id']


def report(store: Store, conversation_id: str, limit: int=30) -> dict:
    """No raw prompts, source text, secrets, provider outputs or model-generated labels."""
    if not 1<=limit<=100:raise ValueError('Invalid report page size')
    rows=store.all('''SELECT id,job_id,evaluator_version,status,attempt,outcome,error_code,
        result_json,created_at,updated_at FROM background_evaluations
        WHERE conversation_id=? ORDER BY created_at DESC,id DESC LIMIT ?''',(conversation_id,limit))
    evaluations=[];counts=Counter();patterns=Counter()
    # Aggregate exact counts in SQL, while bounding the pattern-recognition history.
    grouped=store.all('''SELECT status,COUNT(*) AS n FROM background_evaluations
        WHERE conversation_id=? AND evaluator_version=? GROUP BY status''',
        (conversation_id,EVALUATOR_VERSION))
    for item in grouped:counts[item['status']]=item['n']
    window=store.all('''SELECT result_json FROM background_evaluations
        WHERE conversation_id=? AND evaluator_version=? AND status='completed'
        ORDER BY updated_at DESC,id DESC LIMIT 500''',(conversation_id,EVALUATOR_VERSION))
    for item in window:
        for code in json.loads(item['result_json']).get('issue_codes',[]):
            if code in PROPOSALS:patterns[code]+=1
    for item in rows:
        payload=json.loads(item.pop('result_json'))
        evaluations.append({**item,'result':payload})
    return {'evaluator_version':EVALUATOR_VERSION,
        'summary':{'total':sum(counts.values()),'states':dict(counts),
                   'verified_semantic_labels':0,'production_promotions':0},
        'evaluations':evaluations,
        'pattern_window':{'maximum':500,'evaluated':len(window)},
        'patterns':[{'code':code,'count':count,'suggestion':PROPOSALS[code],
                     'status':'proposal_only'} for code,count in sorted(patterns.items()) if count>=2],
        'learning':{'mode':'deterministic_observation','training':'skipped_no_independent_labels',
                    'model_promoted':False}}
