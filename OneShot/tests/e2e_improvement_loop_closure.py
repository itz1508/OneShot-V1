"""Real-browser closure for I09, I12, I13, I16 against the shipped v6.0.2 UI + API.

Scenario IDs identify tests, they do not redefine the I01-I16 contracts (directive §1).
Each scenario runs through the authenticated session the operator uses (login + CSRF-wrapped
`ui_api`), so the browser authority boundary is honoured.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

from tests.e2e_browser import PASSWORD, launch, port_available, ready, stop, ui_api, wait_for_boot

ROOT = Path(__file__).resolve().parents[1]


def _await_terminal(page, cid, jid):
    for _ in range(120):
        got = ui_api(page, f'/api/conversations/{cid}/jobs/{jid}')
        if got['status'] == 200 and got['data']['status'] in ('completed', 'failed', 'blocked'):
            return got['data']
        time.sleep(0.1)
    raise AssertionError(f'job {jid} never reached terminal state')


def _create_terminal_job(page, cid, name, body):
    src = ui_api(page, f'/api/conversations/{cid}/sources/actions', 'POST',
                 {'action': 'INPUT_SOURCE', 'name': name, 'content': body})
    assert src['status'] == 201, src
    sid = src['data']['source_id']; sver = src['data']['version']
    msg = ui_api(page, f'/api/conversations/{cid}/messages', 'POST',
                 {'channel': 'system', 'content': f'Objective: {name}'})
    assert msg['status'] == 201, msg
    mid = msg['data']['id']
    jr = ui_api(page, f'/api/conversations/{cid}/jobs', 'POST',
                {'operation': 'inspect_sources', 'source_ids': [sid],
                 'expected_versions': {sid: sver},
                 'idempotency_key': 'closure-' + name.replace('.', '-'),
                 'prompt_message_id': mid})
    assert jr['status'] in (201, 202), jr
    jid = jr['data']['id']
    terminal = _await_terminal(page, cid, jid)
    return jid, terminal


def run():
    assert (ROOT/'frontend'/'dist'/'index.html').is_file(), 'frontend not built'
    results = {'scenarios': []}
    with tempfile.TemporaryDirectory(prefix='oneshot-imp-closure-') as tmp:
        os.environ['ONESHOT_RATE_LIMIT_MAX'] = '2000'
        os.environ['ONESHOT_RATE_LIMIT_WINDOW_SECONDS'] = '60'
        data_dir = Path(tmp)/'data'
        port = port_available()
        url = f'http://127.0.0.1:{port}'
        proc = launch(port, data_dir)
        try:
            ready(url, proc)
            with sync_playwright() as driver:
                chromium = os.environ.get('ONESHOT_E2E_CHROMIUM') or shutil.which('chromium')
                browser = driver.chromium.launch(
                    executable_path=chromium or None, headless=True,
                    args=['--no-sandbox', '--disable-dev-shm-usage'] if sys.platform.startswith('linux') else [])
                try:
                    page = browser.new_page(viewport={'width': 1300, 'height': 1000})
                    _errs = []
                    page.on('pageerror', lambda e: _errs.append(str(e)))
                    page.goto(url, wait_until='domcontentloaded', timeout=15000)
                    page.locator('#browser-password').fill(PASSWORD)
                    page.locator('#login-submit').click()
                    page.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page)
                    cid = page.evaluate('sessionStorage.getItem("oneshot_conversation_id")')
                    assert cid and len(cid) == 32, cid

                    # ---- Build TWO terminal jobs so we can exercise I12 / I13 ---------
                    jid_a, job_a = _create_terminal_job(page, cid, 'baseline.txt',
                                                         'baseline body-content for I12')
                    jid_b, job_b = _create_terminal_job(page, cid, 'candidate.txt',
                                                         'candidate body-content for I12')
                    assert jid_a != jid_b
                    # Both jobs went through inspect_sources, which doesn't bind a prompt
                    # version — so prompt_version_id is None. Create and publish a prompt
                    # version and bind the next job to it so we can assert I13 provenance.
                    pr = ui_api(page, f'/api/conversations/{cid}/prompts', 'POST',
                                {'name': 'closure-prompt', 'content': 'Summarize ${source}.',
                                 'variables': [{'name': 'source'}]})
                    assert pr['status'] == 201, pr
                    pid = pr['data']['id']
                    # bump draft rev from 1 to 2
                    saved = ui_api(page, f'/api/conversations/{cid}/prompts/{pid}/draft',
                                   'PATCH', {'content': 'Summarize ${source}.',
                                             'variables': [{'name': 'source'}],
                                             'expected_revision': 1})
                    assert saved['status'] == 200, saved
                    pub = ui_api(page, f'/api/conversations/{cid}/prompts/{pid}/publish', 'POST',
                                 {'expected_revision': saved['data']['revision']})
                    assert pub['status'] == 201, pub
                    v1_id = pub['data']['id']
                    v1_sha = pub['data']['content_sha256']

                    # ---- I09: Recurring defects + evidence readback -------------------
                    # Save a review on jid_a; recurring-defects summary becomes non-zero.
                    r = ui_api(page, f'/api/conversations/{cid}/jobs/{jid_a}/review', 'PUT',
                               {'decision': 'observed_defect',
                                'required': 'Must cite baseline',
                                'reason': 'Missing source id for I09'})
                    assert r['status'] == 200, r
                    rd = ui_api(page, f'/api/conversations/{cid}/recurring-defects?min_count=1')
                    assert rd['status'] == 200, rd
                    reviews = rd['data']['reviews']
                    assert any(x['decision'] == 'observed_defect' and x['n'] >= 1
                               for x in reviews), rd
                    # Also drive the UI panel — click into jid_a and confirm the recurring
                    # defects summary renders a non-empty item (I14 + I09 integration).
                    page.locator('#run-history-refresh').click()
                    page.locator('.run-history-open', has_text=jid_a[:8]).first.click()
                    page.locator('#improvement-loop').wait_for(state='visible')
                    page.locator('#improvement-recurring-section').locator('summary').click()
                    page.locator('#improvement-recurring-summary').wait_for(state='visible')
                    txt = page.locator('#improvement-recurring-summary').inner_text()
                    assert 'Reviews:' in txt and 'grouping' in txt, txt
                    results['scenarios'].append('I09-browser-recurring-defects')

                    # ---- I12: Baseline / candidate comparison -------------------------
                    cmp = ui_api(page, f'/api/conversations/{cid}/compare/runs?left={jid_a}&right={jid_b}')
                    assert cmp['status'] == 200, cmp
                    assert cmp['data']['left']['job_id'] == jid_a, cmp['data']
                    assert cmp['data']['right']['job_id'] == jid_b, cmp['data']
                    # The two jobs produced different artifacts because their inputs differ.
                    assert cmp['data']['left']['artifact'] != cmp['data']['right']['artifact']
                    results['scenarios'].append('I12-browser-baseline-candidate-compare')

                    # ---- I13: Immutable prompt-version identity + provenance ---------
                    # Publish v2 and verify v1 content_sha256 remains unchanged (immutability).
                    saved2 = ui_api(page, f'/api/conversations/{cid}/prompts/{pid}/draft',
                                    'PATCH', {'content': 'Summarize ${source} in exact bullets.',
                                              'variables': [{'name': 'source'}],
                                              'expected_revision': saved['data']['revision']})
                    assert saved2['status'] == 200, saved2
                    pub2 = ui_api(page, f'/api/conversations/{cid}/prompts/{pid}/publish', 'POST',
                                  {'expected_revision': saved2['data']['revision']})
                    assert pub2['status'] == 201, pub2
                    assert pub2['data']['version_number'] == 2
                    # Re-fetch v1 — content and sha256 unchanged.
                    v1_back = ui_api(page, f'/api/conversations/{cid}/prompts/{pid}/versions/1')
                    assert v1_back['status'] == 200, v1_back
                    assert v1_back['data']['content_sha256'] == v1_sha, (v1_back, v1_sha)
                    assert v1_back['data']['id'] == v1_id
                    # Compare v1 vs v2 is non-identical and preserves both version numbers.
                    cmpv = ui_api(page, f'/api/conversations/{cid}/prompts/{pid}/compare?left=1&right=2')
                    assert cmpv['status'] == 200, cmpv
                    assert not cmpv['data']['identical']
                    results['scenarios'].append('I13-browser-prompt-version-immutable')

                    # ---- I16: Full improvement loop lifecycle through the UI ---------
                    # Before the reload, seed an evaluation (proposed→approved→completed) and
                    # an improvement proposal (proposed→accepted) through the API — the panel
                    # itself can create them via its forms (tests/e2e_improvement_loop.py
                    # already covers the click-through), so here we drive the authenticated
                    # session to produce the state and then verify ALL THREE classes of
                    # findings (review, evaluation, proposal) persist across a real browser
                    # reload, which is the actual I16 "full lifecycle" contract.
                    ev_create = ui_api(page, f'/api/conversations/{cid}/jobs/{jid_a}/evaluations',
                                       'POST', {'status': 'proposed',
                                                'criteria': [{'kind': 'contains', 'value': 'baseline'}]})
                    assert ev_create['status'] == 201, ev_create
                    eid = ev_create['data']['id']
                    appr = ui_api(page, f'/api/conversations/{cid}/job-evaluations/{eid}/approve', 'POST', {})
                    assert appr['status'] == 200, appr
                    runr = ui_api(page, f'/api/conversations/{cid}/job-evaluations/{eid}/run', 'POST', {})
                    assert runr['status'] == 200, runr
                    assert runr['data']['status'] == 'completed', runr['data']
                    prop = ui_api(page, f'/api/conversations/{cid}/improvement-proposals', 'POST',
                                  {'issue_summary': 'Must include source identifier for provenance',
                                   'affected_responsibility': 'quality check',
                                   'current_behavior': 'No source id in output',
                                   'required_behavior': 'Include source id',
                                   'proposed_correction': 'Enforce has_source_id',
                                   'risks': '',
                                   'evidence': {'job_ids': [jid_a]}})
                    assert prop['status'] == 201, prop
                    pid_prop = prop['data']['id']
                    accp = ui_api(page, f'/api/conversations/{cid}/improvement-proposals/{pid_prop}/accept',
                                  'POST', {})
                    assert accp['status'] == 200, accp

                    # First reload — same browser context, no restart.
                    page.reload(wait_until='domcontentloaded')
                    page.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page)
                    # Browser session may rebind sessionStorage; make sure it points at cid.
                    page.evaluate(f"sessionStorage.setItem('oneshot_conversation_id', '{cid}')")
                    page.reload(wait_until='domcontentloaded')
                    page.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page)
                    page.locator('#run-history-refresh').click()
                    page.locator('.run-history-open', has_text=jid_a[:8]).first.click()
                    page.locator('#improvement-loop').wait_for(state='visible')

                    # Review decision persisted
                    page.locator('#improvement-review-section').locator('summary').click()
                    assert page.locator(
                        'input[name="improvement-review-decision"][value="observed_defect"]'
                    ).is_checked(), 'review decision lost across reload'

                    # Evaluation persisted + visible in the eval list with completed status
                    page.locator('#improvement-eval-section').locator('summary').click()
                    page.locator(
                        '#improvement-eval-list > li[data-status="completed"]'
                    ).first.wait_for(state='attached', timeout=10000)

                    # Proposal persisted + visible with accepted status
                    page.locator('#improvement-proposal-section').locator('summary').click()
                    page.locator(
                        '#improvement-proposal-list > li[data-status="accepted"]'
                    ).first.wait_for(state='attached', timeout=10000)

                    # Recurring defects summary still non-zero after reload
                    page.locator('#improvement-recurring-section').locator('summary').click()
                    rd2 = page.locator('#improvement-recurring-summary').inner_text()
                    assert 'Reviews:' in rd2 and '0 grouping' not in rd2, rd2

                    # Full-API readback also confirms the three classes of findings persist.
                    rd_api = ui_api(page, f'/api/conversations/{cid}/recurring-defects?min_count=1')
                    assert rd_api['status'] == 200 and rd_api['data']['reviews'], rd_api
                    ev_api = ui_api(page, f'/api/conversations/{cid}/job-evaluations?job_id={jid_a}')
                    assert ev_api['status'] == 200 and any(
                        e['status'] == 'completed' for e in ev_api['data']['items']), ev_api
                    prop_api = ui_api(page, f'/api/conversations/{cid}/improvement-proposals')
                    assert prop_api['status'] == 200 and any(
                        p['status'] == 'accepted' for p in prop_api['data']['items']), prop_api

                    results['scenarios'].append('I16-browser-full-lifecycle')

                    assert not _errs, _errs
                finally:
                    browser.close()

            # ---- I16 extended: fresh browser context + application restart ----
            # Directive v6.0.4 §3 (5/6/7/8). Stop uvicorn, relaunch, open a new browser
            # process + new context, re-authenticate, rebind the sessionStorage conversation
            # id, reopen the same historical job and assert every findings class still
            # persists AND no new evaluation / proposal / Apply operation was created by the
            # readback alone.
            stop(proc)
            os.environ['ONESHOT_RATE_LIMIT_MAX'] = '2000'
            os.environ['ONESHOT_RATE_LIMIT_WINDOW_SECONDS'] = '60'
            proc = launch(port, data_dir)
            ready(url, proc)
            with sync_playwright() as driver2:
                chromium2 = os.environ.get('ONESHOT_E2E_CHROMIUM') or shutil.which('chromium')
                browser2 = driver2.chromium.launch(
                    executable_path=chromium2 or None, headless=True,
                    args=['--no-sandbox', '--disable-dev-shm-usage'] if sys.platform.startswith('linux') else [])
                try:
                    # Fresh context: no cookies, no sessionStorage carryover.
                    ctx = browser2.new_context()
                    ctx.set_default_timeout(10000)
                    page2 = ctx.new_page()
                    page2.set_viewport_size({'width': 1300, 'height': 1000})
                    _errs2 = []
                    page2.on('pageerror', lambda e: _errs2.append(str(e)))
                    page2.goto(url, wait_until='domcontentloaded', timeout=15000)
                    # Reauthenticate from scratch.
                    page2.locator('#browser-password').fill(PASSWORD)
                    page2.locator('#login-submit').click()
                    page2.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page2)
                    # Pin the sessionStorage conversation id to the pre-restart cid and reload.
                    page2.evaluate(f"sessionStorage.setItem('oneshot_conversation_id', '{cid}')")
                    page2.reload(wait_until='domcontentloaded')
                    page2.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page2)

                    # Snapshot counts BEFORE opening the job in the fresh browser.
                    ev_before = ui_api(page2, f'/api/conversations/{cid}/job-evaluations?job_id={jid_a}')
                    pr_before = ui_api(page2, f'/api/conversations/{cid}/improvement-proposals')
                    assert ev_before['status'] == 200 and pr_before['status'] == 200
                    ev_count_before = len(ev_before['data']['items'])
                    pr_count_before = len(pr_before['data']['items'])
                    job_before = ui_api(page2, f'/api/conversations/{cid}/jobs/{jid_a}')
                    assert job_before['status'] == 200

                    # Open the historical job and inspect panels.
                    page2.locator('#run-history-refresh').click()
                    page2.locator('.run-history-open', has_text=jid_a[:8]).first.click()
                    page2.locator('#improvement-loop').wait_for(state='visible')
                    # (5)/(6) persisted review decision in fresh context
                    page2.locator('#improvement-review-section').locator('summary').click()
                    assert page2.locator(
                        'input[name="improvement-review-decision"][value="observed_defect"]'
                    ).is_checked(), 'review decision lost in fresh browser context'
                    # Completed evaluation and accepted proposal visible
                    page2.locator('#improvement-eval-section').locator('summary').click()
                    page2.locator(
                        '#improvement-eval-list > li[data-status="completed"]'
                    ).first.wait_for(state='attached', timeout=10000)
                    page2.locator('#improvement-proposal-section').locator('summary').click()
                    page2.locator(
                        '#improvement-proposal-list > li[data-status="accepted"]'
                    ).first.wait_for(state='attached', timeout=10000)
                    page2.locator('#improvement-recurring-section').locator('summary').click()
                    rd2 = page2.locator('#improvement-recurring-summary').inner_text()
                    assert 'Reviews:' in rd2 and '0 grouping' not in rd2, rd2

                    # (7)/(8) Count-level assertion: readback did NOT create new rows.
                    ev_after = ui_api(page2, f'/api/conversations/{cid}/job-evaluations?job_id={jid_a}')
                    pr_after = ui_api(page2, f'/api/conversations/{cid}/improvement-proposals')
                    assert ev_after['status'] == 200 and pr_after['status'] == 200
                    assert len(ev_after['data']['items']) == ev_count_before, (
                        'readback created new evaluation rows', ev_before, ev_after)
                    assert len(pr_after['data']['items']) == pr_count_before, (
                        'readback created new proposal rows', pr_before, pr_after)
                    # Job row unchanged
                    job_after = ui_api(page2, f'/api/conversations/{cid}/jobs/{jid_a}')
                    assert job_after['status'] == 200
                    assert job_after['data'] == job_before['data'], (
                        'readback mutated job row across restart')

                    assert not _errs2, _errs2
                    results['scenarios'].append('I16-browser-fresh-context-and-restart')
                finally:
                    browser2.close()
        finally:
            stop(proc)
    results['ok'] = True
    print(json.dumps(results, sort_keys=True))


if __name__ == '__main__':
    run()
