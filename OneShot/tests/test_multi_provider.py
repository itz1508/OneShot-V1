"""Wire-protocol and integrated persistence diagnostics, not semantic provider E2E."""
import json
from unittest.mock import patch
import httpx
import pytest
from fastapi.testclient import TestClient
from systems.model_transport import ModelConnection, ModelTransportError, request_text
from systems.settings import Settings
from systems.api import create_app
from tests.conftest import TOKEN

IDS = 'a'*32
PAYLOAD = json.dumps({'document':'Grounded result', 'source_ids_used':[IDS]})


def test_provider_wire_envelopes_are_distinct():
    def openai(req):
        b=json.loads(req.content)
        assert req.headers['authorization']=='Bearer key'
        assert b['response_format']=={'type':'json_object'}
        return httpx.Response(200,json={'choices':[{'finish_reason':'stop','message':{'content':PAYLOAD}}]})
    a=ModelConnection('openai','gpt-example','key','https://api.openai.com/v1/chat/completions')
    assert request_text(a,'System','Source',json_output=True,transport=httpx.MockTransport(openai))==PAYLOAD
    def gemini(req):
        b=json.loads(req.content)
        assert req.headers['x-goog-api-key']=='key'
        assert b['contents'][0]['role']=='user'
        assert b['generationConfig']=={'responseMimeType':'application/json'}
        assert 'messages' not in b
        return httpx.Response(200,json={'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':PAYLOAD}]}}]})
    g=ModelConnection('gemini','gemini-test','key',
        'https://generativelanguage.googleapis.com/v1beta/models/gemini-test:generateContent')
    assert request_text(g,'System','Source',json_output=True,transport=httpx.MockTransport(gemini))==PAYLOAD
    def ollama(req):
        b=json.loads(req.content)
        assert b['stream'] is False and b['format']=='json'
        assert 'Authorization' not in req.headers
        return httpx.Response(200,json={'done':True,'message':{'role':'assistant','content':PAYLOAD}})
    o=ModelConnection('ollama','local-model','','http://127.0.0.1:11434/api/chat')
    assert request_text(o,'System','Source',json_output=True,transport=httpx.MockTransport(ollama))==PAYLOAD


def test_untrusted_provider_cannot_request_tools_or_partial_success():
    c=ModelConnection('ollama','local-model','','http://localhost:11434/api/chat')
    cases=[{'done':False,'message':{'content':'not done'}},
           {'done':True,'message':{'content':'okay','tool_calls':[{'function':{'name':'delete_source'}}]}},
           {'done':True,'message':{'content':''}}]
    for body in cases:
        with pytest.raises(ModelTransportError):
            request_text(c,'System','Source',json_output=False,
                transport=httpx.MockTransport(lambda req:httpx.Response(200,json=body)))
    with pytest.raises(ValueError):
        ModelConnection('ollama','local-model','','http://169.254.169.254/api/chat')
    with pytest.raises(ValueError):
        ModelConnection('gemini','gemini-test','key','https://evil.example/v1beta/models/name:generateContent')
    with pytest.raises(ModelTransportError):
        request_text(c,'System','Source',json_output=True,
            transport=httpx.MockTransport(lambda req:httpx.Response(200,content=b'x'*1_000_010)))


def test_agents_configured_separately_and_persisted_without_system_authority(tmp_path):
    cfg=Settings(tmp_path,TOKEN,agent_gemini_token='agent-private',agent_gemini_model='gemini-test')
    app=create_app(cfg,auto_worker=False)
    with TestClient(app) as client:
        client.headers['Authorization']='Bearer '+TOKEN
        caps=client.get('/api/capabilities').json()
        assert caps['auto_generator']['provider']=='evidence'
        assert caps['agent_integrations']==[{'id':'gemini','model':'gemini-test'}]
        assert 'agent-private' not in json.dumps(caps)
        cid=client.post('/api/conversations',json={'title':'agent integration'}).json()['id']
        route=f'/api/conversations/{cid}'
        user={'content':'Hello model', 'provider':'gemini','idempotency_key':'agent-repeat-123'}
        assert client.post(route+'/agent/replies',json=user).status_code==409
        assert client.patch(route+'/session',json={'agent_active':True}).status_code==200
        assert client.post(route+'/messages',json={'channel':'system','content':'must fail'}).status_code==409
        assert client.post(route+'/sources/actions',json={'action':'INPUT_SOURCE',
            'name':'blocked.md','content':'not permitted'}).status_code==409
        assert client.post(route+'/jobs',json={'operation':'auto_generate'}).status_code==422
        calls=[]
        def reply(connection,system,prompt,*,json_output,transport=None):
            calls.append((connection.provider,connection.name,json_output,prompt))
            assert connection.provider=='gemini'
            assert 'System state' in system
            assert not json_output
            return 'Confirmed Agent reply with no tool action.'
        with patch('systems.model_transport.request_text',reply):
            first=client.post(route+'/agent/replies',json=user)
            assert first.status_code==201,first.text
            assert first.json()['reused'] is False
            second=client.post(route+'/agent/replies',json=user)
            assert second.status_code==201 and second.json()['reused'] is True
            assert len(calls)==1
        messages=client.get(route).json()['messages']
        assert len(messages)==2 and [x['role'] for x in messages]==['user','assistant']
        assert messages[-1]['content']=='Confirmed Agent reply with no tool action.'
        assert client.post(route+'/agent/replies',json={**user,'content':'different'}).status_code==409
        assert client.patch(route+'/session',json={'agent_active':False}).status_code==200
        assert client.post(route+'/messages',json={'channel':'system','content':'System restored'}).status_code==201
        assert client.post(route+'/agent/replies',json={**user,'idempotency_key':'agent-other-234'}).status_code==409
    # Same persistent database, active states and messages stay truthful.
    app2=create_app(cfg,auto_worker=False)
    with TestClient(app2) as c:
        c.headers['Authorization']='Bearer '+TOKEN
        assert len(c.get(route).json()['messages'])==3


def test_provider_failure_produces_no_ghost_agent_messages(tmp_path):
    cfg=Settings(tmp_path,TOKEN,agent_openai_token='server-token',agent_openai_model='model-test')
    with TestClient(create_app(cfg,auto_worker=False)) as c:
        c.headers['Authorization']='Bearer '+TOKEN
        cid=c.post('/api/conversations',json={'title':'fail closed'}).json()['id']
        route=f'/api/conversations/{cid}'
        c.patch(route+'/session',json={'agent_active':True})
        with patch('systems.model_transport.request_text',side_effect=ModelTransportError('secret here')):
            result=c.post(route+'/agent/replies',json={'provider':'openai','content':'test',
                              'idempotency_key':'fail-safe-123'})
        assert result.status_code==502
        assert 'secret here' not in result.text
        assert c.get(route).json()['messages']==[]


def test_agent_retry_provider_identity_cannot_change(tmp_path):
    """A prior response must never be mislabeled as coming from another model."""
    cfg=Settings(tmp_path,TOKEN,
        agent_openai_token='private-one',agent_openai_model='gpt-test',
        agent_gemini_token='private-two',agent_gemini_model='gemini-test')
    with TestClient(create_app(cfg,auto_worker=False)) as client:
        client.headers['Authorization']='Bearer '+TOKEN
        cid=client.post('/api/conversations',json={'title':'provider-key-test'}).json()['id']
        route=f'/api/conversations/{cid}'
        assert client.patch(route+'/session',json={'agent_active':True}).status_code==200
        body={'provider':'openai','content':'same message','idempotency_key':'same-key-777'}
        with patch('systems.model_transport.request_text',return_value='Reply from OpenAI') as mock:
            first=client.post(route+'/agent/replies',json=body)
            assert first.status_code==201
            assert first.json()['provider']=='openai'
            invalid=client.post(route+'/agent/replies',json={**body,'provider':'gemini'})
            assert invalid.status_code==409,invalid.text
            second=client.post(route+'/agent/replies',json=body)
            assert second.status_code==201 and second.json()['reused'] is True
            assert second.json()['provider']=='openai'
            assert mock.call_count==1
        assert len(client.get(route).json()['messages'])==2
