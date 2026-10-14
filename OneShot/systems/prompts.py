"""Prompt lifecycle operations.

A prompt asset lives inside a conversation. Each publication creates an
immutable PromptVersion. The System freezes a resolved version onto a Job
at admission time, so later publications never affect existing jobs.
"""
from __future__ import annotations
import hashlib
import json
from typing import Any

from fastapi import HTTPException
from systems.store import uid, timestamp, emit
from systems.operations import conv
from systems.prompt_variables import (
    VariableResolutionError, load_definitions, find_references, resolve,
)


_NAME_MIN = 1
_NAME_MAX = 120


def _validate_name(name: str) -> str:
    if not isinstance(name, str) or len(name) < _NAME_MIN or len(name) > _NAME_MAX:
        raise HTTPException(422, f'Prompt name must be {_NAME_MIN}..{_NAME_MAX} characters')
    return name


def _validate_variables_json(variables: Any) -> list:
    if variables is None:
        variables = []
    if not isinstance(variables, list):
        raise HTTPException(422, 'variables must be a JSON array of definitions')
    normalized = []
    for item in variables:
        if hasattr(item, 'model_dump'):
            normalized.append(item.model_dump())
        elif isinstance(item, dict):
            normalized.append(item)
        else:
            raise HTTPException(422, f'variable entry must be an object, got {type(item).__name__}')
    try:
        defs = load_definitions(normalized)
    except VariableResolutionError as exc:
        raise HTTPException(422, str(exc)) from exc
    return [
        {'name': d.name, 'required': d.required,
         'description': d.description, 'max_length': d.max_length}
        for d in defs
    ]


def _validate_content(content: Any) -> str:
    if not isinstance(content, str):
        raise HTTPException(422, 'content must be a string')
    if not content.strip():
        raise HTTPException(422, 'content cannot be empty or whitespace-only')
    if len(content) > 200_000:
        raise HTTPException(422, 'content exceeds 200000-character limit')
    return content


def _check_template(content: str, variables: list) -> None:
    try:
        defs = load_definitions(variables)
    except VariableResolutionError as exc:
        raise HTTPException(422, str(exc)) from exc
    defined_names = {d.name for d in defs}
    referenced = find_references(content)
    undeclared = [name for name in referenced if name not in defined_names]
    if undeclared:
        raise HTTPException(422,
            f'Template references undeclared variables: {", ".join(sorted(undeclared))}')


def create_asset(store, cid, body):
    conv(store, cid)
    name = _validate_name(getattr(body, 'name', ''))
    initial_content = _validate_content(getattr(body, 'content', ''))
    variables = _validate_variables_json(getattr(body, 'variables', []))
    _check_template(initial_content, variables)
    aid = uid(); now = timestamp()
    with store.tx() as con:
        existing = con.execute(
            'SELECT id FROM prompt_assets WHERE conversation_id=? AND name=?',
            (cid, name)).fetchone()
        if existing is not None:
            raise HTTPException(409, f'A prompt named {name!r} already exists')
        con.execute(
            'INSERT INTO prompt_assets(id,conversation_id,name,created_at) VALUES(?,?,?,?)',
            (aid, cid, name, now))
        did = uid()
        con.execute(
            'INSERT INTO prompt_drafts(id,prompt_asset_id,revision,content,'
            'variables_json,base_version_id,updated_at) VALUES(?,?,?,?,?,?,?)',
            (did, aid, 1, initial_content, json.dumps(variables), None, now))
        emit(con, cid, 'prompt_created',
             payload={'prompt_id': aid, 'name': name, 'draft_revision': 1})
    return {'id': aid, 'name': name, 'created_at': now, 'latest_version': None,
            'draft': {'id': did, 'revision': 1, 'content': initial_content,
                      'variables': variables, 'base_version_id': None,
                      'updated_at': now}}


def list_assets(store, cid):
    conv(store, cid)
    rows = store.all(
        'SELECT a.id, a.name, a.created_at,'
        ' (SELECT v.id FROM prompt_versions v WHERE v.prompt_asset_id=a.id'
        '  ORDER BY v.version_number DESC LIMIT 1) AS latest_id,'
        ' (SELECT v.version_number FROM prompt_versions v WHERE v.prompt_asset_id=a.id'
        '  ORDER BY v.version_number DESC LIMIT 1) AS latest_number'
        ' FROM prompt_assets a WHERE a.conversation_id=? ORDER BY a.created_at DESC',
        (cid,))
    out = []
    for row in rows:
        out.append({
            'id': row['id'], 'name': row['name'], 'created_at': row['created_at'],
            'latest_version': ({'id': row['latest_id'], 'version_number': row['latest_number']}
                               if row['latest_id'] else None),
        })
    return {'items': out}


def read_asset(store, cid, aid):
    conv(store, cid)
    row = store.one(
        'SELECT * FROM prompt_assets WHERE id=? AND conversation_id=?', (aid, cid))
    if row is None:
        raise HTTPException(404, 'Prompt not found')
    versions = store.all(
        'SELECT id, version_number, content_sha256, published_at, restored_from'
        ' FROM prompt_versions WHERE prompt_asset_id=? ORDER BY version_number',
        (aid,))
    draft = store.one(
        'SELECT * FROM prompt_drafts WHERE prompt_asset_id=?', (aid,))
    latest = versions[-1] if versions else None
    return {
        'id': row['id'], 'name': row['name'], 'created_at': row['created_at'],
        'latest_version': ({'id': latest['id'], 'version_number': latest['version_number']}
                           if latest else None),
        'versions': [dict(v) for v in versions],
        'draft': ({'id': draft['id'], 'revision': draft['revision'],
                   'content': draft['content'],
                   'variables': json.loads(draft['variables_json']),
                   'base_version_id': draft['base_version_id'],
                   'updated_at': draft['updated_at']}
                  if draft else None),
    }


def update_draft(store, cid, aid, body):
    conv(store, cid)
    content = _validate_content(getattr(body, 'content', ''))
    variables = _validate_variables_json(getattr(body, 'variables', []))
    _check_template(content, variables)
    expected = getattr(body, 'expected_revision', None)
    now = timestamp()
    with store.tx() as con:
        asset = con.execute(
            'SELECT id FROM prompt_assets WHERE id=? AND conversation_id=?',
            (aid, cid)).fetchone()
        if asset is None:
            raise HTTPException(404, 'Prompt not found')
        draft = con.execute(
            'SELECT revision FROM prompt_drafts WHERE prompt_asset_id=?',
            (aid,)).fetchone()
        if draft is None:
            did = uid()
            con.execute(
                'INSERT INTO prompt_drafts(id,prompt_asset_id,revision,content,'
                'variables_json,base_version_id,updated_at) VALUES(?,?,?,?,?,?,?)',
                (did, aid, 1, content, json.dumps(variables), None, now))
            emit(con, cid, 'prompt_draft_saved',
                 payload={'prompt_id': aid, 'draft_id': did, 'revision': 1})
            return {'id': did, 'revision': 1, 'content': content,
                    'variables': variables, 'updated_at': now}
        current = draft['revision']
        if expected is not None and int(expected) != current:
            raise HTTPException(409,
                f'Draft revision conflict (expected {expected}, have {current})')
        new_rev = current + 1
        con.execute(
            'UPDATE prompt_drafts SET revision=?, content=?, variables_json=?, updated_at=?'
            ' WHERE prompt_asset_id=?',
            (new_rev, content, json.dumps(variables), now, aid))
        emit(con, cid, 'prompt_draft_saved',
             payload={'prompt_id': aid, 'revision': new_rev})
    return {'revision': new_rev, 'content': content, 'variables': variables,
            'updated_at': now}


def publish(store, cid, aid, body=None):
    conv(store, cid)
    expected = getattr(body, 'expected_revision', None) if body else None
    with store.tx() as con:
        asset = con.execute(
            'SELECT id FROM prompt_assets WHERE id=? AND conversation_id=?',
            (aid, cid)).fetchone()
        if asset is None:
            raise HTTPException(404, 'Prompt not found')
        draft = con.execute(
            'SELECT * FROM prompt_drafts WHERE prompt_asset_id=?', (aid,)).fetchone()
        if draft is None:
            raise HTTPException(422, 'Nothing to publish: no draft present')
        if expected is not None and int(expected) != draft['revision']:
            raise HTTPException(409, 'Draft revision conflict')
        content = draft['content']
        variables = json.loads(draft['variables_json'])
        _check_template(content, variables)
        max_row = con.execute(
            'SELECT MAX(version_number) AS n FROM prompt_versions WHERE prompt_asset_id=?',
            (aid,)).fetchone()
        next_number = (max_row['n'] or 0) + 1
        sha = hashlib.sha256(content.encode('utf-8')).hexdigest()
        vid = uid(); now = timestamp()
        con.execute(
            'INSERT INTO prompt_versions(id,prompt_asset_id,version_number,content,'
            'variables_json,content_sha256,published_at,restored_from) '
            'VALUES(?,?,?,?,?,?,?,?)',
            (vid, aid, next_number, content, draft['variables_json'], sha, now, None))
        emit(con, cid, 'prompt_published',
             payload={'prompt_id': aid, 'version_id': vid,
                      'version_number': next_number, 'content_sha256': sha})
    return {'id': vid, 'version_number': next_number, 'content_sha256': sha,
            'published_at': now, 'restored_from': None}


def _version_by_ref(con, cid, aid, version_ref):
    asset = con.execute(
        'SELECT id FROM prompt_assets WHERE id=? AND conversation_id=?',
        (aid, cid)).fetchone()
    if asset is None:
        raise HTTPException(404, 'Prompt not found')
    if version_ref in (None, '', 'latest'):
        row = con.execute(
            'SELECT * FROM prompt_versions WHERE prompt_asset_id=?'
            ' ORDER BY version_number DESC LIMIT 1', (aid,)).fetchone()
    elif isinstance(version_ref, int) or (isinstance(version_ref, str) and version_ref.isdigit()):
        row = con.execute(
            'SELECT * FROM prompt_versions WHERE prompt_asset_id=? AND version_number=?',
            (aid, int(version_ref))).fetchone()
    else:
        row = con.execute(
            'SELECT * FROM prompt_versions WHERE id=? AND prompt_asset_id=?',
            (version_ref, aid)).fetchone()
    if row is None:
        raise HTTPException(404, f'Prompt version {version_ref!r} not found')
    return row


def list_versions(store, cid, aid):
    conv(store, cid)
    with store.connection() as con:
        asset = con.execute(
            'SELECT id FROM prompt_assets WHERE id=? AND conversation_id=?',
            (aid, cid)).fetchone()
        if asset is None:
            raise HTTPException(404, 'Prompt not found')
        rows = con.execute(
            'SELECT id, version_number, content_sha256, published_at, restored_from'
            ' FROM prompt_versions WHERE prompt_asset_id=? ORDER BY version_number',
            (aid,)).fetchall()
        return {'items': [dict(r) for r in rows]}


def read_version(store, cid, aid, version_ref):
    conv(store, cid)
    with store.connection() as con:
        row = _version_by_ref(con, cid, aid, version_ref)
        return {
            'id': row['id'], 'prompt_asset_id': row['prompt_asset_id'],
            'version_number': row['version_number'],
            'content': row['content'],
            'variables': json.loads(row['variables_json']),
            'content_sha256': row['content_sha256'],
            'published_at': row['published_at'],
            'restored_from': row['restored_from'],
        }


def resolve_variables(store, cid, aid, body):
    conv(store, cid)
    version_ref = getattr(body, 'version', 'latest')
    values = getattr(body, 'values', {}) or {}
    with store.connection() as con:
        row = _version_by_ref(con, cid, aid, version_ref)
    defs = load_definitions(json.loads(row['variables_json']))
    try:
        rendered = resolve(row['content'], defs, values)
    except VariableResolutionError as exc:
        raise HTTPException(422, str(exc)) from exc
    return {
        'version_id': row['id'],
        'version_number': row['version_number'],
        'content_sha256': row['content_sha256'],
        'resolved_content': rendered,
        'values': values,
    }


def restore(store, cid, aid, body):
    conv(store, cid)
    version_ref = getattr(body, 'version', None)
    if version_ref in (None, ''):
        raise HTTPException(422, 'version is required for restore')
    with store.tx() as con:
        asset = con.execute(
            'SELECT id FROM prompt_assets WHERE id=? AND conversation_id=?',
            (aid, cid)).fetchone()
        if asset is None:
            raise HTTPException(404, 'Prompt not found')
        source = _version_by_ref(con, cid, aid, version_ref)
        max_row = con.execute(
            'SELECT MAX(version_number) AS n FROM prompt_versions WHERE prompt_asset_id=?',
            (aid,)).fetchone()
        next_number = (max_row['n'] or 0) + 1
        vid = uid(); now = timestamp()
        con.execute(
            'INSERT INTO prompt_versions(id,prompt_asset_id,version_number,content,'
            'variables_json,content_sha256,published_at,restored_from) '
            'VALUES(?,?,?,?,?,?,?,?)',
            (vid, aid, next_number, source['content'], source['variables_json'],
             source['content_sha256'], now, source['id']))
        emit(con, cid, 'prompt_restored',
             payload={'prompt_id': aid, 'new_version_id': vid,
                      'new_version_number': next_number,
                      'restored_from_id': source['id'],
                      'restored_from_number': source['version_number']})
    return {'id': vid, 'version_number': next_number,
            'content_sha256': source['content_sha256'],
            'restored_from': source['id'],
            'restored_from_number': source['version_number'],
            'published_at': now}


def compare(store, cid, aid, left_ref, right_ref):
    conv(store, cid)
    import difflib
    with store.connection() as con:
        left = _version_by_ref(con, cid, aid, left_ref)
        right = _version_by_ref(con, cid, aid, right_ref)
    left_lines = (left['content'] or '').splitlines()
    right_lines = (right['content'] or '').splitlines()
    diff = list(difflib.unified_diff(
        left_lines, right_lines,
        fromfile=f"v{left['version_number']}", tofile=f"v{right['version_number']}",
        lineterm='',
    ))
    return {
        'left': {'id': left['id'], 'version_number': left['version_number'],
                 'content': left['content'],
                 'variables': json.loads(left['variables_json']),
                 'content_sha256': left['content_sha256']},
        'right': {'id': right['id'], 'version_number': right['version_number'],
                  'content': right['content'],
                  'variables': json.loads(right['variables_json']),
                  'content_sha256': right['content_sha256']},
        'identical': left['content_sha256'] == right['content_sha256'],
        'unified_diff': '\n'.join(diff),
    }


def create_evaluation(store, cid, aid, body):
    conv(store, cid)
    version_ref = getattr(body, 'version', 'latest')
    criteria = getattr(body, 'criteria', [])
    if not isinstance(criteria, list):
        raise HTTPException(422, 'criteria must be a list')
    with store.tx() as con:
        row = _version_by_ref(con, cid, aid, version_ref)
        eid = uid(); now = timestamp()
        con.execute(
            'INSERT INTO prompt_evaluations(id,prompt_version_id,job_id,status,'
            'criteria_json,findings_json,created_at,updated_at) '
            'VALUES(?,?,?,?,?,?,?,?)',
            (eid, row['id'], None, 'queued', json.dumps(criteria), '{}', now, now))
        emit(con, cid, 'prompt_evaluation_queued',
             payload={'prompt_id': aid, 'version_id': row['id'],
                      'evaluation_id': eid, 'criteria_count': len(criteria)})
    return {'id': eid, 'prompt_version_id': row['id'], 'status': 'queued',
            'criteria': criteria, 'created_at': now}


def _run_criterion(index, c, content, variables):
    if not isinstance(c, dict) or 'kind' not in c:
        return {'index': index, 'criterion': c, 'outcome': 'error',
                'reason': "criterion must be an object with a 'kind' field"}
    kind = c['kind']
    def ok_result(ok, description):
        return {'index': index, 'criterion': c,
                'outcome': 'pass' if ok else 'fail', 'description': description}
    if kind == 'contains':
        return ok_result(c.get('value', '') in content,
                         f"substring {c.get('value')!r}")
    if kind == 'contains_ci':
        return ok_result(c.get('value', '').lower() in content.lower(),
                         f"substring (ci) {c.get('value')!r}")
    if kind == 'absent':
        return ok_result(c.get('value', '') not in content,
                         f"must not contain {c.get('value')!r}")
    if kind == 'declares_variable':
        names = {v['name'] for v in variables}
        return ok_result(c.get('name') in names, f"must declare {c.get('name')!r}")
    if kind == 'variable_count':
        lo = int(c.get('min', 0)); hi = int(c.get('max', 10**6))
        return ok_result(lo <= len(variables) <= hi,
                         f'variable count in [{lo},{hi}]')
    if kind == 'max_length':
        limit = int(c.get('value', 0))
        return ok_result(len(content) <= limit, f'content length <= {limit}')
    return {'index': index, 'criterion': c, 'outcome': 'error',
            'reason': f'unsupported criterion kind: {kind!r}'}


def run_evaluation(store, cid, aid, eid):
    conv(store, cid)
    with store.tx() as con:
        asset = con.execute(
            'SELECT id FROM prompt_assets WHERE id=? AND conversation_id=?',
            (aid, cid)).fetchone()
        if asset is None:
            raise HTTPException(404, 'Prompt not found')
        row = con.execute(
            'SELECT e.*, v.content AS v_content, v.variables_json AS v_vars'
            ' FROM prompt_evaluations e'
            ' JOIN prompt_versions v ON v.id=e.prompt_version_id'
            ' WHERE e.id=? AND v.prompt_asset_id=?',
            (eid, aid)).fetchone()
        if row is None:
            raise HTTPException(404, 'Evaluation not found')
        if row['status'] not in ('queued', 'failed'):
            raise HTTPException(409, f"Evaluation already in state {row['status']}")
        criteria = json.loads(row['criteria_json'] or '[]')
        content = row['v_content']
        variables = json.loads(row['v_vars'])
        results = []
        for i, c in enumerate(criteria):
            try:
                results.append(_run_criterion(i, c, content, variables))
            except Exception as exc:
                results.append({'index': i, 'criterion': c,
                                'outcome': 'error', 'reason': str(exc)})
        passed = sum(1 for r in results if r.get('outcome') == 'pass')
        failed = sum(1 for r in results if r.get('outcome') == 'fail')
        errored = sum(1 for r in results if r.get('outcome') == 'error')
        findings = {'passed': passed, 'failed': failed, 'errored': errored,
                    'results': results}
        status = 'completed' if errored == 0 else 'failed'
        now = timestamp()
        con.execute(
            'UPDATE prompt_evaluations SET status=?, findings_json=?, updated_at=? WHERE id=?',
            (status, json.dumps(findings), now, eid))
        emit(con, cid, 'prompt_evaluation_completed',
             payload={'prompt_id': aid, 'evaluation_id': eid, 'status': status,
                      'passed': passed, 'failed': failed, 'errored': errored})
    return {'id': eid, 'status': status, 'findings': findings, 'updated_at': now}


def list_evaluations(store, cid, aid):
    conv(store, cid)
    rows = store.all(
        'SELECT e.id, e.prompt_version_id, e.status, e.criteria_json, e.findings_json,'
        ' e.created_at, e.updated_at, v.version_number'
        ' FROM prompt_evaluations e'
        ' JOIN prompt_versions v ON v.id=e.prompt_version_id'
        ' WHERE v.prompt_asset_id=? ORDER BY e.created_at DESC', (aid,))
    out = []
    for row in rows:
        d = dict(row)
        d['criteria'] = json.loads(d.pop('criteria_json') or '[]')
        d['findings'] = json.loads(d.pop('findings_json') or '{}')
        out.append(d)
    return {'items': out}


def read_evaluation(store, cid, aid, eid):
    conv(store, cid)
    row = store.one(
        'SELECT e.*, v.version_number FROM prompt_evaluations e'
        ' JOIN prompt_versions v ON v.id=e.prompt_version_id'
        ' JOIN prompt_assets a ON a.id=v.prompt_asset_id'
        ' WHERE e.id=? AND a.id=? AND a.conversation_id=?',
        (eid, aid, cid))
    if row is None:
        raise HTTPException(404, 'Evaluation not found')
    out = dict(row)
    out['criteria'] = json.loads(out.pop('criteria_json') or '[]')
    out['findings'] = json.loads(out.pop('findings_json') or '{}')
    return out


def propose_optimization(store, cid, aid, body, settings, transport=None):
    conv(store, cid)
    with store.connection() as con:
        asset = con.execute(
            'SELECT id FROM prompt_assets WHERE id=? AND conversation_id=?',
            (aid, cid)).fetchone()
        if asset is None:
            raise HTTPException(404, 'Prompt not found')
        version_ref = getattr(body, 'version', None)
        base_version = None
        if version_ref:
            base_version = _version_by_ref(con, cid, aid, version_ref)
            base_content = base_version['content']
            base_variables = json.loads(base_version['variables_json'])
        else:
            draft = con.execute(
                'SELECT content, variables_json, revision FROM prompt_drafts WHERE prompt_asset_id=?',
                (aid,)).fetchone()
            if draft is None:
                raise HTTPException(422, 'No draft or version to optimize')
            base_content = draft['content']
            base_variables = json.loads(draft['variables_json'])
    if settings.provider == 'evidence':
        raise HTTPException(503,
            "No optimizer provider configured. Set ONESHOT_PROVIDER to a non-'evidence' value.")
    from systems.model_transport import system_connection, request_text, ModelTransportError
    connection = system_connection(settings)
    system = (
        'You are an advisory prompt-optimizer. Given a prompt template and its '
        'declared variables, return a strict JSON object: {"proposed": "...", '
        '"rationale": "..."} where proposed is the improved template using '
        'the SAME ${name} variables (do not invent new variables) and rationale '
        'summarises the specific improvements. Do NOT invent new instructions or '
        'authority. Keep the operator in control.'
    )
    user = json.dumps({
        'current_template': base_content,
        'declared_variables': base_variables,
        'constraints': 'Preserve variable names. One pass. Advisory only.',
    })
    try:
        answer = request_text(connection, system, user, json_output=True, transport=transport)
    except ModelTransportError as exc:
        raise HTTPException(502, f'Optimizer transport error: {exc}') from exc
    try:
        parsed = json.loads(answer)
        proposed = str(parsed['proposed'])
        rationale = str(parsed.get('rationale', ''))
    except (ValueError, KeyError, TypeError) as exc:
        raise HTTPException(502, f'Optimizer returned malformed output: {exc}') from exc
    try:
        _check_template(proposed, base_variables)
    except HTTPException as exc:
        raise HTTPException(502, f'Optimizer proposal invalid: {exc.detail}') from exc
    oid = uid(); now = timestamp()
    with store.tx() as con:
        con.execute(
            'INSERT INTO prompt_optimizations(id,prompt_asset_id,base_version_id,'
            'base_draft_revision,provider,model,proposed_content,rationale,status,created_at)'
            ' VALUES(?,?,?,?,?,?,?,?,?,?)',
            (oid, aid,
             base_version['id'] if base_version else None,
             None,
             connection.provider, connection.name, proposed, rationale,
             'proposed', now))
        emit(con, cid, 'prompt_optimization_proposed',
             payload={'prompt_id': aid, 'optimization_id': oid,
                      'provider': connection.provider, 'model': connection.name,
                      'base_version_id': base_version['id'] if base_version else None})
    return {'id': oid, 'status': 'proposed',
            'provider': connection.provider, 'model': connection.name,
            'base_version_id': base_version['id'] if base_version else None,
            'proposed_content': proposed, 'rationale': rationale,
            'created_at': now}


def list_optimizations(store, cid, aid):
    conv(store, cid)
    rows = store.all(
        'SELECT id, base_version_id, provider, model, status, created_at'
        ' FROM prompt_optimizations WHERE prompt_asset_id=? ORDER BY created_at DESC',
        (aid,))
    return {'items': [dict(r) for r in rows]}


def read_optimization(store, cid, aid, oid):
    conv(store, cid)
    row = store.one(
        'SELECT o.* FROM prompt_optimizations o'
        ' JOIN prompt_assets a ON a.id=o.prompt_asset_id'
        ' WHERE o.id=? AND a.conversation_id=?', (oid, cid))
    if row is None or row['prompt_asset_id'] != aid:
        raise HTTPException(404, 'Optimization not found')
    return dict(row)


def accept_optimization(store, cid, aid, oid):
    conv(store, cid)
    now = timestamp()
    with store.tx() as con:
        asset = con.execute(
            'SELECT id FROM prompt_assets WHERE id=? AND conversation_id=?',
            (aid, cid)).fetchone()
        if asset is None:
            raise HTTPException(404, 'Prompt not found')
        row = con.execute(
            'SELECT o.* FROM prompt_optimizations o WHERE o.id=? AND o.prompt_asset_id=?',
            (oid, aid)).fetchone()
        if row is None:
            raise HTTPException(404, 'Optimization not found')
        if row['status'] != 'proposed':
            raise HTTPException(409, f"Optimization is {row['status']}, not 'proposed'")
        base_vars_json = '[]'
        if row['base_version_id']:
            v = con.execute('SELECT variables_json FROM prompt_versions WHERE id=?',
                            (row['base_version_id'],)).fetchone()
            if v:
                base_vars_json = v['variables_json']
        else:
            d = con.execute('SELECT variables_json FROM prompt_drafts WHERE prompt_asset_id=?',
                            (aid,)).fetchone()
            if d:
                base_vars_json = d['variables_json']
        draft = con.execute('SELECT revision FROM prompt_drafts WHERE prompt_asset_id=?',
                            (aid,)).fetchone()
        if draft is None:
            did = uid()
            con.execute(
                'INSERT INTO prompt_drafts(id,prompt_asset_id,revision,content,'
                'variables_json,base_version_id,updated_at) VALUES(?,?,?,?,?,?,?)',
                (did, aid, 1, row['proposed_content'], base_vars_json,
                 row['base_version_id'], now))
            new_rev = 1
        else:
            new_rev = draft['revision'] + 1
            con.execute(
                'UPDATE prompt_drafts SET revision=?, content=?, variables_json=?,'
                ' base_version_id=?, updated_at=? WHERE prompt_asset_id=?',
                (new_rev, row['proposed_content'], base_vars_json,
                 row['base_version_id'], now, aid))
        con.execute("UPDATE prompt_optimizations SET status='accepted' WHERE id=?", (oid,))
        emit(con, cid, 'prompt_optimization_accepted',
             payload={'prompt_id': aid, 'optimization_id': oid,
                      'draft_revision': new_rev})
    return {'id': oid, 'status': 'accepted', 'draft_revision': new_rev}


def reject_optimization(store, cid, aid, oid):
    conv(store, cid)
    with store.tx() as con:
        row = con.execute(
            'SELECT o.status FROM prompt_optimizations o'
            ' JOIN prompt_assets a ON a.id=o.prompt_asset_id'
            ' WHERE o.id=? AND o.prompt_asset_id=? AND a.conversation_id=?',
            (oid, aid, cid)).fetchone()
        if row is None:
            raise HTTPException(404, 'Optimization not found')
        if row['status'] != 'proposed':
            raise HTTPException(409, f"Optimization is {row['status']}, not 'proposed'")
        con.execute(
            "UPDATE prompt_optimizations SET status='rejected' WHERE id=?", (oid,))
        emit(con, cid, 'prompt_optimization_rejected',
             payload={'prompt_id': aid, 'optimization_id': oid})
    return {'id': oid, 'status': 'rejected'}
