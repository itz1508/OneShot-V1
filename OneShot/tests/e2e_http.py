"""Real HTTP integration diagnostic. Not a substitute for Chromium browser E2E."""
from pathlib import Path
import hashlib, json, os, socket, subprocess, sys, tempfile, time
import httpx

ROOT=Path(__file__).resolve().parents[1]
TOKEN='test-only-long-bearer-token-for-e2e'
PASSWORD='test-only-browser-password-e2e'

def serve(port,data):
    env={**os.environ,'ONESHOT_API_TOKEN':TOKEN,'ONESHOT_BROWSER_PASSWORD':PASSWORD,
         'ONESHOT_PROVIDER':'evidence','ONESHOT_DATA_DIR':str(data),
         'ONESHOT_FRONTEND_DIST':str(ROOT/'frontend'/'dist')}
    return subprocess.Popen([sys.executable,'-m','uvicorn','systems.api:create_app','--factory',
        '--host','127.0.0.1','--port',str(port),'--workers','1'],cwd=ROOT,env=env,
        stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)

def check_ready(p,url):
    for _ in range(100):
        if p.poll() is not None:raise RuntimeError('Uvicorn exited: '+p.stderr.read().decode()[-2000:])
        try:
            if httpx.get(url+'/health',timeout=1).status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(.1)
    raise RuntimeError('Uvicorn readiness timeout')

def stop(p):
    if p.poll() is None:
        p.terminate()
        try:p.wait(timeout=7)
        except subprocess.TimeoutExpired:p.kill();p.wait(timeout=7)

def run():
    with tempfile.TemporaryDirectory(prefix='oneshot-full-http-') as t:
        root=Path(t)/'data'
        with socket.socket() as s:
            s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        url=f'http://127.0.0.1:{port}';p=serve(port,root)
        try:
            check_ready(p,url)
            with httpx.Client(base_url=url,timeout=4) as c:
                resp=c.get('/');assert resp.status_code==200 and 'login-view' in resp.text
                for file in ('/app.js','/api/client.js','/styles.css','/workspace.js'):
                    assert c.get(file).status_code==200,file
                assert c.get('/api/capabilities').status_code==401
                assert c.post('/auth/login',json={'password':'bad-browser-password'}).status_code==401
                login=c.post('/auth/login',json={'password':PASSWORD});assert login.status_code==200,login.text
                token=login.json()['csrf']
                assert c.get('/auth/session').json()['authenticated']
                assert c.post('/api/conversations',json={'title':'no csrf'}).status_code==403
                c.headers['X-Oneshot-CSRF']=token
                created=c.post('/api/conversations',json={'title':'Real HTTP System E2E'});assert created.status_code==201,created.text
                cid=created.json()['id']
                message=c.post(f'/api/conversations/{cid}/messages',json={'channel':'system','content':'System independent'});
                assert message.status_code==201,message.text
                assert c.patch(f'/api/conversations/{cid}/session',json={'agent_active':True}).status_code==409
                assert c.post(f'/api/conversations/{cid}/messages',json={'channel':'agent','content':'fake agent'}).status_code==409
                src=c.post(f'/api/conversations/{cid}/sources/actions',json={'action':'INPUT_SOURCE',
                        'name':'rules.md','content':'Preserve evidence. Do not alter original.'})
                assert src.status_code==201,src.text;sid=src.json()['source_id']
                draft=c.post(f'/api/conversations/{cid}/drafts',json={'source_id':sid,'content':'Draft only'});
                assert draft.status_code==201,draft.text
                assert c.get(f'/api/conversations/{cid}/sources/{sid}/content').content==b'Preserve evidence. Do not alter original.'
                objective=c.post(f'/api/conversations/{cid}/messages',json={'channel':'system','content':'Review evidence and preserve source constraints.'})
                assert objective.status_code==201,objective.text
                job=c.post(f'/api/conversations/{cid}/jobs',json={'operation':'auto_generate','prompt_message_id':objective.json()['id'],'source_ids':[sid],
                            'expected_versions':{sid:1},'idempotency_key':'http-full-e2e-01'})
                assert job.status_code==202,job.text;jid=job.json()['id']
                result=None
                for _ in range(120):
                    result=c.get(f'/api/conversations/{cid}/jobs/{jid}').json()
                    if result['status'] not in ('queued','running'):break
                    time.sleep(.1)
                assert result['status']=='completed',result
                background_result=None
                for _ in range(80):
                    background_result=c.get(f'/api/conversations/{cid}/background').json()
                    if background_result['summary']['states'].get('completed',0)>=1:break
                    time.sleep(.1)
                assert background_result['summary']['states'].get('completed',0)>=1,background_result
                assert background_result['summary']['verified_semantic_labels']==0
                aid=result['artifact_id'];artifact=c.get(f'/api/conversations/{cid}/artifacts/{aid}').json()
                assert artifact['kind']=='evidence_packet' and 'Preserve evidence' in artifact['content']
                assert 'Review evidence and preserve source constraints.' in artifact['content']
                assert 'L1: Preserve evidence. Do not alter original.' in artifact['content']
                assert result['prompt_message_id']==objective.json()['id']
                assert c.post(f'/api/conversations/{cid}/jobs',json={
                    'operation':'auto_generate','source_ids':[sid],
                    'expected_versions':{sid:1},'idempotency_key':'missing-objective'}).status_code==422
                events=c.get(f'/api/conversations/{cid}/events').json()['events']
                assert any(x['kind']=='node_started' for x in events)
                assert any(x['kind']=='job_completed' and x['job_id']==jid for x in events)
                with c.stream('GET',f'/api/conversations/{cid}/events/stream',params={'after':0}) as r:
                    assert r.status_code==200
                    assert next(r.iter_lines()).startswith('id: ')
                observed=c.get(f'/api/conversations/{cid}/events').json()['events']
                completed_bg=[x for x in observed if x['kind']=='background_completed']
                assert completed_bg and completed_bg[-1]['job_id']==jid
                prior=completed_bg[-1]['seq']-1
                with c.stream('GET',f'/api/conversations/{cid}/events/stream',
                              headers={'Last-Event-ID':str(prior)}) as response:
                    assert response.status_code==200
                    assert next(response.iter_lines())=='id: '+str(completed_bg[-1]['seq'])
                trace=c.get(f'/api/conversations/{cid}/jobs/{jid}/trace').json()
                assert all(n['status']=='completed' for n in trace['nodes'])
                prepare=c.post(f'/api/conversations/{cid}/apply/prepare',json={'artifact_id':aid,'destination':'notes/proven.md'});
                assert prepare.status_code==200,prepare.text
                path=root/'applied'/'notes'/'proven.md';assert not path.exists()
                confirm=c.post(f'/api/conversations/{cid}/apply/confirm',json={
                    'confirmation_token':prepare.json()['confirmation_token'],'confirm_apply':True})
                assert confirm.status_code==200 and confirm.json()['verified'],confirm.text
                assert hashlib.sha256(path.read_bytes()).hexdigest()==confirm.json()['result_sha256']
                assert c.post(f'/api/conversations/{cid}/apply/confirm',json={
                    'confirmation_token':prepare.json()['confirmation_token'],'confirm_apply':True}).status_code==403
                stop(p);p=serve(port,root);check_ready(p,url)
                assert c.get('/auth/session').status_code==401  # in-memory browser sessions expire on restart
                assert c.get(f'/api/conversations/{cid}').status_code==401
                login=c.post('/auth/login',json={'password':PASSWORD});assert login.status_code==200
                c.headers['X-Oneshot-CSRF']=login.json()['csrf']
                restored=c.get(f'/api/conversations/{cid}');assert restored.status_code==200
                assert 'System independent' in str(restored.json()['messages'])
                assert c.get(f'/api/conversations/{cid}/jobs/{jid}').json()['status']=='completed'
                assert path.is_file()
                assert c.get(f'/api/conversations/{cid}/background').json()['summary']['states'].get('completed',0)>=1
                assert c.post('/auth/logout').status_code==200
                assert c.get('/api/capabilities').status_code==401
                print(json.dumps({'diagnostic':'REAL_HTTP_INTEGRATION','http':'observed','frontend_assets':'served',
                    'auth':'cookie + csrf','sse':'observed','source':'immutable','job':'real worker',
                    'artifact':'evidence_packet','apply':'verified readback','restart':'durable state',
                    'python_version':sys.version.split()[0]},sort_keys=True))
        finally:stop(p)

if __name__=='__main__':run()
