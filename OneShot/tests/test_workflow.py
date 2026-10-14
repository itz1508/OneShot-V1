import base64,hashlib,threading,os,json
from pathlib import Path
from systems.operations import Worker,recover
from systems.settings import Settings
from systems.store import Store
from systems.file_store import FileStore

def ingest(c,cid,name='rules.md',text='Preserve evidence.\nDo not alter originals.'):
    r=c.post(f'/api/conversations/{cid}/sources/actions',json={'action':'INPUT_SOURCE','name':name,'content':text})
    assert r.status_code==201,r.text
    return r.json()

def admit(c,cid,sources,key='key-001',prompt_id=None):
    if prompt_id is None:
        saved=c.post(f'/api/conversations/{cid}/messages',json={'channel':'system','content':'Prepare evidence for these selected sources.'})
        assert saved.status_code==201,saved.text
        prompt_id=saved.json()['id']
    body={'operation':'auto_generate','prompt_message_id':prompt_id,'source_ids':[s['source_id'] for s in sources],
          'expected_versions':{s['source_id']:s['version'] for s in sources},'idempotency_key':key}
    return c.post(f'/api/conversations/{cid}/jobs',json=body)

def test_api_auth_and_security(setup):
    c,app=setup
    assert c.get('/api/capabilities',headers={'Authorization':'Bearer invalid'}).status_code==401
    assert c.get('/health').json().get('ok') is True
    assert c.get('/api/capabilities').status_code==200
    assert c.get('/api/capabilities').headers['X-Content-Type-Options']=='nosniff'

def test_e2e_durable_real_events_and_packet(conversation,tmp_path):
    c,app,cid=conversation
    src=ingest(c,cid)
    req=admit(c,cid,[src]);assert req.status_code==202,req.text
    jid=req.json()['id']
    # Admission did not secretly run the job or invent execution events.
    assert c.get(f'/api/conversations/{cid}/jobs/{jid}').json()['status']=='queued'
    before=c.get(f'/api/conversations/{cid}/events').json()['events']
    assert not any(e['kind']=='node_started' for e in before)
    assert app.state.worker.step()==jid
    job=c.get(f'/api/conversations/{cid}/jobs/{jid}').json()
    assert job['status']=='completed'
    artifact=c.get(f"/api/conversations/{cid}/artifacts/{job['artifact_id']}").json()
    assert artifact['kind']=='evidence_packet'
    assert src['sha256'] in artifact['content'] and 'Preserve evidence.' in artifact['content']
    assert 'semantic completeness' in artifact['limitations'][0]
    ev=c.get(f'/api/conversations/{cid}/events').json()['events']
    assert [x['seq'] for x in ev]==list(range(1,len(ev)+1))
    assert {'job_started','job_completed','checklist_prepared','node_started','node_completed'}<={x['kind'] for x in ev}
    resume=c.get(f'/api/conversations/{cid}/events?after={ev[4]["seq"]}').json()['events']
    assert resume[0]['seq']==ev[5]['seq']
    trace=c.get(f'/api/conversations/{cid}/jobs/{jid}/trace').json()
    assert all(n['status']=='completed' for n in trace['nodes'])
    assert all(x['status']=='observed' for x in trace['edges'])
    rid=next(e['run_id'] for e in ev if e['kind']=='job_started')
    assert c.get(f'/api/conversations/{cid}/runs/{rid}').json()['job_id']==jid

def test_image_refuse_without_vision(conversation):
    c,app,cid=conversation
    src=c.post(f'/api/conversations/{cid}/sources/actions',json={
        'action':'IMPORT_SOURCE','name':'figure.png','content_base64':base64.b64encode(b'fakepng').decode()}).json()
    job=admit(c,cid,[src],key='image-123').json()
    app.state.worker.step()
    result=c.get(f"/api/conversations/{cid}/jobs/{job['id']}").json()
    assert result['status']=='blocked' and result['artifact_id'] is None
    t=c.get(f"/api/conversations/{cid}/jobs/{job['id']}/trace").json()
    assert next(n['status'] for n in t['nodes'] if n['id']=='auto_generator')=='skipped'

def test_source_actions_and_reference(conversation):
    c,app,cid=conversation
    s=ingest(c,cid)
    assert c.get(f"/api/conversations/{cid}/sources/{s['source_id']}/content").content.startswith(b'Preserve')
    ref=c.post(f'/api/conversations/{cid}/sources/actions',json={
        'action':'REFERENCE_SOURCE','name':'site','url':'https://docs.python.org/3/'}).json()
    assert ref['retrieved'] is False
    assert admit(c,cid,[ref],key='ref-123').status_code==422
    assert c.post(f'/api/conversations/{cid}/sources/actions',json={
        'action':'REFERENCE_SOURCE','name':'bad','url':'https://127.0.0.1/page'}).status_code==422
    s2=ingest(c,cid,'other.txt','abc')
    detached=c.post(f'/api/conversations/{cid}/sources/actions',json={'action':'REMOVE_SOURCE','source_id':s2['source_id']}).json()
    assert detached['detached'] and not detached['deleted']
    assert c.get(f'/api/conversations/{cid}/sources/{s2["source_id"]}/content').status_code==404
    assert c.post(f'/api/conversations/{cid}/sources/actions',json={'action':'ADD_SOURCE','source_id':s2['source_id']}).status_code==201
    assert c.post(f'/api/conversations/{cid}/sources/actions',json={'action':'DELETE_SOURCE','source_id':s2['source_id'],'confirm_delete':True}).json()['deleted']
    assert c.post(f'/api/conversations/{cid}/sources/actions',json={'action':'DELETE_SOURCE','source_id':s['source_id']}).status_code==422

def test_idempotency_scope_and_concurrency(conversation):
    c,app,cid=conversation
    first=ingest(c,cid);second=ingest(c,cid,'b.md','another')
    message=c.post(f'/api/conversations/{cid}/messages',json={'channel':'system','content':'Analyze scope.'}).json()['id']
    a=admit(c,cid,[first],prompt_id=message);assert a.status_code==202
    b=admit(c,cid,[first],prompt_id=message);assert b.json()['reused'] is True and a.json()['id']==b.json()['id']
    assert admit(c,cid,[second],prompt_id=message).status_code==409
    assert app.state.worker.step()==a.json()['id']
    assert app.state.worker.step() is None

def test_snapshot_immutability_tampering_detected(conversation):
    c,app,cid=conversation
    src=ingest(c,cid)
    job=admit(c,cid,[src],key='tamper-123').json()
    path=app.state.store.files.root/src['sha256'][:2]/src['sha256']
    path.write_bytes(b'corrupted')
    app.state.worker.step()
    assert c.get(f"/api/conversations/{cid}/jobs/{job['id']}").json()['status']=='failed'
    assert c.get(f"/api/conversations/{cid}/sources/{src['source_id']}/content").status_code==500

def test_drafts_immutable_and_409(conversation):
    c,app,cid=conversation
    src=ingest(c,cid)
    draft=c.post(f'/api/conversations/{cid}/drafts',json={'source_id':src['source_id'],'content':'A'}).json()
    did=draft['id']
    revised=c.patch(f'/api/conversations/{cid}/drafts/{did}',json={'expected_revision':1,'content':'B'})
    assert revised.status_code==200 and revised.json()['revision']==2
    assert c.patch(f'/api/conversations/{cid}/drafts/{did}',json={'expected_revision':1,'content':'C'}).status_code==409
    assert c.get(f'/api/conversations/{cid}/drafts/{did}').json()['content']=='B'
    assert app.state.store.one('SELECT content FROM draft_revisions WHERE draft_id=? AND revision=1',(did,))['content']=='A'
    assert c.get(f"/api/conversations/{cid}/sources/{src['source_id']}/content").content.startswith(b'Preserve')

def test_apply_authorized_verified_stale_and_reuse(conversation):
    c,app,cid=conversation
    s=ingest(c,cid);j=admit(c,cid,[s],key='apply-123').json();app.state.worker.step()
    artifact=c.get(f"/api/conversations/{cid}/jobs/{j['id']}").json()['artifact_id']
    prepare=c.post(f'/api/conversations/{cid}/apply/prepare',json={'artifact_id':artifact,'destination':'notes/result.md'})
    assert prepare.status_code==200
    token=prepare.json()['confirmation_token']
    assert not (app.state.store.root/'applied/notes/result.md').exists()
    confirm=c.post(f'/api/conversations/{cid}/apply/confirm',json={'confirmation_token':token,'confirm_apply':True})
    assert confirm.status_code==200,confirm.text
    assert confirm.json()['verified'] and '+++ applied' in confirm.json()['final_applied_diff']
    p=app.state.store.root/'applied/notes/result.md'
    assert hashlib.sha256(p.read_bytes()).hexdigest()==confirm.json()['result_sha256']
    assert c.post(f'/api/conversations/{cid}/apply/confirm',json={'confirmation_token':token,'confirm_apply':True}).status_code==403
    assert c.post(f'/api/conversations/{cid}/apply/prepare',json={'artifact_id':artifact,'destination':'notes/result.md'}).status_code==409
    assert c.post(f'/api/conversations/{cid}/apply/prepare',json={'artifact_id':artifact,'destination':'../escape.md'}).status_code==422
    assert c.get(f"/api/conversations/{cid}/sources/{s['source_id']}/content").content.startswith(b'Preserve')

def test_agent_without_integration_does_not_lock_system_or_fake_replies(conversation):
    c,app,cid=conversation
    path=f'/api/conversations/{cid}'
    assert c.post(path+'/messages',json={'channel':'system','content':'system draft'}).status_code==201
    assert c.patch(path+'/session',json={'agent_active':True}).status_code==409
    assert c.post(path+'/messages',json={'channel':'agent','content':'hello agent'}).status_code==409
    assert c.post(path+'/messages',json={'channel':'system','content':'system still works'}).status_code==201
    assert c.get(path).json()['agent_active'] is False
    assert [x['channel'] for x in c.get(path).json()['messages']]==['system','system']

    # Recover previously persisted unavailable-Agent sessions; retain history.
    with app.state.store.tx() as con:
        con.execute('UPDATE conversations SET agent_active=1 WHERE id=?',(cid,))
    assert recover(app.state.store)==0
    assert c.get(path).json()['agent_active'] is False
    assert c.post(path+'/messages',json={'channel':'system','content':'after restart'}).status_code==201
    assert [x['channel'] for x in c.get(path).json()['messages']]==['system']*3

def test_restart_recovery(conversation):
    c,app,cid=conversation
    s=ingest(c,cid);jid=admit(c,cid,[s],key='restart-123').json()['id']
    with app.state.store.tx() as con:
        con.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
        con.execute("INSERT INTO runs(id,job_id,attempt,status,started_at) VALUES(?,?,1,'running','now')",('r'*32,jid))
    assert recover(app.state.store)==1
    assert c.get(f'/api/conversations/{cid}/jobs/{jid}').json()['status']=='failed'
    assert app.state.worker.step() is None

def test_events_isolation_between_conversations(conversation):
    c,app,cid=conversation
    other=c.post('/api/conversations',json={'title':'other'}).json()['id']
    src=ingest(c,cid)
    jid=admit(c,cid,[src],key='isolate-123').json()['id']
    app.state.worker.step()
    assert c.get(f'/api/conversations/{other}/jobs/{jid}').status_code==404
    assert c.get(f'/api/conversations/{other}/jobs/{jid}/trace').status_code==404
    assert not c.get(f'/api/conversations/{other}/events').json()['events']

def test_event_trace_is_not_limited_by_other_job_events(conversation):
    c,app,cid=conversation
    src=ingest(c,cid)
    j1=admit(c,cid,[src],key='job001').json()['id']
    j2=admit(c,cid,[src],key='job002').json()['id']
    app.state.worker.step();app.state.worker.step()
    with app.state.store.tx() as con:
        from systems.store import emit
        for i in range(510):emit(con,cid,'noise',job_id=j1)
    graph=c.get(f'/api/conversations/{cid}/jobs/{j2}/trace').json()
    assert all(e['job_id']==j2 for e in graph['events'])
    assert any(e['kind']=='job_completed' for e in graph['events'])

def test_apply_target_changes_after_prepare(conversation):
    c,app,cid=conversation
    src=ingest(c,cid)
    job=admit(c,cid,[src],key='drift001').json()['id'];app.state.worker.step()
    art=c.get(f'/api/conversations/{cid}/jobs/{job}').json()['artifact_id']
    token=c.post(f'/api/conversations/{cid}/apply/prepare',json={'artifact_id':art,'destination':'safe/file.md'}).json()['confirmation_token']
    target=app.state.store.root/'applied/safe/file.md'
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text('external edit')
    r=c.post(f'/api/conversations/{cid}/apply/confirm',json={'confirmation_token':token,'confirm_apply':True})
    assert r.status_code==409 and target.read_text()=='external edit'

def test_undetermined_apply_is_not_called_verified_on_recovery(conversation):
    c,app,cid=conversation
    src=ingest(c,cid)
    job=admit(c,cid,[src],key='applyrecovery').json()['id'];app.state.worker.step()
    art=c.get(f'/api/conversations/{cid}/jobs/{job}').json()['artifact_id']
    token=c.post(f'/api/conversations/{cid}/apply/prepare',json={'artifact_id':art,'destination':'saved.txt'}).json()['confirmation_token']
    with app.state.store.tx() as con:con.execute("UPDATE apply_intents SET state='applying' WHERE id=?",(token,))
    recover(app.state.store)
    assert app.state.store.one('SELECT state FROM apply_intents WHERE id=?',(token,))['state']=='needs_review'
    assert c.post(f'/api/conversations/{cid}/apply/confirm',json={'confirmation_token':token,'confirm_apply':True}).status_code==403

def test_scope_memory_limit(conversation):
    c,app,cid=conversation
    sources=[ingest(c,cid,f'doc{i}.txt','a'*750_000) for i in range(3)]
    assert admit(c,cid,sources,key='limit-123').status_code==413
    assert app.state.store.one('SELECT COUNT(*) AS n FROM jobs')['n']==0

def test_failed_operation_closes_active_trace_node(conversation):
    c,app,cid=conversation
    src=ingest(c,cid)
    jid=admit(c,cid,[src],key='failtrace001').json()['id']
    path=app.state.store.files.root/src['sha256'][:2]/src['sha256'];path.unlink()
    app.state.worker.step()
    graph=c.get(f'/api/conversations/{cid}/jobs/{jid}/trace').json()
    assert next(n for n in graph['nodes'] if n['id']=='source_access')['status']=='failed'
    assert any(e['kind']=='job_failed' for e in graph['events'])


def test_prompt_is_required_scoped_and_bound_to_job(conversation):
    c,app,cid=conversation
    src=ingest(c,cid,'api.py','def validate_session():\n    return True')
    scope={'operation':'auto_generate','source_ids':[src['source_id']],
           'expected_versions':{src['source_id']:1},'idempotency_key':'prompt-bind-01'}
    assert c.post(f'/api/conversations/{cid}/jobs',json=scope).status_code==422
    assert c.post(f'/api/conversations/{cid}/jobs',json={**scope,'prompt_message_id':'a'*32}).status_code==422
    other=c.post('/api/conversations',json={'title':'other'}).json()['id']
    wrong=c.post(f'/api/conversations/{other}/messages',json={'channel':'system','content':'wrong scope'}).json()['id']
    assert c.post(f'/api/conversations/{cid}/jobs',json={**scope,'prompt_message_id':wrong}).status_code==422
    prompt=c.post(f'/api/conversations/{cid}/messages',json={'channel':'system','content':'Explain `validate_session` precisely.'}).json()['id']
    admitted=c.post(f'/api/conversations/{cid}/jobs',json={**scope,'prompt_message_id':prompt})
    assert admitted.status_code==202,admitted.text
    job_id=admitted.json()['id']
    assert c.get(f'/api/conversations/{cid}/jobs/{job_id}').json()['prompt_message_id']==prompt
    assert app.state.worker.step()==job_id
    job=c.get(f'/api/conversations/{cid}/jobs/{job_id}').json()
    result=c.get(f"/api/conversations/{cid}/artifacts/{job['artifact_id']}").json()
    assert 'Explain `validate_session` precisely.' in result['content']
    assert 'Literal code-term pointers' in result['content']
    assert '`validate_session`: api.py' in result['content']
    assert 'L1: def validate_session():' in result['content']
    assert 'L2:     return True' in result['content']
    assert 'not a semantic answer' in result['content']
    assert c.post(f'/api/conversations/{cid}/jobs',json={**scope,'prompt_message_id':prompt}).json()['reused']
    another=c.post(f'/api/conversations/{cid}/messages',json={'channel':'system','content':'Summarize separately.'}).json()['id']
    assert c.post(f'/api/conversations/{cid}/jobs',json={**scope,'prompt_message_id':another}).status_code==409
    original=c.get(f"/api/conversations/{cid}/sources/{src['source_id']}/content").content.decode()
    assert original=='def validate_session():\n    return True'

def test_schema_v1_reopens_without_data_loss(tmp_path):
    from systems.store import SCHEMA
    import sqlite3
    d=tmp_path/'v1';d.mkdir();db=d/'oneshot.sqlite3'
    con=sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute('PRAGMA user_version=1')
    con.execute("INSERT INTO conversations(id,title) VALUES('abc','preserved')")
    con.commit();con.close()
    store=Store(d)
    assert store.one('SELECT title FROM conversations WHERE id=?',('abc',))['title']=='preserved'
    with store.connection() as con:
        assert con.execute('PRAGMA user_version').fetchone()[0]==7
        assert any(row[1]=='prompt_message_id' for row in con.execute('PRAGMA table_info(jobs)'))


def test_source_names_and_code_variable_provenance_survive_content_dedup(conversation):
    c,app,cid=conversation
    text='session_token = "original"\n'
    first=ingest(c,cid,'config.py',text)
    second=ingest(c,cid,'auth.py',text)
    assert first['source_id']!=second['source_id']
    assert first['sha256']==second['sha256']  # Same immutable bytes are content-addressed.
    indexed={item['id']:item for item in c.get(f'/api/conversations/{cid}/sources').json()}
    assert indexed[first['source_id']]['name']=='config.py'
    assert indexed[second['source_id']]['name']=='auth.py'
    prompt=c.post(f'/api/conversations/{cid}/messages',json={
        'channel':'system','content':'Find literal `session_token` in the selected source files.'}).json()['id']
    response=admit(c,cid,[first,second],key='file-name-001',prompt_id=prompt)
    assert response.status_code==202,response.text
    app.state.worker.step()
    job=c.get(f"/api/conversations/{cid}/jobs/{response.json()['id']}").json()
    assert job['status']=='completed'
    document=c.get(f"/api/conversations/{cid}/artifacts/{job['artifact_id']}").json()['content']
    for src,filename in ((first,'config.py'),(second,'auth.py')):
        assert f'## {filename}' in document
        assert f'Source ID: {src["source_id"]}' in document
        assert f'SHA-256: {src["sha256"]}' in document
        assert f'{filename} (source {src["source_id"]}) L1' in document
        actual=c.get(f'/api/conversations/{cid}/sources/{src["source_id"]}/content')
        assert actual.content==text.encode()
    assert 'L1: session_token = "original"' in document


def test_available_source_inventory_readds_without_changing_original(conversation):
    c, app, cid = conversation
    original = ingest(c, cid, 'retained.md', 'Exact retained text.')
    url = f'/api/conversations/{cid}/sources'
    assert original['source_id'] not in {s['id'] for s in c.get(url+'/available').json()}
    removed = c.post(url+'/actions',json={'action':'REMOVE_SOURCE','source_id':original['source_id']})
    assert removed.status_code==201 and removed.json()['deleted'] is False
    inventory=c.get(url+'/available')
    assert inventory.status_code==200
    assert any(item['id']==original['source_id'] for item in inventory.json())
    assert c.post(url+'/actions',json={'action':'ADD_SOURCE','source_id':original['source_id']}).status_code==201
    assert original['source_id'] not in {s['id'] for s in c.get(url+'/available').json()}
    assert c.get(url+'/'+original['source_id']+'/content').content == b'Exact retained text.'


def test_apply_target_preview_and_persisted_verified_readback(conversation):
    c, app, cid = conversation
    src=ingest(c,cid)
    job=admit(c,cid,[src],key='applyui123').json()
    app.state.worker.step()
    artifact=c.get(f'/api/conversations/{cid}/jobs/{job["id"]}').json()['artifact_id']
    prefix=f'/api/conversations/{cid}'
    target=c.get(prefix+'/apply/target',params={'destination':'preview/file.md'})
    assert target.status_code==200 and target.json()['exists'] is False
    plan=c.post(prefix+'/apply/prepare',json={'artifact_id':artifact,'destination':'preview/file.md',
                                               'expected_target_sha256':target.json()['sha256']})
    assert plan.status_code==200,plan.text
    assert not (app.state.store.root/'applied/preview/file.md').exists()
    applied=c.post(prefix+'/apply/confirm',json={'confirmation_token':plan.json()['confirmation_token'],
                                                  'confirm_apply':True})
    assert applied.status_code==200,applied.text
    proof=c.get(prefix+'/applied/'+applied.json()['id'])
    assert proof.status_code==200 and proof.json()['verified']
    assert proof.json()['final_applied_diff']==applied.json()['final_applied_diff']
    assert proof.json()['result_sha256']==applied.json()['result_sha256']
    old_src=c.get(prefix+'/sources/'+src['source_id']+'/content').content
    (app.state.store.root/'applied/preview/file.md').write_text('tampered')
    assert c.get(prefix+'/applied/'+applied.json()['id']).status_code==409
    assert c.get(prefix+'/sources/'+src['source_id']+'/content').content==old_src
    assert c.get(prefix+'/apply/target',params={'destination':'../escaped.md'}).status_code==422


def test_partial_source_coverage_is_truthful_and_persisted(conversation):
    c,app,cid=conversation
    valid=ingest(c,cid,'good.md','This source is readable.')
    invalid=c.post(f'/api/conversations/{cid}/sources/actions',json={
        'action':'IMPORT_SOURCE','name':'image.png',
        'content_base64':base64.b64encode(b'invalid-image').decode()}).json()
    job=admit(c,cid,[valid,invalid],key='coverage001').json()
    app.state.worker.step()
    current=c.get(f'/api/conversations/{cid}/jobs/{job["id"]}').json()
    assert current['status']=='blocked'
    events=c.get(f'/api/conversations/{cid}/jobs/{job["id"]}/trace').json()['events']
    checked=next(x['payload'] for x in events if x['kind']=='coverage_assessed')
    assert checked['structural_state']=='incomplete'
    assert checked['readable_source_count']==1 and checked['selected_source_count']==2
    assert checked['semantic_sufficiency']=='not_evaluated'
    assert checked['missing'][0]['source_id']==invalid['source_id']
    assert any(x['kind']=='job_blocked' and x['payload']['structural_state']=='incomplete' for x in events)
    assert not any(x['kind']=='node_started' and x['node_id']=='auto_generator' for x in events)


def test_unusable_scope_is_reported_without_fabricated_generation(conversation):
    c,app,cid=conversation
    bad=c.post(f'/api/conversations/{cid}/sources/actions',json={
        'action':'IMPORT_SOURCE','name':'not-readable.pdf',
        'content_base64':base64.b64encode(b'%PDF not parsed').decode()}).json()
    j=admit(c,cid,[bad],key='unusable001').json()
    app.state.worker.step()
    events=c.get(f'/api/conversations/{cid}/jobs/{j["id"]}/trace').json()['events']
    assert next(e['payload']['structural_state'] for e in events if e['kind']=='coverage_assessed')=='unusable'
    assert c.get(f'/api/conversations/{cid}/jobs/{j["id"]}').json()['artifact_id'] is None


def test_inspect_sources_skips_model_and_retains_partial_evidence(conversation):
    c, app, cid=conversation
    valid=ingest(c,cid,'readable.md','Read me without a model.')
    invalid=c.post(f'/api/conversations/{cid}/sources/actions',json={
        'action':'IMPORT_SOURCE','name':'diagram.png',
        'content_base64':base64.b64encode(b'not-image-bytes').decode()}).json()
    prompt=c.post(f'/api/conversations/{cid}/messages',json={'channel':'system','content':'Inspect selected files.'}).json()['id']
    scope=[valid,invalid]
    request={'operation':'inspect_sources','prompt_message_id':prompt,
        'source_ids':[x['source_id'] for x in scope],
        'expected_versions':{x['source_id']:x['version'] for x in scope},
        'idempotency_key':'inspect001'}
    res=c.post(f'/api/conversations/{cid}/jobs',json=request)
    assert res.status_code==202,res.text
    app.state.worker.step()
    job=c.get(f'/api/conversations/{cid}/jobs/{res.json()["id"]}').json()
    assert job['status']=='completed' and job['artifact_id']
    artifact=c.get(f'/api/conversations/{cid}/artifacts/{job["artifact_id"]}').json()
    assert artifact['kind']=='evidence_packet' and 'Read me without a model.' in artifact['content']
    assert 'diagram.png' in artifact['content'] and 'Limitation:' in artifact['content']
    trace=c.get(f'/api/conversations/{cid}/jobs/{job["id"]}/trace').json()
    assert next(n['status'] for n in trace['nodes'] if n['id']=='auto_generator')=='skipped'
    assert next(e['payload']['structural_state'] for e in trace['events'] if e['kind']=='coverage_assessed')=='incomplete'
