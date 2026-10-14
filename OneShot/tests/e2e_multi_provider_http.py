"""Real Uvicorn + local model HTTP protocol integration diagnostic.

Does NOT validate model semantics, a live external model, or Chromium.
"""
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
TOKEN='integration-test-token-long-enough-for-server'
PASSWORD='integration-test-browser-password'


class LocalOllamaProtocol(BaseHTTPRequestHandler):
    calls=[]
    def log_message(self,*args):pass
    def do_POST(self):
        assert self.path=='/api/chat'
        b=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.calls.append(b)
        if b.get('format')=='json':
            user=json.loads(b['messages'][-1]['content'])
            ids=[s['id'] for s in user['sources']]
            if 'single key summary' in b['messages'][0]['content']:
                answer=json.dumps({'summary':'Model protocol summary for '+user['objective']})
            else:
                answer=json.dumps({'document':'Recorded local protocol response for '+user['objective'],
                                   'source_ids_used':ids})
        else:
            prompt=json.loads(b['messages'][-1]['content'])
            answer='Agent local protocol response: '+prompt['current_user_message']
        payload=json.dumps({'model':b['model'],'done':True,
                            'message':{'role':'assistant','content':answer}}).encode()
        self.send_response(200)
        self.send_header('Content-Type','application/json')
        self.send_header('Content-Length',str(len(payload)))
        self.end_headers();self.wfile.write(payload)


def free_port():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]


def await_ready(p,origin):
    for _ in range(80):
        if p.poll() is not None:
            raise RuntimeError('Uvicorn exited: '+p.stderr.read().decode()[-1600:])
        try:
            if httpx.get(origin+'/health',timeout=.8).status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(.1)
    raise RuntimeError('server startup timeout')


def run():
    with tempfile.TemporaryDirectory(prefix='oneshot-model-http-') as temp:
        root=Path(temp)/'data'
        model=ThreadingHTTPServer(('127.0.0.1',0),LocalOllamaProtocol)
        daemon=threading.Thread(target=model.serve_forever,daemon=True)
        daemon.start()
        endpoint=f'http://127.0.0.1:{model.server_port}/api/chat'
        port=free_port();url=f'http://127.0.0.1:{port}'
        env={**os.environ,'ONESHOT_API_TOKEN':TOKEN,'ONESHOT_BROWSER_PASSWORD':PASSWORD,
             'ONESHOT_PROVIDER':'ollama','ONESHOT_MODEL_NAME':'local-contract-model',
             'ONESHOT_MODEL_ENDPOINT':endpoint,'ONESHOT_AGENT_OLLAMA_MODEL':'local-contract-model',
             'ONESHOT_AGENT_OLLAMA_ENDPOINT':endpoint,'ONESHOT_DATA_DIR':str(root),
             'ONESHOT_FRONTEND_DIST':str(ROOT/'frontend'/'dist')}
        def launch():
            return subprocess.Popen([sys.executable,'-m','uvicorn','systems.api:create_app','--factory',
                '--host','127.0.0.1','--port',str(port),'--workers','1'],env=env,cwd=ROOT,
                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        def stop(p):
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=8)
                except subprocess.TimeoutExpired:p.kill();p.wait()
        server=launch()
        try:
            await_ready(server,url)
            with httpx.Client(base_url=url,timeout=8) as c:
                assert c.get('/').status_code==200
                assert c.get('/api/capabilities').status_code==401
                login=c.post('/auth/login',json={'password':PASSWORD});assert login.status_code==200
                csrf=login.json()['csrf']
                assert c.post('/api/conversations',json={'title':'No CSRF'}).status_code==403
                c.headers['X-Oneshot-CSRF']=csrf
                cap=c.get('/api/capabilities').json()
                assert cap['auto_generator']['provider']=='ollama',cap
                assert cap['agent_integrations'][0]['id']=='ollama',cap
                cid=c.post('/api/conversations',json={'title':'multi-provider E2E'}).json()['id']
                route=f'/api/conversations/{cid}'
                assert c.patch(route+'/session',json={'agent_active':True}).status_code==200
                assert c.post(route+'/messages',json={'channel':'system','content':'Blocked during Agent'}).status_code==409
                agent=c.post(route+'/agent/replies',json={'provider':'ollama','content':'test private agent lane',
                                         'idempotency_key':'local-agent-111'})
                assert agent.status_code==201,agent.text
                assert agent.json()['content']=='Agent local protocol response: test private agent lane'
                repeat=c.post(route+'/agent/replies',json={'provider':'ollama','content':'test private agent lane',
                                           'idempotency_key':'local-agent-111'})
                assert repeat.status_code==201 and repeat.json()['reused']
                assert c.patch(route+'/session',json={'agent_active':False}).status_code==200
                objective=c.post(route+'/messages',json={'channel':'system',
                                 'content':'Summarize the selected original without changing it.'})
                assert objective.status_code==201,objective.text
                sid=c.post(route+'/sources/actions',json={'action':'INPUT_SOURCE',
                    'name':'terms.md','content':'Section 1: Preserve the original source evidence.'}).json()['source_id']
                job=c.post(route+'/jobs',json={'operation':'auto_generate',
                    'prompt_message_id':objective.json()['id'],'source_ids':[sid],
                    'expected_versions':{sid:1},'idempotency_key':'provider-e2e-001'})
                assert job.status_code==202,job.text
                jid=job.json()['id']
                result=None
                for _ in range(200):
                    result=c.get(route+'/jobs/'+jid).json()
                    if result['status'] not in ('queued','running'):break
                    time.sleep(.1)
                assert result['status']=='completed',result
                aid=result['artifact_id'];artifact=c.get(route+'/artifacts/'+aid).json()
                assert artifact['kind']=='model_generated',artifact
                assert artifact['content']=='Recorded local protocol response for Summarize the selected original without changing it.'
                assert artifact['source_ids']==[sid]
                assert c.get(route+'/sources/'+sid+'/content').text=='Section 1: Preserve the original source evidence.'
                trace=c.get(route+'/jobs/'+jid+'/trace').json()
                assert all(x['status']=='completed' for x in trace['nodes'])
                events=c.get(route+'/events').json()['events']
                assert any(x['kind']=='job_completed' for x in events)
                assert any(x['kind']=='agent_reply_saved' for x in events)
                assert c.post(route+'/apply/prepare',json={'artifact_id':aid,'destination':'../bad.md'}).status_code==422
                proposed=c.post(route+'/apply/prepare',json={'artifact_id':aid,'destination':'notes/model-result.md'})
                assert proposed.status_code==200,proposed.text
                assert not (root/'applied'/'notes'/'model-result.md').exists()
                applied=c.post(route+'/apply/confirm',json={'confirmation_token':proposed.json()['confirmation_token'],
                                                              'confirm_apply':True})
                assert applied.status_code==200 and applied.json()['verified'],applied.text
                assert (root/'applied'/'notes'/'model-result.md').read_text()==artifact['content']
                # Model summary runs through the *actual* HTTP job and event
                # lifecycle and exports only the one-field output.json contract.
                summary_job=c.post(route+'/jobs',json={'operation':'summarize',
                    'prompt_message_id':objective.json()['id'],'source_ids':[sid],
                    'expected_versions':{sid:1},'idempotency_key':'provider-summary-001'})
                assert summary_job.status_code==202,summary_job.text
                summary_jid=summary_job.json()['id']
                for _ in range(200):
                    state=c.get(route+'/jobs/'+summary_jid).json()
                    if state['status'] not in ('queued','running'):break
                    time.sleep(.1)
                assert state['status']=='completed',state
                output=c.get(route+'/artifacts/'+state['artifact_id']+'/summary')
                assert output.status_code==200 and set(output.json())=={'summary'},output.text
                assert 'output.json' in output.headers['content-disposition']
                assert 'Model protocol summary' in output.json()['summary']
                stop(server);server=launch();await_ready(server,url)
                assert c.get('/auth/session').status_code==401
                assert c.get(route).status_code==401
                login=c.post('/auth/login',json={'password':PASSWORD});assert login.status_code==200
                c.headers['X-Oneshot-CSRF']=login.json()['csrf']
                restored=c.get(route).json()
                assert len(restored['messages'])==3
                assert c.get(route+'/artifacts/'+aid).json()['content']==artifact['content']
                assert (root/'applied'/'notes'/'model-result.md').read_text()==artifact['content']
                assert len(LocalOllamaProtocol.calls)==3,LocalOllamaProtocol.calls
                print(json.dumps({'status':'REAL_HTTP_WITH_LOCAL_PROTOCOL_STUB',
                    'browser_e2e':False,'external_model_semantics_verified':False,
                    'agent_messages':2,'worker_completed':True,'artifact_kind':'model_generated',
                    'stored_events':len(events),'restart_persistence':True,'apply_readback':True,
                    'protocol_requests':len(LocalOllamaProtocol.calls)},sort_keys=True))
        finally:
            stop(server)
            model.shutdown();model.server_close()

if __name__=='__main__':run()
