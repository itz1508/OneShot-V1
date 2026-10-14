"""Actual Chromium -> built frontend -> Uvicorn -> SQLite -> Worker -> Apply -> restart.

Run: python -m tests.e2e_browser (requires Playwright + Chromium installed).
This does not claim unavailable image/PDF, external AI semantics, or Docker verification.
"""
import json, os, socket, subprocess, sys, tempfile, time, shutil
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'e2e_api_token_please_replace_outside_testing'
PASSWORD = 'e2e_browser_password_private_for_testing'

def port_available():
    with socket.socket() as s:
        s.bind(('127.0.0.1',0))
        return s.getsockname()[1]

def launch(port, data):
    env={**os.environ,
         'ONESHOT_API_TOKEN':TOKEN,
         'ONESHOT_BROWSER_PASSWORD':PASSWORD,
         'ONESHOT_PROVIDER':'evidence',
         'ONESHOT_DATA_DIR':str(data),
         'ONESHOT_FRONTEND_DIST':str(ROOT/'frontend'/'dist')}
    return subprocess.Popen([sys.executable,'-m','uvicorn','systems.api:create_app','--factory',
        '--host','127.0.0.1','--port',str(port),'--workers','1'],cwd=ROOT,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)

def ready(url,p):
    for _ in range(70):
        if p.poll() is not None:
            raise AssertionError('Uvicorn stopped during startup: '+p.stderr.read().decode()[-2000:])
        try:
            if httpx.get(url+'/health',timeout=1).status_code==200:return
        except httpx.HTTPError:pass
        time.sleep(.1)
    raise AssertionError('Uvicorn startup timed out')

def stop(p):
    if p.poll() is None:
        p.terminate()
        try:p.wait(timeout=7)
        except subprocess.TimeoutExpired:p.kill();p.wait(timeout=7)

def ui_api(page, path, method='GET', payload=None):
    return page.evaluate('''async ({path,method,payload})=>{
      const session=await (await fetch('/auth/session')).json();
      const headers={'X-Oneshot-CSRF':session.csrf};
      if(payload!==null)headers['Content-Type']='application/json';
      const response=await fetch(path,{method,headers,credentials:'same-origin',body:payload===null?undefined:JSON.stringify(payload)});
      let data;try{data=await response.json()}catch{data=null}
      return {status:response.status,data};
    }''', {'path':path,'method':method,'payload':payload})

def wait_for_boot(page, timeout_ms=10000):
    # Deterministic post-boot gate: boot() in frontend/app.js awaits createConversation() and
    # writes sessionStorage['oneshot_conversation_id'] BEFORE updateConnection() sets the
    # #connection-state text to 'System connected'. Waiting on that text closes the race the
    # earlier `#system-input visible` wait left open (the input becomes visible before boot's
    # awaited promises resolve). CSP forbids 'unsafe-eval', so no wait_for_function.
    page.locator('#connection-state').wait_for(state='attached', timeout=timeout_ms)
    page.locator('#connection-state:text-is("System connected")').wait_for(state='attached', timeout=timeout_ms)

def run():
    assert (ROOT/'frontend'/'dist'/'index.html').is_file(),'Build frontend first: cd frontend && npm run build'
    with tempfile.TemporaryDirectory(prefix='oneshot-real-browser-') as temporary:
        data=Path(temporary)/'data';port=port_available();url=f'http://127.0.0.1:{port}'
        p=launch(port,data)
        try:
            ready(url,p)
            assert httpx.get(url+'/api/capabilities').status_code==401
            with sync_playwright() as browser_driver:
                chromium_path = os.getenv('ONESHOT_E2E_CHROMIUM') or shutil.which('chromium')
                browser=browser_driver.chromium.launch(
                    executable_path=chromium_path or None,headless=True,
                    args=['--no-sandbox','--disable-dev-shm-usage'] if sys.platform.startswith('linux') else [])
                try:
                    page=browser.new_page(viewport={'width':1440,'height':900})
                    errors=[]
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(url,wait_until='domcontentloaded')
                    page.locator('#login-view').wait_for(state='visible')
                    assert page.locator('#workspace').is_hidden()
                    page.locator('#browser-password').fill('wrong-password-please-reject')
                    page.locator('#login-submit').click()
                    page.locator('#login-error').get_by_text('401',exact=False).wait_for()
                    assert page.locator('#workspace').is_hidden()
                    page.locator('#browser-password').fill(PASSWORD)
                    page.locator('#login-submit').click()
                    page.locator('#system-input').wait_for(state='visible')
                    page.get_by_text('System connected',exact=False).first.wait_for()
                    assert page.locator('#agent-selector').is_disabled()
                    page.locator('#system-input').fill('System remains primary without Agents')
                    page.locator('#send-system').click()
                    page.get_by_text('System remains primary without Agents').first.wait_for()
                    assert page.locator('#processing-objective').inner_text()=='System remains primary without Agents'
                    cid=page.evaluate('sessionStorage.getItem("oneshot_conversation_id")')
                    assert cid and len(cid)==32
                    page.locator('#attach-toggle').click()
                    page.locator('#paste-toggle').click()
                    page.locator('#paste-name').fill('requirements.md')
                    page.locator('#paste-content').fill('Preserve original evidence. Never mutate before Apply.')
                    page.locator('#paste-form button[type="submit"]').click()
                    page.get_by_role('button',name='requirements.md',exact=True).wait_for()
                    page.get_by_label('Select requirements.md for processing').check()
                    assert page.locator('#processing-objective').inner_text()=='System remains primary without Agents'
                    assert page.locator('#start-button').is_enabled()
                    page.locator('#start-button').click()
                    # Start opens a real review modal; no work is accepted until
                    # the user confirms the frozen objective and selected scope.
                    page.locator('#start-review-dialog').wait_for(state='visible')
                    page.locator('#start-review-confirm').click()
                    page.locator('#job-summary').get_by_text('completed',exact=False).wait_for(timeout=20000)
                    page.locator('#background-history').get_by_text('completed',exact=False).wait_for(timeout=15000)
                    bg=ui_api(page,f'/api/conversations/{cid}/background')
                    assert bg['status']==200 and bg['data']['summary']['states'].get('completed',0)>=1,bg
                    assert bg['data']['learning']['model_promoted'] is False
                    page.locator('#open-result').click()
                    page.get_by_text('# Prepared source evidence',exact=False).wait_for(timeout=7000)
                    content=page.locator('#artifact-content').inner_text()
                    assert 'Preserve original evidence' in content and 'evidence packet' in content
                    # Explicitly verify real executed worker events and recorded artifact.
                    ev=ui_api(page,f'/api/conversations/{cid}/events').get('data',{}).get('events',[])
                    assert any(x['kind']=='node_started' for x in ev)
                    complete=next(x for x in reversed(ev) if x['kind']=='job_completed')
                    artifact=complete['payload']['artifact_id']
                    jid=complete['job_id']
                    assert artifact
                    trace=ui_api(page,f'/api/conversations/{cid}/jobs/{jid}/trace')
                    assert trace['status']==200 and all(n['status']=='completed' for n in trace['data']['nodes'])
                    # An unavailable Agent must NOT disable System or fabricate a reply.
                    bad=ui_api(page,f'/api/conversations/{cid}/session','PATCH',{'agent_active':True})
                    assert bad['status']==409,bad
                    bad=ui_api(page,f'/api/conversations/{cid}/messages','POST',{'channel':'agent','content':'Fake Agent?'})
                    assert bad['status']==409,bad
                    # Without a CSRF header the live server must deny a browser write.
                    no_csrf=page.evaluate('''async ()=> (await fetch('/api/conversations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:'unauthorized'})})).status''')
                    assert no_csrf==403,no_csrf
                    # Source draft is separate from immutable source bytes.
                    page.get_by_role('button',name='requirements.md',exact=True).click()
                    page.locator('#editor-input').wait_for(state='visible')
                    page.locator('#editor-input').fill('Changed draft only; original still preserved.')
                    page.locator('#save-draft').click()
                    page.get_by_text('Draft revision 1 saved').wait_for()
                    srcs=ui_api(page,f'/api/conversations/{cid}/sources')['data']
                    assert len(srcs)==1
                    original=page.evaluate('''async args=>{
                      const b=await (await fetch(args)).text();return b;
                    }''',f'/api/conversations/{cid}/sources/{srcs[0]["id"]}/content')
                    assert original=='Preserve original evidence. Never mutate before Apply.'
                    # The actual UI must perform the two-step authenticated Apply and
                    # report a verified persisted readback, not an internal fetch helper.
                    page.locator('#open-result').click()
                    page.locator('#apply-controls').wait_for(state='visible')
                    page.locator('#apply-destination').fill('notes/browser_result.md')
                    page.locator('#apply-prepare').click()
                    page.locator('#apply-dialog').wait_for(state='visible')
                    assert not (data/'applied'/'notes'/'browser_result.md').exists()
                    page.locator('#apply-confirm').click()
                    page.locator('#apply-status').get_by_text('Verified applied result',exact=False).wait_for()
                    page.locator('#apply-diff').wait_for(state='visible')
                    assert '+++ applied' in page.locator('#apply-diff').inner_text()
                    applied=data/'applied'/'notes'/'browser_result.md'
                    assert applied.is_file() and 'Preserve original evidence' in applied.read_text()
                    # Confirm browser-only auth cannot be stolen into fake success by restart.
                    page.screenshot(path=str(Path(temporary)/'browser_e2e_screenshot.png'),full_page=True)
                    stop(p)
                    p=launch(port,data);ready(url,p)
                    page.reload(wait_until='domcontentloaded')
                    page.locator('#login-view').wait_for(state='visible')
                    page.locator('#browser-password').fill(PASSWORD)
                    page.locator('#login-submit').click()
                    page.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page)
                    restored=ui_api(page,f'/api/conversations/{cid}')
                    assert restored['status']==200,restored
                    assert 'System remains primary' in str(restored['data']['messages'])
                    after_restart=ui_api(page,f'/api/conversations/{cid}/background')
                    assert after_restart['status']==200 and after_restart['data']['summary']['states'].get('completed',0)>=1
                    assert applied.read_text()==content
                    assert not errors,errors
                    print(json.dumps({'result':'E2E_SLICE_OBSERVED','browser':'Chromium',
                      'server':'real uvicorn','frontend':'built assets',
                      'authentication':'cookie + csrf enforced','job_id':jid,
                      'actual_worker_events':sum(x['kind']=='node_started' for x in ev),
                      'artifact_kind':'evidence_packet','apply_verified':True,
                      'restart_persistence':True,'uninstalled_agent_blocked':True,
                      'python_version':sys.version.split()[0]},sort_keys=True))
                finally:browser.close()
        finally:stop(p)

if __name__=='__main__':run()
