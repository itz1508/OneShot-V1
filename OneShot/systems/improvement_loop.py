"""Phase 2-5 — Evidence-linked operator feedback, job-level evaluations, and
improvement proposals. Pure persistence overlay on committed job evidence.

Owns no workflow transitions, no model calls, no Apply authority. Every call
reads committed events / jobs / artifacts and writes to the three new tables
introduced by schema v7 (`job_reviews`, `job_evaluations`,
`improvement_proposals`).

System-ownership rules (directive §4, §14):

- A review NEVER mutates the reviewed job row (`observed_defect` is a label
  on the review, not on the job).
- A review cannot execute Apply or publish a prompt.
- A proposal cannot execute Apply, publish a prompt, or admit a job.
- An evaluation is a structural check, same vocabulary as prompt_evaluations.
"""
from __future__ import annotations
import json
from typing import Any
from fastapi import HTTPException
from systems.store import uid, timestamp, emit
from systems.operations import conv


_DECISIONS = ('observed_defect', 'reviewer_expectation', 'potential_defect',
              'unresolved_decision')
_EVAL_STATUSES = ('proposed', 'approved', 'rejected',
                  'running', 'completed', 'failed')
_PROPOSAL_STATUSES = ('proposed', 'accepted', 'rejected', 'implemented')


def _validate_text(value: Any, field: str, *, max_len: int, allow_empty: bool = True) -> str:
    if value is None:
        if allow_empty:
            return ''
        raise HTTPException(422, f'{field} is required')
    if not isinstance(value, str):
        raise HTTPException(422, f'{field} must be a string')
    if not allow_empty and not value.strip():
        raise HTTPException(422, f'{field} cannot be empty')
    if len(value) > max_len:
        raise HTTPException(422, f'{field} exceeds {max_len}-character limit')
    return value


def _job_exists(con, cid: str, jid: str) -> None:
    row = con.execute(
        'SELECT id FROM jobs WHERE id=? AND conversation_id=?', (jid, cid)).fetchone()
    if row is None:
        raise HTTPException(404, 'Job not found in this conversation')


# ---------------------------------------------------------- Job reviews ----


def upsert_review(store, cid: str, jid: str, body) -> dict:
    """Create or revise one review per job (UNIQUE(job_id))."""
    conv(store, cid)
    decision = getattr(body, 'decision', None)
    if decision not in _DECISIONS:
        raise HTTPException(422, f'decision must be one of {_DECISIONS}')
    required = _validate_text(getattr(body, 'required', ''), 'required', max_len=4000)
    prohibited = _validate_text(getattr(body, 'prohibited', ''), 'prohibited', max_len=4000)
    reason = _validate_text(getattr(body, 'reason', ''), 'reason', max_len=4000)
    limitations = _validate_text(getattr(body, 'limitations', ''), 'limitations', max_len=4000)
    evidence_ids = getattr(body, 'evidence_source_ids', None) or []
    if not isinstance(evidence_ids, list):
        raise HTTPException(422, 'evidence_source_ids must be a list of source ids')
    expected_revision = getattr(body, 'expected_revision', None)
    now = timestamp()
    with store.tx() as con:
        _job_exists(con, cid, jid)
        if evidence_ids:
            scope = {r['id'] for r in con.execute(
                'SELECT id FROM sources s JOIN source_links l ON l.source_id=s.id'
                ' WHERE l.conversation_id=?', (cid,))}
            unknown = [s for s in evidence_ids if s not in scope]
            if unknown:
                raise HTTPException(422,
                    f'Evidence source(s) not in conversation scope: {unknown}')
        existing = con.execute(
            'SELECT * FROM job_reviews WHERE job_id=? AND conversation_id=?',
            (jid, cid)).fetchone()
        if existing is None:
            rid = uid()
            con.execute(
                'INSERT INTO job_reviews(id,conversation_id,job_id,revision,decision,'
                'required,prohibited,reason,limitations,evidence_source_ids,'
                'created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
                (rid, cid, jid, 1, decision, required, prohibited, reason,
                 limitations, json.dumps(evidence_ids), now, now))
            emit(con, cid, 'job_review_recorded', job_id=jid,
                 payload={'review_id': rid, 'decision': decision, 'revision': 1})
            return {'id': rid, 'job_id': jid, 'revision': 1,
                    'decision': decision, 'required': required,
                    'prohibited': prohibited, 'reason': reason,
                    'limitations': limitations,
                    'evidence_source_ids': evidence_ids,
                    'created_at': now, 'updated_at': now}
        current = existing['revision']
        if expected_revision is not None and int(expected_revision) != current:
            raise HTTPException(409,
                f'Review revision conflict (expected {expected_revision}, have {current})')
        new_rev = current + 1
        con.execute(
            'UPDATE job_reviews SET revision=?, decision=?, required=?, prohibited=?,'
            ' reason=?, limitations=?, evidence_source_ids=?, updated_at=?'
            ' WHERE id=?',
            (new_rev, decision, required, prohibited, reason, limitations,
             json.dumps(evidence_ids), now, existing['id']))
        emit(con, cid, 'job_review_revised', job_id=jid,
             payload={'review_id': existing['id'], 'decision': decision,
                      'revision': new_rev})
        return {'id': existing['id'], 'job_id': jid, 'revision': new_rev,
                'decision': decision, 'required': required,
                'prohibited': prohibited, 'reason': reason,
                'limitations': limitations,
                'evidence_source_ids': evidence_ids,
                'created_at': existing['created_at'], 'updated_at': now}


def read_review(store, cid: str, jid: str) -> dict:
    conv(store, cid)
    row = store.one(
        'SELECT * FROM job_reviews WHERE conversation_id=? AND job_id=?', (cid, jid))
    if row is None:
        raise HTTPException(404, 'No review for this job')
    out = dict(row)
    out['evidence_source_ids'] = json.loads(out.pop('evidence_source_ids') or '[]')
    return out


def list_reviews(store, cid: str, *, limit: int = 50, offset: int = 0) -> dict:
    conv(store, cid)
    rows = store.all(
        'SELECT * FROM job_reviews WHERE conversation_id=?'
        ' ORDER BY created_at DESC LIMIT ? OFFSET ?',
        (cid, limit, offset))
    items = []
    for r in rows:
        d = dict(r)
        d['evidence_source_ids'] = json.loads(d.pop('evidence_source_ids') or '[]')
        items.append(d)
    return {'items': items}


# ----------------------------------------------------- Job evaluations ----


def create_evaluation(store, cid: str, jid: str, body) -> dict:
    conv(store, cid)
    criteria = getattr(body, 'criteria', None) or []
    if not isinstance(criteria, list):
        raise HTTPException(422, 'criteria must be a list')
    review_id = getattr(body, 'review_id', None)
    status = (getattr(body, 'status', None) or 'proposed')
    if status not in ('proposed', 'approved'):
        raise HTTPException(422, "status must be 'proposed' or 'approved' on create")
    now = timestamp()
    with store.tx() as con:
        _job_exists(con, cid, jid)
        if review_id is not None:
            rev = con.execute(
                'SELECT id FROM job_reviews WHERE id=? AND conversation_id=? AND job_id=?',
                (review_id, cid, jid)).fetchone()
            if rev is None:
                raise HTTPException(404, 'review_id not found for this job')
        eid = uid()
        con.execute(
            'INSERT INTO job_evaluations(id,conversation_id,job_id,review_id,'
            'status,criteria_json,findings_json,created_at,updated_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?)',
            (eid, cid, jid, review_id, status, json.dumps(criteria), '{}', now, now))
        emit(con, cid, 'job_evaluation_queued', job_id=jid,
             payload={'evaluation_id': eid, 'status': status,
                      'criteria_count': len(criteria),
                      'review_id': review_id})
    return {'id': eid, 'job_id': jid, 'status': status, 'review_id': review_id,
            'criteria': criteria, 'created_at': now}


def approve_evaluation(store, cid: str, eid: str) -> dict:
    conv(store, cid)
    now = timestamp()
    with store.tx() as con:
        row = con.execute(
            'SELECT * FROM job_evaluations WHERE id=? AND conversation_id=?',
            (eid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, 'Evaluation not found')
        if row['status'] != 'proposed':
            raise HTTPException(409, f"Cannot approve: status is {row['status']}")
        con.execute(
            "UPDATE job_evaluations SET status='approved', updated_at=? WHERE id=?",
            (now, eid))
        emit(con, cid, 'job_evaluation_approved', job_id=row['job_id'],
             payload={'evaluation_id': eid})
    return {'id': eid, 'status': 'approved'}


def reject_evaluation(store, cid: str, eid: str) -> dict:
    conv(store, cid)
    now = timestamp()
    with store.tx() as con:
        row = con.execute(
            'SELECT * FROM job_evaluations WHERE id=? AND conversation_id=?',
            (eid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, 'Evaluation not found')
        if row['status'] not in ('proposed', 'approved'):
            raise HTTPException(409, f"Cannot reject: status is {row['status']}")
        con.execute(
            "UPDATE job_evaluations SET status='rejected', updated_at=? WHERE id=?",
            (now, eid))
        emit(con, cid, 'job_evaluation_rejected', job_id=row['job_id'],
             payload={'evaluation_id': eid})
    return {'id': eid, 'status': 'rejected'}


def run_evaluation(store, cid: str, eid: str) -> dict:
    """Execute an approved evaluation against the recorded artifact of the job.

    Each criterion is the same structural shape as prompt_evaluations:

      {'kind':'contains','value':'...'}
      {'kind':'absent','value':'...'}
      {'kind':'contains_ci','value':'...'}
      {'kind':'max_length','value':2000}
      {'kind':'has_source_id','value':'<hex>'}
      {'kind':'quality_outcome','value':'completed'|'blocked'|'failed'}

    Model-based semantic judges are deliberately NOT invoked here (directive
    §9, §16 — semantic verification is a product decision).
    """
    conv(store, cid)
    now = timestamp()
    with store.tx() as con:
        row = con.execute(
            'SELECT e.*, j.status AS job_status, j.artifact_id FROM job_evaluations e'
            ' JOIN jobs j ON j.id=e.job_id AND j.conversation_id=e.conversation_id'
            ' WHERE e.id=? AND e.conversation_id=?', (eid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, 'Evaluation not found')
        if row['status'] != 'approved':
            raise HTTPException(409,
                "Only an 'approved' evaluation can run (directive §8). "
                f"status is {row['status']}")
        criteria = json.loads(row['criteria_json'] or '[]')
        content = ''
        source_ids = []
        if row['artifact_id']:
            art = con.execute(
                'SELECT content, source_ids_json FROM artifacts WHERE id=? AND conversation_id=?',
                (row['artifact_id'], cid)).fetchone()
            if art:
                content = art['content']
                try:
                    source_ids = json.loads(art['source_ids_json'] or '[]')
                except Exception:
                    source_ids = []
        results = []
        for i, c in enumerate(criteria):
            results.append(_run_criterion(i, c, content, source_ids, row['job_status']))
        passed = sum(1 for r in results if r['outcome'] == 'pass')
        failed = sum(1 for r in results if r['outcome'] == 'fail')
        errored = sum(1 for r in results if r['outcome'] == 'error')
        findings = {'passed': passed, 'failed': failed, 'errored': errored,
                    'results': results, 'baseline_job_id': row['job_id']}
        status = 'completed' if errored == 0 else 'failed'
        con.execute(
            'UPDATE job_evaluations SET status=?, findings_json=?, updated_at=?'
            ' WHERE id=?', (status, json.dumps(findings), now, eid))
        emit(con, cid, 'job_evaluation_completed', job_id=row['job_id'],
             payload={'evaluation_id': eid, 'status': status,
                      'passed': passed, 'failed': failed, 'errored': errored})
    return {'id': eid, 'status': status, 'findings': findings, 'updated_at': now}


def _run_criterion(index, c, content, source_ids, job_status):
    if not isinstance(c, dict) or 'kind' not in c:
        return {'index': index, 'criterion': c, 'outcome': 'error',
                'reason': "criterion must be an object with a 'kind' field"}
    kind = c['kind']
    def ok(ok_bool, description):
        return {'index': index, 'criterion': c,
                'outcome': 'pass' if ok_bool else 'fail',
                'description': description}
    if kind == 'contains':
        return ok(c.get('value', '') in content, f'contains {c.get("value")!r}')
    if kind == 'contains_ci':
        return ok(c.get('value', '').lower() in content.lower(),
                  f'contains (ci) {c.get("value")!r}')
    if kind == 'absent':
        return ok(c.get('value', '') not in content, f'absent {c.get("value")!r}')
    if kind == 'max_length':
        return ok(len(content) <= int(c.get('value', 0)),
                  f'len <= {c.get("value")}')
    if kind == 'has_source_id':
        return ok(c.get('value') in source_ids, f'artifact cites {c.get("value")!r}')
    if kind == 'quality_outcome':
        return ok(job_status == c.get('value'), f'job status is {c.get("value")!r}')
    return {'index': index, 'criterion': c, 'outcome': 'error',
            'reason': f'unsupported criterion kind: {kind!r}'}


def read_evaluation(store, cid: str, eid: str) -> dict:
    conv(store, cid)
    row = store.one(
        'SELECT * FROM job_evaluations WHERE id=? AND conversation_id=?', (eid, cid))
    if row is None:
        raise HTTPException(404, 'Evaluation not found')
    out = dict(row)
    out['criteria'] = json.loads(out.pop('criteria_json') or '[]')
    out['findings'] = json.loads(out.pop('findings_json') or '{}')
    return out


def list_evaluations(store, cid: str, *, job_id: str | None = None,
                     limit: int = 50, offset: int = 0) -> dict:
    conv(store, cid)
    if job_id is not None:
        rows = store.all(
            'SELECT * FROM job_evaluations WHERE conversation_id=? AND job_id=?'
            ' ORDER BY created_at DESC LIMIT ? OFFSET ?',
            (cid, job_id, limit, offset))
    else:
        rows = store.all(
            'SELECT * FROM job_evaluations WHERE conversation_id=?'
            ' ORDER BY created_at DESC LIMIT ? OFFSET ?',
            (cid, limit, offset))
    items = []
    for r in rows:
        d = dict(r)
        d['criteria'] = json.loads(d.pop('criteria_json') or '[]')
        d['findings'] = json.loads(d.pop('findings_json') or '{}')
        items.append(d)
    return {'items': items}


# ---------------------------------------------- Improvement proposals ----


def create_proposal(store, cid: str, body) -> dict:
    conv(store, cid)
    issue = _validate_text(getattr(body, 'issue_summary', None), 'issue_summary',
                           max_len=1000, allow_empty=False)
    responsibility = _validate_text(getattr(body, 'affected_responsibility', None),
                                    'affected_responsibility', max_len=160,
                                    allow_empty=False)
    current_b = _validate_text(getattr(body, 'current_behavior', ''), 'current_behavior', max_len=4000)
    required_b = _validate_text(getattr(body, 'required_behavior', ''), 'required_behavior', max_len=4000)
    correction = _validate_text(getattr(body, 'proposed_correction', ''), 'proposed_correction', max_len=4000)
    risks = _validate_text(getattr(body, 'risks', ''), 'risks', max_len=4000)
    evidence = getattr(body, 'evidence', None) or {}
    if not isinstance(evidence, dict):
        raise HTTPException(422, 'evidence must be a JSON object')
    # Scope every referenced job id to this conversation.
    with store.tx() as con:
        job_ids = evidence.get('job_ids') or []
        if not isinstance(job_ids, list):
            raise HTTPException(422, 'evidence.job_ids must be a list')
        for jid in job_ids:
            r = con.execute('SELECT 1 FROM jobs WHERE id=? AND conversation_id=?',
                            (jid, cid)).fetchone()
            if r is None:
                raise HTTPException(422, f'evidence.job_ids[{jid}] not in scope')
        review_ids = evidence.get('review_ids') or []
        for rid in review_ids:
            r = con.execute('SELECT 1 FROM job_reviews WHERE id=? AND conversation_id=?',
                            (rid, cid)).fetchone()
            if r is None:
                raise HTTPException(422, f'evidence.review_ids[{rid}] not in scope')
        pid = uid(); now = timestamp()
        con.execute(
            'INSERT INTO improvement_proposals(id,conversation_id,issue_summary,'
            'affected_responsibility,current_behavior,required_behavior,'
            'proposed_correction,risks,evidence_json,status,created_at,updated_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (pid, cid, issue, responsibility, current_b, required_b,
             correction, risks, json.dumps(evidence), 'proposed', now, now))
        emit(con, cid, 'improvement_proposal_recorded',
             payload={'proposal_id': pid, 'affected_responsibility': responsibility,
                      'evidence_job_count': len(job_ids)})
    return {'id': pid, 'status': 'proposed', 'issue_summary': issue,
            'affected_responsibility': responsibility, 'evidence': evidence,
            'created_at': now}


def _set_proposal_status(store, cid: str, pid: str, new_status: str,
                          allowed_from: tuple) -> dict:
    conv(store, cid)
    now = timestamp()
    with store.tx() as con:
        row = con.execute(
            'SELECT status FROM improvement_proposals WHERE id=? AND conversation_id=?',
            (pid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, 'Proposal not found')
        if row['status'] not in allowed_from:
            raise HTTPException(409,
                f'Cannot transition to {new_status}: current status is {row["status"]}')
        con.execute(
            'UPDATE improvement_proposals SET status=?, updated_at=? WHERE id=?',
            (new_status, now, pid))
        emit(con, cid, 'improvement_proposal_updated',
             payload={'proposal_id': pid, 'status': new_status})
    return {'id': pid, 'status': new_status, 'updated_at': now}


def accept_proposal(store, cid: str, pid: str) -> dict:
    return _set_proposal_status(store, cid, pid, 'accepted', ('proposed',))


def reject_proposal(store, cid: str, pid: str) -> dict:
    return _set_proposal_status(store, cid, pid, 'rejected', ('proposed',))


def mark_proposal_implemented(store, cid: str, pid: str) -> dict:
    return _set_proposal_status(store, cid, pid, 'implemented', ('accepted',))


def list_proposals(store, cid: str, *, limit: int = 50, offset: int = 0) -> dict:
    conv(store, cid)
    rows = store.all(
        'SELECT * FROM improvement_proposals WHERE conversation_id=?'
        ' ORDER BY created_at DESC LIMIT ? OFFSET ?',
        (cid, limit, offset))
    items = []
    for r in rows:
        d = dict(r)
        try:
            d['evidence'] = json.loads(d.pop('evidence_json') or '{}')
        except Exception:
            d['evidence'] = {}
        items.append(d)
    return {'items': items}


def read_proposal(store, cid: str, pid: str) -> dict:
    conv(store, cid)
    row = store.one(
        'SELECT * FROM improvement_proposals WHERE id=? AND conversation_id=?',
        (pid, cid))
    if row is None:
        raise HTTPException(404, 'Proposal not found')
    out = dict(row)
    try:
        out['evidence'] = json.loads(out.pop('evidence_json') or '{}')
    except Exception:
        out['evidence'] = {}
    return out


# --------------------------------------------- Recurring-defect summary --


def recurring_defects(store, cid: str, *, min_count: int = 2) -> dict:
    """Group reviews + background issue codes by shape. Pure DB read."""
    conv(store, cid)
    rows = store.all(
        'SELECT decision, COUNT(*) AS n FROM job_reviews WHERE conversation_id=?'
        ' GROUP BY decision ORDER BY n DESC', (cid,))
    reviews_summary = [dict(r) for r in rows]
    issue_rows = store.all(
        "SELECT result_json FROM background_evaluations"
        " WHERE conversation_id=? AND status='completed'", (cid,))
    counts: dict[str, int] = {}
    for r in issue_rows:
        try:
            payload = json.loads(r['result_json'])
            for code in payload.get('issue_codes', []):
                counts[code] = counts.get(code, 0) + 1
        except Exception:
            continue
    issue_summary = sorted(
        ({'code': code, 'count': n} for code, n in counts.items() if n >= min_count),
        key=lambda x: x['count'], reverse=True)
    return {'reviews': reviews_summary, 'recurring_issue_codes': issue_summary,
            'min_count': min_count}


# ------------------------------------------------- I05 advisory analysis --


def request_advisory_analysis(store, cid: str, jid: str, settings) -> dict:
    """I05 — ask the configured model for *advisory* observations on a committed job.

    The model may suggest potential defects, missing information, contradictions
    or improvement directions. It cannot change the reviewed job, promote any
    suggestion into an observed fact, approve criteria, mark an improvement
    verified, publish a prompt, or execute Apply (directive §9).

    Advisory output is persisted as an `improvement_proposals` row in status
    `proposed` with explicit `evidence_json.model_provenance = {provider, model}`.
    The operator decides whether to accept, reject, or mark it implemented.

    When no non-evidence provider is configured, this call MUST return HTTP 503
    `MODEL_RUNTIME_UNAVAILABLE` so the receiver can see the exact missing
    prerequisite instead of synthetic evidence (directive §15, §17).
    """
    conv(store, cid)
    if settings.provider == 'evidence':
        raise HTTPException(503, {
            'detail': 'MODEL_RUNTIME_UNAVAILABLE',
            'missing_prerequisite': "ONESHOT_PROVIDER != 'evidence' + ONESHOT_MODEL_NAME + credentials",
            'corrective_action': "Configure a non-'evidence' provider (local llama-server or explicitly "
                                 "approved hosted API) and retry; no advisory evidence is written otherwise.",
        })
    with store.tx() as con:
        _job_exists(con, cid, jid)
        row = con.execute(
            'SELECT status, artifact_id FROM jobs WHERE id=? AND conversation_id=?',
            (jid, cid)).fetchone()
    content = ''
    source_ids: list[str] = []
    if row['artifact_id']:
        with store.tx() as con:
            art = con.execute(
                'SELECT content, source_ids_json FROM artifacts'
                ' WHERE id=? AND conversation_id=?',
                (row['artifact_id'], cid)).fetchone()
        if art:
            content = art['content'] or ''
            try: source_ids = json.loads(art['source_ids_json'] or '[]')
            except Exception: source_ids = []
    # Admitted operation: narrow prompt, strict JSON contract, independent validation.
    from systems.model_transport import system_connection, request_text, ModelTransportError
    try:
        connection = system_connection(settings)
    except Exception as exc:
        raise HTTPException(503, {
            'detail': 'MODEL_RUNTIME_UNAVAILABLE',
            'missing_prerequisite': 'valid model connection',
            'corrective_action': f'Fix provider configuration: {exc}',
        }) from exc
    system = (
        'You are an advisory reviewer. Given one job output and its cited source ids, '
        'return a strict JSON object: {"issue_summary": "...", '
        '"affected_responsibility": "...", "current_behavior": "...", '
        '"required_behavior": "...", "proposed_correction": "...", '
        '"risks": "..."} with concise, source-grounded observations. '
        'Do NOT alter the job, approve criteria, publish prompts, or request Apply.'
    )
    user = json.dumps({
        'job_id': jid,
        'job_status': row['status'],
        'output_content': content[:50_000],
        'cited_source_ids': source_ids,
    })
    try:
        answer = request_text(connection, system, user, json_output=True)
    except ModelTransportError as exc:
        raise HTTPException(502, {
            'detail': 'advisory_transport_error',
            'cause': str(exc),
        }) from exc
    try:
        parsed = json.loads(answer)
        issue = str(parsed['issue_summary'])[:1000]
        area = str(parsed['affected_responsibility'])[:160]
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, {
            'detail': 'advisory_malformed_output',
            'cause': str(exc),
        }) from exc
    if not issue.strip() or not area.strip():
        raise HTTPException(502, {
            'detail': 'advisory_missing_required_fields',
        })
    # Persist as an advisory improvement_proposals row with full provenance.
    pid = uid(); now = timestamp()
    evidence = {
        'job_ids': [jid],
        'source_ids': source_ids,
        'model_provenance': {
            'provider': connection.provider,
            'model': connection.name,
            'kind': 'advisory_analysis',
        },
    }
    with store.tx() as con:
        con.execute(
            'INSERT INTO improvement_proposals(id,conversation_id,issue_summary,'
            'affected_responsibility,current_behavior,required_behavior,'
            'proposed_correction,risks,evidence_json,status,created_at,updated_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (pid, cid, issue, area,
             str(parsed.get('current_behavior', ''))[:4000],
             str(parsed.get('required_behavior', ''))[:4000],
             str(parsed.get('proposed_correction', ''))[:4000],
             str(parsed.get('risks', ''))[:4000],
             json.dumps(evidence), 'proposed', now, now))
        emit(con, cid, 'improvement_proposal_created', job_id=jid,
             payload={'proposal_id': pid, 'source': 'advisory_analysis',
                      'model_provider': connection.provider,
                      'model_name': connection.name})
    return {
        'id': pid,
        'status': 'proposed',
        'issue_summary': issue,
        'affected_responsibility': area,
        'evidence': evidence,
        'created_at': now,
    }
