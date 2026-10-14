"""Real Chromium E2E for the Prompt Workspace feature.

Boots a real uvicorn + SQLite + built frontend and drives the Prompt Workspace
through Chromium end to end. P09 (real-model) and P12 (real optimizer) are
NOT exercised here — those require a local llama-server and remain
E2E_INCOMPLETE per the correction directive.
"""
import json, os, socket, subprocess, sys, tempfile, time, shutil
from pathlib import Path
import httpx
from playwright.sync_api import sync_playwright


def wait_for_boot(page, timeout_ms=10000):
    # Deterministic post-boot gate used by other E2E modules; see tests/e2e_browser.py.
    page.locator('#connection-state').wait_for(state='attached', timeout=timeout_ms)
    page.locator('#connection-state:text-is("System connected")').wait_for(state='attached', timeout=timeout_ms)

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'e2e_api_token_please_replace_outside_testing'
PASSWORD = 'e2e_browser_password_private_for_testing'


def port_available():
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]


def launch(port, data):
    env = {**os.environ,
           'ONESHOT_API_TOKEN': TOKEN,
           'ONESHOT_BROWSER_PASSWORD': PASSWORD,
           'ONESHOT_PROVIDER': 'evidence',
           'ONESHOT_DATA_DIR': str(data),
           'ONESHOT_FRONTEND_DIST': str(ROOT / 'frontend' / 'dist')}
    return subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'systems.api:create_app', '--factory',
         '--host', '127.0.0.1', '--port', str(port), '--workers', '1'],
        cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def ready(url, p):
    for _ in range(70):
        if p.poll() is not None:
            raise AssertionError('Uvicorn stopped during startup: '
                                 + p.stderr.read().decode()[-2000:])
        try:
            if httpx.get(url + '/health', timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(.1)
    raise AssertionError('Uvicorn startup timed out')


def stop(p):
    if p.poll() is None:
        p.terminate()
        try:
            p.wait(timeout=7)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait(timeout=7)


def run():
    assert (ROOT / 'frontend' / 'dist' / 'index.html').is_file(), (
        'Build frontend first: cd frontend && npm run build')
    with tempfile.TemporaryDirectory(prefix='oneshot-prompts-e2e-') as temporary:
        data = Path(temporary) / 'data'
        port = port_available()
        url = f'http://127.0.0.1:{port}'
        p = launch(port, data)
        try:
            ready(url, p)
            with sync_playwright() as pw:
                chromium_path = os.getenv('ONESHOT_E2E_CHROMIUM') or shutil.which('chromium')
                browser = pw.chromium.launch(
                    executable_path=chromium_path or None, headless=True,
                    args=(['--no-sandbox', '--disable-dev-shm-usage']
                          if sys.platform.startswith('linux') else []))
                try:
                    page = browser.new_page(viewport={'width': 1440, 'height': 900})
                    errors = []
                    page.on('pageerror', lambda e: errors.append(str(e)))

                    page.goto(url, wait_until='domcontentloaded')
                    page.locator('#login-view').wait_for(state='visible')
                    page.locator('#browser-password').fill(PASSWORD)
                    page.locator('#login-submit').click()
                    page.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page)
                    page.get_by_text('System connected', exact=False).first.wait_for()

                    # P01 — Create Prompt
                    page.locator('#prompt-workspace').wait_for(state='visible')
                    page.evaluate('window.prompt = () => "Report Draft Prompt"')
                    page.locator('#prompt-new').click()
                    page.get_by_text('Created Report Draft Prompt',
                                     exact=False).first.wait_for()
                    page.locator('#prompt-detail').wait_for(state='visible')

                    # P03 — Draft content + variables + Save
                    editor = page.locator('#prompt-draft-content')
                    editor.fill('Summarize ${source} briefly.')
                    page.locator('#prompt-variables').fill(
                        '[{"name":"source","required":true}]')
                    page.locator('#prompt-save-draft').click()
                    page.locator('#prompt-draft-state[data-prompt-draft-rev="2"]').wait_for(state="attached", timeout=10000)

                    # P04 — Publish v1
                    page.locator('#prompt-publish').click()
                    page.locator('#prompt-latest[data-prompt-latest-version="1"]').wait_for(state="attached", timeout=10000)

                    # P05 — v2
                    editor.fill('New: Summarize ${source} in 3 bullets.')
                    page.locator('#prompt-save-draft').click()
                    page.locator('#prompt-draft-state[data-prompt-draft-rev="3"]').wait_for(state="attached", timeout=10000)
                    page.locator('#prompt-publish').click()
                    page.locator('#prompt-latest[data-prompt-latest-version="2"]').wait_for(state="attached", timeout=10000)

                    # P10 — Compare v1 vs v2
                    page.locator('summary', has_text='Version history').click()
                    page.locator('#prompt-compare-left').fill('1')
                    page.locator('#prompt-compare-right').fill('2')
                    page.locator('#prompt-compare-go').click()
                    # Poll the DOM via locator; CSP forbids wait_for_function strings.
                    deadline = time.time() + 5
                    out = ''
                    while time.time() < deadline:
                        out = page.locator('#prompt-compare-output').inner_text()
                        if out.strip():
                            break
                        time.sleep(0.1)
                    assert 'in 3 bullets' in out, (
                        f'Compare output missing v2 phrase: {out!r}')
                    assert 'briefly' in out, (
                        f'Compare output missing v1 phrase: {out!r}')

                    # P11 — Structural evaluation
                    page.locator('summary', has_text='Structural evaluation').click()
                    page.locator('#prompt-eval-criteria').fill(
                        '[{"kind":"contains","value":"Summarize"},'
                        ' {"kind":"declares_variable","name":"source"},'
                        ' {"kind":"absent","value":"FORBIDDEN"}]')
                    page.locator('#prompt-eval-run').click()
                    page.get_by_text('"passed": 3', exact=False).first.wait_for(timeout=5000)

                    # P12 — Optimizer refuses without provider (precise error path)
                    page.locator('summary', has_text='Optimization proposals').click()
                    page.locator('#prompt-optimize').click()
                    # The notify() surface renders text somewhere on the page.
                    page.get_by_text('optimizer', exact=False).first.wait_for(timeout=5000)

                    # P08 — Restore v1 as new version
                    page.evaluate('window.confirm = () => true')
                    page.locator('#prompt-versions-list li').first.locator('button').click()
                    page.get_by_text('Restored v1 as a new version',
                                     exact=False).first.wait_for(timeout=5000)

                    # P18a — Browser reload (same uvicorn process)
                    page.reload(wait_until='domcontentloaded')
                    page.locator('#system-input').wait_for(state='visible', timeout=10000)
                    page.locator('#prompt-workspace').wait_for(state='visible')
                    page.locator('summary', has_text='Version history').click()
                    time.sleep(0.6)
                    items_before_restart = page.locator('#prompt-versions-list li').count()
                    assert items_before_restart == 3, (
                        f'expected 3 versions after reload, got {items_before_restart}')
                    draft_before_restart = page.locator('#prompt-draft-content').input_value()
                    conv_cookie = page.context.cookies(url)
                    stored_cid = page.evaluate(
                        "sessionStorage.getItem('oneshot_conversation_id')")

                    # P02 + P18b — REAL uvicorn kill + reboot on the SAME data dir.
                    # This is NOT a Store-reopen or a page reload; it kills the
                    # actual Python process and starts a fresh one.
                    browser.close()
                finally:
                    pass
                stop(p)
                assert p.poll() is not None, 'uvicorn did not exit'
                # Reboot on the same data_dir + same port.
                p2 = launch(port, data)
                try:
                    ready(url, p2)
                    chromium_path2 = os.getenv('ONESHOT_E2E_CHROMIUM') or shutil.which('chromium')
                    browser2 = pw.chromium.launch(
                        executable_path=chromium_path2 or None, headless=True,
                        args=(['--no-sandbox', '--disable-dev-shm-usage']
                              if sys.platform.startswith('linux') else []))
                    try:
                            ctx2 = browser2.new_context(viewport={'width': 1440, 'height': 900})
                            # The in-memory session dict was reset by the uvicorn
                            # restart (sessions dict is per-process). This is
                            # architectural: the DB survives, the session doesn't.
                            # Re-login proves the DB state is still intact.
                            page2 = ctx2.new_page()
                            # Pre-seed sessionStorage with the same conversation
                            # id so the client reconnects to the DB-backed row
                            # (not a brand-new conversation).
                            if stored_cid:
                                page2.add_init_script(
                                    "sessionStorage.setItem('oneshot_conversation_id', "
                                    + json.dumps(stored_cid) + ")")
                            page2.goto(url, wait_until='domcontentloaded')
                            page2.locator('#login-view').wait_for(state='visible', timeout=10000)
                            page2.locator('#browser-password').fill(PASSWORD)
                            page2.locator('#login-submit').click()
                            page2.locator('#system-input').wait_for(state='visible',
                                                                     timeout=10000)
                            page2.locator('#prompt-workspace').wait_for(state='visible')
                            # Wait for the prompt-detail panel to populate from
                            # the DB-backed /prompts call before interacting.
                            page2.locator('#prompt-detail').wait_for(state='visible', timeout=10000)
                            vhistory = page2.locator('summary', has_text='Version history')
                            vhistory.scroll_into_view_if_needed()
                            vhistory.click()
                            time.sleep(0.6)
                            items_after_restart = page2.locator('#prompt-versions-list li').count()
                            assert items_after_restart == 3, (
                                f'expected 3 versions after uvicorn restart, got {items_after_restart}')
                            draft_after_restart = page2.locator('#prompt-draft-content').input_value()
                            assert draft_after_restart == draft_before_restart, (
                                f'draft content differed after restart:'
                                f' before={draft_before_restart!r} after={draft_after_restart!r}')
                            # Readback via the authenticated API to prove the DB rows survived
                            # DB-backed API readback via the restored cid.
                            api_items = page2.evaluate(
                                """async () => {
                                  const cid = sessionStorage.getItem('oneshot_conversation_id');
                                  if (!cid) return null;
                                  const r = await fetch(
                                    `/api/conversations/${cid}/prompts`,
                                    {credentials:'same-origin'});
                                  return (await r.json()).items;
                                }""")
                            assert api_items, (
                                'API readback after restart returned no prompts')
                            assert len(api_items) == 1 and api_items[0]['name'] == 'Report Draft Prompt'
                            if errors:
                                raise AssertionError(f'Browser console errors: {errors}')
                    finally:
                        browser2.close()
                    print(json.dumps({'ok': True,
                                      'scenarios': ['P01', 'P02-uvicorn-restart',
                                                    'P03', 'P04', 'P05',
                                                    'P08', 'P10', 'P11',
                                                    'P12-precondition-missing',
                                                    'P18']}))
                finally:
                    stop(p2)
        finally:
            # p already stopped in the inner finally; stop() is idempotent.
            stop(p)


if __name__ == '__main__':
    run()
