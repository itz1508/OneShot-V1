"""Required live-model browser E2E: actual System UI → real provider → persisted summary.

No provider stubs. Must be run with explicitly configured ONESHOT_PROVIDER,
ONESHOT_MODEL_NAME and applicable ONESHOT_MODEL_TOKEN / ONESHOT_MODEL_ENDPOINT.
Cannot establish semantic correctness for all inputs; asserts a known grounded fact.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from tests.e2e_browser import PASSWORD, ROOT, TOKEN, port_available, ready, stop, ui_api


def run() -> None:
    provider = os.environ.get('ONESHOT_PROVIDER', 'evidence')
    assert provider in ('openai', 'gemini', 'ollama', 'model'), (
        'Live-model E2E requires ONESHOT_PROVIDER=openai|gemini|ollama|model; '
        'evidence mode or a controlled responder is not a real model test'
    )
    assert os.environ.get('ONESHOT_MODEL_NAME'), 'Configure an actual ONESHOT_MODEL_NAME'
    if provider in ('openai', 'gemini', 'model'):
        assert os.environ.get('ONESHOT_MODEL_TOKEN'), 'Live provider credentials are required'
    assert (ROOT / 'frontend' / 'dist' / 'index.html').is_file(), 'Build frontend first'

    with tempfile.TemporaryDirectory(prefix='oneshot-live-model-e2e-') as temporary:
        data = Path(temporary) / 'data'
        port = port_available()
        origin = f'http://127.0.0.1:{port}'
        env = {**os.environ, 'ONESHOT_API_TOKEN': TOKEN,
               'ONESHOT_BROWSER_PASSWORD': PASSWORD, 'ONESHOT_DATA_DIR': str(data),
               'ONESHOT_FRONTEND_DIST': str(ROOT / 'frontend' / 'dist'),
               'ONESHOT_SYSTEM_BACKGROUND': 'false'}
        proc = subprocess.Popen(
            [sys.executable, '-m', 'uvicorn', 'systems.api:create_app', '--factory',
             '--host', '127.0.0.1', '--port', str(port), '--workers', '1'],
            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        try:
            ready(origin, proc)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                try:
                    context = browser.new_context(viewport={'width': 1440, 'height': 900}, accept_downloads=True)
                    page = context.new_page()
                    errors = []
                    page.on('pageerror', lambda exception: errors.append(str(exception)))
                    page.goto(origin, wait_until='domcontentloaded')
                    page.locator('#browser-password').fill(PASSWORD)
                    page.locator('#login-submit').click()
                    page.locator('#system-input').wait_for(state='visible')
                    caps = ui_api(page, '/api/capabilities')
                    assert caps['status'] == 200 and caps['data']['auto_generator']['provider'] == provider, caps
                    prompt = ('Summarize the attached original in one sentence. Preserve the exact '
                              'object name Copper lantern and do not invent other objects.')
                    page.locator('#system-input').fill(prompt)
                    page.locator('#send-system').click()
                    page.locator('#processing-objective').filter(has_text=prompt).wait_for()
                    cid = page.evaluate('sessionStorage.getItem("oneshot_conversation_id")')
                    assert cid
                    page.locator('#attach-toggle').click()
                    page.locator('#paste-toggle').click()
                    page.locator('#paste-name').fill('reference.txt')
                    source = ('Inventory record: A Copper lantern is stored in the west cabinet. '
                              'The label and the cabinet location are verified by the original record.')
                    page.locator('#paste-content').fill(source)
                    page.locator('#paste-form button[type="submit"]').click()
                    page.get_by_role('button', name='reference.txt').wait_for()
                    page.get_by_label('Select reference.txt for processing').check()
                    page.locator('#requested-operation').select_option('summarize')
                    page.locator('#start-button').click()
                    page.locator('#start-review-dialog').wait_for(state='visible')
                    page.locator('#start-review-confirm').click()
                    page.locator('#job-summary').get_by_text('completed', exact=False).wait_for(timeout=90000)
                    page.locator('#open-result').click()
                    page.locator('#artifact-content').wait_for(state='visible')
                    summary_text = page.locator('#artifact-content').inner_text()
                    assert 'Copper lantern' in summary_text, summary_text
                    assert page.locator('#summary-export').is_visible()
                    with page.expect_download(timeout=20000) as d:
                        page.locator('#summary-export').click()
                    download = d.value
                    assert download.suggested_filename == 'output.json', download.suggested_filename
                    path = download.path()
                    assert path is not None
                    exported = json.loads(path.read_text(encoding='utf-8'))
                    assert set(exported) == {'summary'} and 'Copper lantern' in exported['summary'], exported
                    srcs = ui_api(page, f'/api/conversations/{cid}/sources')
                    assert srcs['status'] == 200 and len(srcs['data']) == 1, srcs
                    sid = srcs['data'][0]['id']
                    original = page.evaluate('''async path => (await fetch(path)).text()''',
                        f'/api/conversations/{cid}/sources/{sid}/content')
                    assert original == source, 'Original source changed without Apply'
                    events = ui_api(page, f'/api/conversations/{cid}/events')
                    assert events['status'] == 200 and any(
                        x['kind'] == 'job_completed' for x in events['data']['events']), events
                    assert not errors, errors
                    print(json.dumps({'result': 'LIVE_MODEL_BROWSER_PATH_OBSERVED',
                        'provider': provider, 'semantic_fixture': 'Copper lantern',
                        'summary_export': 'output.json', 'source_immutable': True,
                        'note': 'One source-grounded fixture; separate broader model evaluation still required'},
                        sort_keys=True))
                finally:
                    browser.close()
        finally:
            stop(proc)


if __name__ == '__main__':
    run()
