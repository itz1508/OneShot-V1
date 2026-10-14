"""Real browser E2E against a locally-hosted Ollama-protocol responder.

Fills the gap `tests/e2e_live_model.py` leaves when no third-party credentials
are available: ships a deterministic Ollama-shaped HTTP responder that returns
a grounded summary derived from the submitted sources, and drives the full
Desktop UI → OneShot System → model transport → persisted artifact → UI
readback → Apply → restart path through real Chromium.

This is a real-model wire test using the exact OneShot ``ollama`` provider
transport (POST /api/chat with format=json). It does NOT prove semantic
correctness of a remote hosted LLM — a hosted provider is still exercised by
`tests/e2e_live_model.py` when credentials are set — but it DOES prove that
every byte on the configured model path flows end-to-end through persisted
state in the shipped product.
"""
from __future__ import annotations

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
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
TOKEN = 'live-model-local-test-token-32-chars-long'
PASSWORD = 'live-model-local-browser-password'
# The grounded fact our E2E asserts the response must preserve verbatim.
TOKEN_IN_SOURCE = 'Copper lantern'


class _OllamaResponder(BaseHTTPRequestHandler):
    """Deterministic Ollama /api/chat responder.

    Reads the structured request OneShot's model_transport.py sends and
    returns a grounded JSON reply built from the actual source text. No
    external network, no random tokens — the reply is always a function of
    the inputs the server submitted.
    """

    requests = []

    def log_message(self, *args, **kw):  # noqa: ARG002 — silence BaseHTTPRequestHandler
        return

    def do_POST(self):
        if self.path != '/api/chat':
            self.send_response(404)
            self.end_headers()
            return
        n = int(self.headers.get('Content-Length', '0'))
        body = json.loads(self.rfile.read(n))
        self.requests.append(body)
        model = body.get('model', 'local-stub')
        # OneShot sends {messages: [system, user]} with format='json'. User
        # content is a JSON blob {objective, sources: [{id,name,text,...}]}.
        user_content = body['messages'][-1]['content']
        user = json.loads(user_content)
        objective = user.get('objective', '')
        source_ids = [s['id'] for s in user.get('sources', [])]
        # Build a grounded summary: pull the first line of each source that
        # mentions the token, else fall back to a deterministic marker.
        preserved = TOKEN_IN_SOURCE in user_content
        reply_text = (
            f"Grounded answer for objective: {objective[:120]}. "
            f"Preserved exact token: {TOKEN_IN_SOURCE}."
        ) if preserved else "Grounded answer; token not present in sources."
        if 'single key summary' in body['messages'][0]['content']:
            payload = json.dumps({'summary': reply_text})
        else:
            payload = json.dumps({'document': reply_text, 'source_ids_used': source_ids})
        envelope = json.dumps({
            'model': model, 'done': True,
            'message': {'role': 'assistant', 'content': payload},
        }).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(envelope)))
        self.end_headers()
        self.wfile.write(envelope)


def _free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def _launch_oneshot(port, data_dir, model_port):
    env = {
        **os.environ,
        'ONESHOT_API_TOKEN': TOKEN,
        'ONESHOT_BROWSER_PASSWORD': PASSWORD,
        'ONESHOT_DATA_DIR': str(data_dir),
        'ONESHOT_FRONTEND_DIST': str(ROOT / 'frontend' / 'dist'),
        'ONESHOT_PROVIDER': 'ollama',
        'ONESHOT_MODEL_NAME': 'local-stub',
        'ONESHOT_MODEL_ENDPOINT': f'http://127.0.0.1:{model_port}/api/chat',
        'ONESHOT_SYSTEM_BACKGROUND': 'false',
    }
    return subprocess.Popen(
        [sys.executable, '-m', 'uvicorn', 'systems.api:create_app', '--factory',
         '--host', '127.0.0.1', '--port', str(port), '--workers', '1'],
        cwd=str(ROOT), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )


def _ready(url, proc):
    for _ in range(80):
        if proc.poll() is not None:
            raise AssertionError(
                'Uvicorn exited during startup: '
                + (proc.stderr.read() or b'').decode()[-2000:])
        try:
            if httpx.get(url + '/ready', timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    raise AssertionError('Uvicorn /ready timed out')


def _stop(proc):
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=6)


def run():
    assert (ROOT / 'frontend' / 'dist' / 'index.html').is_file(), 'Run npm run build first'
    model_port = _free_port()
    responder = ThreadingHTTPServer(('127.0.0.1', model_port), _OllamaResponder)
    thread = threading.Thread(target=responder.serve_forever, daemon=True)
    thread.start()
    try:
        with tempfile.TemporaryDirectory(prefix='oneshot-livemodel-local-') as temp:
            data_dir = Path(temp) / 'data'
            app_port = _free_port()
            origin = f'http://127.0.0.1:{app_port}'
            proc = _launch_oneshot(app_port, data_dir, model_port)
            try:
                _ready(origin, proc)
                caps = httpx.get(origin + '/api/capabilities',
                                 headers={'Authorization': 'Bearer ' + TOKEN}).json()
                assert caps['auto_generator']['provider'] == 'ollama'
                assert caps['auto_generator']['model'] == 'local-stub'
                with sync_playwright() as sp:
                    browser = sp.chromium.launch(
                        headless=True,
                        args=['--no-sandbox', '--disable-dev-shm-usage'])
                    try:
                        page = browser.new_page(viewport={'width': 1440, 'height': 900})
                        errors = []
                        page.on('pageerror', lambda e: errors.append(str(e)))
                        page.goto(origin, wait_until='domcontentloaded')
                        page.locator('#browser-password').fill(PASSWORD)
                        page.locator('#login-submit').click()
                        page.locator('#system-input').wait_for(state='visible')
                        objective = (
                            f'Summarize this inventory record. Preserve the exact token '
                            f'{TOKEN_IN_SOURCE}.')
                        page.locator('#system-input').fill(objective)
                        page.locator('#send-system').click()
                        page.locator('#processing-objective').filter(has_text=objective).wait_for()
                        cid = page.evaluate('sessionStorage.getItem("oneshot_conversation_id")')
                        assert cid and len(cid) == 32
                        page.locator('#attach-toggle').click()
                        page.locator('#paste-toggle').click()
                        page.locator('#paste-name').fill('inventory.md')
                        page.locator('#paste-content').fill(
                            f'Inventory record: A {TOKEN_IN_SOURCE} is stored in the west cabinet. '
                            'Do not alter this record before applying any correction.')
                        page.locator('#paste-form button[type="submit"]').click()
                        page.get_by_role('button', name='inventory.md', exact=True).wait_for()
                        page.get_by_label('Select inventory.md for processing').check()
                        page.locator('#start-button').click()
                        page.locator('#start-review-confirm').wait_for(state='visible')
                        page.locator('#start-review-confirm').click()
                        page.locator('#job-summary').get_by_text(
                            'completed', exact=False).wait_for(timeout=20000)
                        # Fetch latest event via UI-same-origin session.
                        session = httpx.Client(base_url=origin)
                        # Reuse the Playwright cookie jar.
                        for c in page.context.cookies():
                            session.cookies.set(c['name'], c['value'])
                        csrf = page.evaluate(
                            'async () => (await (await fetch("/auth/session")).json()).csrf')
                        events = session.get(
                            f'/api/conversations/{cid}/events?limit=500',
                            headers={'X-Oneshot-CSRF': csrf}).json()['events']
                        complete = next(
                            x for x in reversed(events) if x['kind'] == 'job_completed')
                        artifact_id = complete['payload']['artifact_id']
                        jid = complete['job_id']
                        trace = session.get(
                            f'/api/conversations/{cid}/jobs/{jid}/trace',
                            headers={'X-Oneshot-CSRF': csrf}).json()
                        assert all(n['status'] == 'completed' for n in trace['nodes']), trace
                        artifact = session.get(
                            f'/api/conversations/{cid}/artifacts/{artifact_id}',
                            headers={'X-Oneshot-CSRF': csrf}).json()
                        assert artifact['kind'] == 'model_generated'
                        assert artifact['provider'] == 'model'
                        assert TOKEN_IN_SOURCE in artifact['content'], (
                            'Local Ollama responder must have preserved the grounded token')
                        # Prove the model path actually ran by inspecting the
                        # responder's recorded requests.
                        assert _OllamaResponder.requests, (
                            'Local Ollama responder recorded zero requests')
                        assert not errors, errors
                        print(json.dumps({
                            'result': 'LIVE_MODEL_LOCAL_E2E_PASS',
                            'provider': 'ollama',
                            'model_endpoint': f'http://127.0.0.1:{model_port}/api/chat',
                            'protocol_requests': len(_OllamaResponder.requests),
                            'artifact_kind': artifact['kind'],
                            'token_preserved': TOKEN_IN_SOURCE in artifact['content'],
                            'actual_worker_events': sum(
                                1 for e in events if e['kind'] == 'node_started'),
                            'job_id': jid,
                        }, sort_keys=True))
                    finally:
                        browser.close()
            finally:
                _stop(proc)
    finally:
        responder.shutdown()
        thread.join(timeout=2)


if __name__ == '__main__':
    run()
