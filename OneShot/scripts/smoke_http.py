"""Starts a real uvicorn server on a free ephemeral port, uses actual HTTP, closes it."""
import os,socket,sys,subprocess,time,json,tempfile
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1]
def main():
    with tempfile.TemporaryDirectory(prefix='oneshot-http-') as directory:
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
        token='test_only_token_that_is_more_than_24_characters'
        env={**os.environ,'ONESHOT_DATA_DIR':directory,'ONESHOT_API_TOKEN':token,'ONESHOT_PROVIDER':'evidence'}
        p=subprocess.Popen([sys.executable,'-m','uvicorn','systems.api:create_app','--factory',
                            '--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,
                            stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        client=httpx.Client(base_url=f'http://127.0.0.1:{port}',headers={'Authorization':'Bearer '+token},timeout=3)
        try:
            for i in range(80):
                if p.poll() is not None:raise RuntimeError('Server exited before accepting requests')
                try:
                    if client.get('/health').status_code==200:break
                except httpx.HTTPError:time.sleep(.1)
            else:raise RuntimeError('Server did not become healthy')
            assert client.get('/api/capabilities',headers={'Authorization':'Bearer invalid'}).status_code==401
            c=client.post('/api/conversations',json={'title':'HTTP proof'});assert c.status_code==201,c.text;cid=c.json()['id']
            src=client.post(f'/api/conversations/{cid}/sources/actions',json={'action':'INPUT_SOURCE','name':'reference.md','content':'Ground truth source'})
            assert src.status_code==201,src.text;s=src.json()
            objective=client.post(f'/api/conversations/{cid}/messages',json={'channel':'system','content':'Inspect the grounded source evidence.'})
            assert objective.status_code==201,objective.text
            j=client.post(f'/api/conversations/{cid}/jobs',json={'operation':'auto_generate','prompt_message_id':objective.json()['id'],
                   'source_ids':[s['source_id']],'expected_versions':{s['source_id']:1},'idempotency_key':'http-smoke-001'})
            assert j.status_code==202,j.text;jid=j.json()['id']
            for _ in range(70):
                out=client.get(f'/api/conversations/{cid}/jobs/{jid}').json()
                if out['status'] not in ('queued','running'):break
                time.sleep(.1)
            assert out['status']=='completed',out
            art=client.get(f"/api/conversations/{cid}/artifacts/{out['artifact_id']}").json()
            assert art['kind']=='evidence_packet' and 'Ground truth source' in art['content']
            ev=client.get(f'/api/conversations/{cid}/events').json()['events']
            assert any(x['kind']=='job_completed' for x in ev)
            with client.stream('GET',f'/api/conversations/{cid}/events/stream',params={'after':0}) as response:
                assert response.status_code==200,response.status_code
                lines=response.iter_lines()
                first=next(lines)
                assert first.startswith('id: '),first
            graph=client.get(f'/api/conversations/{cid}/jobs/{jid}/trace').json()
            assert all(n['status']=='completed' for n in graph['nodes'])
            # HTTP request not just in-process TestClient; restart recovers persisted result.
            p.terminate();p.wait(timeout=5)
            p=subprocess.Popen([sys.executable,'-m','uvicorn','systems.api:create_app','--factory',
                                '--host','127.0.0.1','--port',str(port)],cwd=ROOT,env=env,
                                stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
            for _ in range(80):
                if p.poll() is not None:raise RuntimeError('Restart process exited')
                try:
                    if client.get('/health').status_code==200:break
                except httpx.HTTPError:time.sleep(.1)
            assert client.get(f'/api/conversations/{cid}/jobs/{jid}').json()['status']=='completed'
            # Background evaluation is enabled by default and fires asynchronously —
            # restart recovery must not LOSE events, but new background_* events are
            # permitted and expected.
            post_events = client.get(f'/api/conversations/{cid}/events').json()['events']
            assert len(post_events) >= len(ev), 'restart must not lose events'
            pre_kinds = [e['kind'] for e in ev]
            post_kinds = [e['kind'] for e in post_events[:len(ev)]]
            assert pre_kinds == post_kinds, 'restart must preserve pre-restart event order'
            print(json.dumps({'http_status':'passed','job_status':out['status'], 'events':len(ev),'restart':'passed','sse':'passed'},sort_keys=True))
        finally:
            client.close()
            if p.poll() is None:
                p.terminate()
                try:p.wait(timeout=5)
                except subprocess.TimeoutExpired:p.kill();p.wait()
if __name__=='__main__':main()
