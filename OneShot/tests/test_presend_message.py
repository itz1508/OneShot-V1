"""Transport contract for reviewed System messages (UI approval is tested separately)."""


def test_system_message_retains_exact_approved_context_and_original(conversation):
    c,app,cid=conversation
    original='  Objective: Preserve data.\r\nConstraints:\r\n- Do not delete.  \r\n'
    summary='Preserve data and avoid deletion.'
    approved=(
        'Reviewed context summary (user approved; not independently verified):\n'
        +summary+'\n\nOriginal user input (verbatim):\n'+original
    )
    route=f'/api/conversations/{cid}/messages'
    result=c.post(route,json={'channel':'system','content':approved})
    assert result.status_code==201,result.text
    assert result.json()['content']==approved
    assert c.get(f'/api/conversations/{cid}').json()['messages'][0]['content']==approved
    saved=app.state.store.one('SELECT content FROM messages WHERE id=?',(result.json()['id'],))
    assert saved['content'].endswith(original)
    ev=c.get(f'/api/conversations/{cid}/events').json()['events']
    assert len([x for x in ev if x['kind']=='message_saved'])==1
    assert original not in str(ev)


def test_system_message_backend_rejects_unapproved_oversized_payload(conversation):
    c,app,cid=conversation
    before=c.get(f'/api/conversations/{cid}').json()['messages']
    response=c.post(f'/api/conversations/{cid}/messages',json={
        'channel':'system','content':'a'*100_001,
    })
    assert response.status_code==422,response.text
    assert c.get(f'/api/conversations/{cid}').json()['messages']==before


def test_reviewed_message_http_duplicate_safe_retry(conversation):
    client,app,cid=conversation
    endpoint=f'/api/conversations/{cid}/messages'
    original='Objective: Preserve exactly.\n```yaml\nConstraints: example only\n```'
    key='approved_20261010_1234'
    body={'channel':'system','content':original,'idempotency_key':key}
    first=client.post(endpoint,json=body)
    assert first.status_code==201,first.text
    retry=client.post(endpoint,json=body)
    assert retry.status_code==201,retry.text
    assert retry.json()==first.json()
    assert len(client.get(f'/api/conversations/{cid}').json()['messages'])==1
    collision=client.post(endpoint,json={**body,'content':'different'})
    assert collision.status_code==409,collision.text
    events=client.get(f'/api/conversations/{cid}/events').json()['events']
    assert sum(e['kind']=='message_saved' for e in events)==1
