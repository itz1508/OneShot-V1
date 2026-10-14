"""Artifact-to-immutable-source navigation and trustworthy export."""
import hashlib
import json


def build_evidence(conversation):
    client, app, cid = conversation
    msg = client.post(f'/api/conversations/{cid}/messages',
                      json={'channel': 'system', 'content': 'Extract supported evidence'})
    assert msg.status_code == 201
    original = b'Source A\nL2: precise evidence\n'
    source = client.post(f'/api/conversations/{cid}/sources/actions', json={
        'action': 'INPUT_SOURCE', 'name': 'alpha.md', 'content': original.decode()})
    assert source.status_code == 201
    sid = source.json()['source_id']
    job = client.post(f'/api/conversations/{cid}/jobs', json={
        'operation': 'auto_generate', 'prompt_message_id': msg.json()['id'],
        'source_ids': [sid], 'expected_versions': {sid: 1},
        'idempotency_key': 'evidence-navigation-unique'})
    assert job.status_code == 202, job.text
    assert app.state.worker.step()
    completed = client.get(f'/api/conversations/{cid}/jobs/{job.json()["id"]}').json()
    assert completed['status'] == 'completed', completed
    return client, app, cid, completed['artifact_id'], sid, original


def test_evidence_survives_source_detachment(conversation):
    c, _, cid, aid, sid, original = build_evidence(conversation)
    detach = c.post(f'/api/conversations/{cid}/sources/actions', json={'action':'REMOVE_SOURCE','source_id':sid})
    assert detach.status_code == 201
    assert c.get(f'/api/conversations/{cid}/sources/{sid}/content').status_code == 404
    evidence = c.get(f'/api/conversations/{cid}/artifacts/{aid}/evidence')
    assert evidence.status_code == 200
    assert evidence.json()['sources'] == [{
        'source_id': sid, 'name':'alpha.md', 'version':1,
        'sha256': hashlib.sha256(original).hexdigest(), 'available': True}]
    raw = c.get(f'/api/conversations/{cid}/artifacts/{aid}/evidence/{sid}/content')
    assert raw.status_code == 200 and raw.content == original
    exported = c.get(f'/api/conversations/{cid}/artifacts/{aid}/export')
    assert exported.status_code == 200
    assert exported.headers['content-disposition'].startswith('attachment;')
    assert exported.json()['kind'] == 'evidence_packet'
    assert exported.json()['sources'] == evidence.json()['sources']
    assert exported.json()['limitations'] and 'summary' not in exported.json()


def test_evidence_denies_other_conversation_and_unreferenced_source(conversation):
    c, _, cid, aid, sid, _ = build_evidence(conversation)
    other = c.post('/api/conversations',json={'title':'other'}).json()['id']
    assert c.get(f'/api/conversations/{other}/artifacts/{aid}/evidence').status_code == 404
    assert c.get(f'/api/conversations/{cid}/artifacts/{aid}/evidence/{"f"*32}/content').status_code == 404


def test_evidence_fails_closed_when_bytes_corrupted(conversation):
    c, app, cid, aid, sid, original = build_evidence(conversation)
    sha=hashlib.sha256(original).hexdigest()
    (app.state.store.files.root / sha[:2] / sha).write_bytes(b'untrusted replacement')
    metadata=c.get(f'/api/conversations/{cid}/artifacts/{aid}/evidence')
    assert metadata.status_code == 200
    assert metadata.json()['sources'][0]['available'] is False
    assert c.get(f'/api/conversations/{cid}/artifacts/{aid}/evidence/{sid}/content').status_code == 409
    exported=c.get(f'/api/conversations/{cid}/artifacts/{aid}/export')
    assert exported.status_code == 200 and exported.json()['sources'][0]['available'] is False


def test_provenance_contracts_exposed_in_openapi(conversation):
    c, _, cid = conversation
    doc = c.get('/openapi.json').json()
    evidence_path='/api/conversations/{cid}/artifacts/{aid}/evidence'
    export_path='/api/conversations/{cid}/artifacts/{aid}/export'
    assert evidence_path in doc['paths'] and export_path in doc['paths']
    assert 'ArtifactEvidenceBundle' in doc['components']['schemas']
    assert 'ArtifactExportRecord' in doc['components']['schemas']
