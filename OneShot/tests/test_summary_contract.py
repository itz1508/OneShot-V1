"""Summary export is a separate user operation, never an evidence alias.

Tests use a protocol responder as a diagnostic, not semantic-model evidence.
"""
import json
import httpx
from fastapi.testclient import TestClient
from systems.api import create_app
from systems.settings import Settings
from systems.auto_generator import AutoGenerator
from tests.conftest import TOKEN


def make_job(client,cid,operation):
    prefix=f'/api/conversations/{cid}'
    objective=client.post(prefix+'/messages',json={
        'channel':'system','content':'Summarize the named requirements faithfully.'}).json()
    source=client.post(prefix+'/sources/actions',json={
        'action':'INPUT_SOURCE','name':'requirements.md',
        'content':'A. Preserve originals.\nB. Require Apply confirmation.'}).json()
    payload={'operation':operation,'prompt_message_id':objective['id'],
             'source_ids':[source['source_id']],
             'expected_versions':{source['source_id']:source['version']},
             'idempotency_key':'summarize123'}
    job=client.post(prefix+'/jobs',json=payload)
    assert job.status_code==202,job.text
    return prefix,source,job.json()['id']


def test_model_summary_produces_strict_one_field_output_json_and_provenance(tmp_path):
    model_summary='The requirements preserve original source bytes and require confirmation before Apply.'
    def respond(request):
        submitted=json.loads(request.content)
        assert 'single key summary' in submitted['messages'][0]['content']
        return httpx.Response(200,json={'done':True,'message':{
            'content':json.dumps({'summary':model_summary})}})
    settings=Settings(tmp_path,TOKEN,provider='ollama',model_name='local-contract-model')
    generator=AutoGenerator(settings,transport=httpx.MockTransport(respond))
    app=create_app(settings,auto_worker=False,generator=generator)
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer '+TOKEN
        cid=client.post('/api/conversations',json={'title':'summary-contract'}).json()['id']
        prefix,source,jid=make_job(client,cid,'summarize')
        assert app.state.worker.step()==jid
        state=client.get(prefix+'/jobs/'+jid).json()
        assert state['status']=='completed' and state['artifact_id']
        aid=state['artifact_id']
        summary=client.get(prefix+'/artifacts/'+aid+'/summary')
        assert summary.status_code==200,summary.text
        assert summary.json()=={'summary':model_summary}
        assert 'filename="output.json"' in summary.headers['content-disposition']
        evidence=client.get(prefix+'/artifacts/'+aid+'/evidence').json()
        assert [s['source_id'] for s in evidence['sources']]==[source['source_id']]
        assert client.get(prefix+'/sources/'+source['source_id']+'/content').text.startswith('A. Preserve')
        assert client.get(prefix+'/artifacts/'+aid+'/export').json()['kind']=='summary'


def test_evidence_mode_blocks_semantic_summary_without_fabrication(conversation):
    c,app,cid=conversation
    prefix,src,jid=make_job(c,cid,'summarize')
    app.state.worker.step()
    job=c.get(prefix+'/jobs/'+jid).json()
    assert job['status']=='blocked' and job['artifact_id'] is None
    assert any(e['kind']=='node_skipped' and e['node_id']=='auto_generator'
               for e in c.get(prefix+'/jobs/'+jid+'/trace').json()['events'])


def test_model_contract_rejects_extra_fields_and_avoids_summary_artifact(tmp_path):
    def invalid(request):
        return httpx.Response(200,json={'done':True,'message':{
            'content':'{"summary":"Enough text","extra":"not approved"}'}})
    settings=Settings(tmp_path,TOKEN,provider='ollama',model_name='local-contract-model')
    app=create_app(settings,auto_worker=False,generator=AutoGenerator(settings,transport=httpx.MockTransport(invalid)))
    with TestClient(app) as c:
        c.headers['Authorization']='Bearer '+TOKEN
        cid=c.post('/api/conversations',json={'title':'bad summary'}).json()['id']
        prefix,src,jid=make_job(c,cid,'summarize')
        app.state.worker.step()
        job=c.get(prefix+'/jobs/'+jid).json()
        assert job['status']=='failed' and job['artifact_id'] is None
