import httpx,json,pytest
from systems.settings import Settings
from systems.auto_generator import AutoGenerator,ProviderError
from capabilities.advisor import prepare

def data():
    src={'id':'a'*32,'name':'r.md','sha256':'f'*64,'version':1,'coverage':'complete','text':'Do not delete facts','limitation':None}
    return [src],prepare([src],'Summarize the selected reference')

def test_model_requires_config(tmp_path):
    with pytest.raises(ValueError):Settings(tmp_path,'x'*30,'model')
    with pytest.raises(ValueError):Settings(tmp_path,'x'*30,'model','http://127.0.0.1:9000','token','model')

def test_optin_provider_contract_and_source_ids(tmp_path):
    sources,check=data();settings=Settings(tmp_path,'x'*30,'model','https://model.example/v1/chat/completions','secret','model')
    def good(request):
        assert request.headers['authorization']=='Bearer secret'
        body=json.loads(request.content)
        assert body['temperature']==0
        supplied=json.loads(body['messages'][1]['content'])
        assert supplied['objective']=='Summarize the selected reference'
        assert supplied['sources'][0]['text']=='Do not delete facts'
        assert 'Rewrite the supplied material' not in body['messages'][0]['content']
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'document':'Source-grounded response retains fact.','source_ids_used':['a'*32]})}}]})
    result=AutoGenerator(settings,httpx.MockTransport(good)).run(sources,check,'Summarize the selected reference')
    assert result.kind=='model_generated' and result.content=='Source-grounded response retains fact.'
    def bad(_request):
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'document':'x','source_ids_used':['b'*32]})}}]})
    with pytest.raises(ProviderError):AutoGenerator(settings,httpx.MockTransport(bad)).run(sources,check,'Summarize the selected reference')
    def malformed(_request):return httpx.Response(200,json={'choices':[{'message':{'content':'NOT JSON'}}]})
    with pytest.raises(ProviderError):AutoGenerator(settings,httpx.MockTransport(malformed)).run(sources,check,'Summarize the selected reference')

def test_blocked_without_provider_request(tmp_path):
    src={'id':'a'*32,'name':'image.png','sha256':'f'*64,'version':1,'coverage':'blocked','text':'','limitation':'No view'}
    settings=Settings(tmp_path,'x'*30,'model','https://model.example/v1/chat/completions','secret','model')
    def must_not(_request):raise AssertionError('Blocked checklist invoked provider')
    with pytest.raises(ProviderError):AutoGenerator(settings,httpx.MockTransport(must_not)).run([src],prepare([src],'Inspect image evidence'),'Inspect image evidence')

def test_provider_enforces_output_size_limit(tmp_path):
    sources,check=data()
    settings=Settings(tmp_path,'x'*30,'model','https://model.example/v1/chat/completions','secret','model')
    def huge(_):return httpx.Response(200,content=b' '*1_000_100)
    with pytest.raises(ProviderError):AutoGenerator(settings,httpx.MockTransport(huge)).run(sources,check,'Summarize the selected reference')
