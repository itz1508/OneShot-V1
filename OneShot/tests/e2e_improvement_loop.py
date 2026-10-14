"""Real Chromium -> frontend -> OneShot System -> SQLite exercise of the v6 Improvement Loop UI.

Covers I01, I03, I04, I06, I07, I08, I10, I11, I14 and the post-restart persistence requirement
of I15 as applied to review state. Model-dependent scenarios (I05) are explicitly out of scope
here; see tests/e2e_live_model_local.py for the model-execution gate.

Scenarios (names only identify tests; they do not redefine I01-I16):
  I03-browser-review-create
  I03-browser-review-update
  I06-browser-eval-propose-approve
  I07-browser-eval-reject-not-runnable
  I08-browser-eval-run-after-approve
  I10-browser-proposal-lifecycle
  I11-browser-no-apply-mutation
  I14-browser-run-history-navigation
  I15-browser-review-survives-restart
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from tests.e2e_browser import PASSWORD, launch, port_available, ready, stop, ui_api, wait_for_boot

ROOT = Path(__file__).resolve().parents[1]


def run():
    assert (ROOT/'frontend'/'dist'/'index.html').is_file(), 'frontend not built'
    results = {'scenarios': []}
    with tempfile.TemporaryDirectory(prefix='oneshot-imp-loop-e2e-') as tmp:
        data_dir = Path(tmp)/'data'
        port = port_available()
        url = f'http://127.0.0.1:{port}'
        os.environ['ONESHOT_RATE_LIMIT_MAX'] = '2000'
        os.environ['ONESHOT_RATE_LIMIT_WINDOW_SECONDS'] = '60'
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
                    _page_errors = []
                    page.on('pageerror', lambda ex: _page_errors.append(str(ex)))
                    page.goto(url, wait_until='domcontentloaded', timeout=15000)
                    page.locator('#browser-password').fill(PASSWORD)
                    page.locator('#login-submit').click()
                    page.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page)
                    cid = page.evaluate('sessionStorage.getItem("oneshot_conversation_id")')
                    assert cid and len(cid) == 32, cid

                    # Create a source + run an inspect_sources job (deterministic terminal state).
                    src = ui_api(page, f'/api/conversations/{cid}/sources/actions', 'POST',
                                 {'action': 'INPUT_SOURCE', 'name': 'review-target.txt',
                                  'content': 'ground truth body-content for review'})
                    assert src['status'] == 201, src
                    sid = src['data']['source_id']; sver = src['data']['version']
                    msg = ui_api(page, f'/api/conversations/{cid}/messages', 'POST',
                                 {'channel': 'system', 'content': 'Objective: review target'})
                    assert msg['status'] == 201, msg
                    mid = msg['data']['id']
                    jr = ui_api(page, f'/api/conversations/{cid}/jobs', 'POST',
                                {'operation': 'inspect_sources', 'source_ids': [sid],
                                 'expected_versions': {sid: sver},
                                 'idempotency_key': 'imp-e2e-aaa', 'prompt_message_id': mid})
                    assert jr['status'] in (201, 202), jr
                    jid = jr['data']['id']
                    # Poll until terminal.
                    terminal = {'completed', 'failed', 'blocked'}
                    import time
                    for _ in range(120):
                        got = ui_api(page, f'/api/conversations/{cid}/jobs/{jid}')
                        if got['status'] == 200 and got['data']['status'] in terminal:
                            break
                        time.sleep(0.1)
                    else:
                        raise AssertionError('job never reached terminal state')
                    pre_review_job = got['data']

                    # Reload the browser so Run History picks up the historical job, then open it.
                    page.reload(wait_until='domcontentloaded')
                    page.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page)
                    page.locator('#run-history-refresh').click()
                    page.locator('.run-history-open', has_text=jid[:8]).first.wait_for(state='visible',
                                                                                        timeout=10000)
                    page.locator('.run-history-open', has_text=jid[:8]).first.click()
                    page.locator('#improvement-loop').wait_for(state='visible')
                    results['scenarios'].append('I14-browser-run-history-navigation')

                    # ---- I03: create a review ------------------------------------------------
                    page.locator('#improvement-review-section').locator('summary').click()
                    page.locator('input[name="improvement-review-decision"][value="observed_defect"]').check()
                    page.locator('#improvement-review-required').fill('Must cite body-content')
                    page.locator('#improvement-review-prohibited').fill('No fabricated numbers')
                    page.locator('#improvement-review-reason').fill('Missing provenance in output')
                    page.locator('#improvement-review-save').click()
                    page.locator('#improvement-review-state',
                                 has_text='Revision 1 saved').wait_for(timeout=5000)
                    results['scenarios'].append('I03-browser-review-create')

                    # Verify I03/I11 — the job row was NOT mutated by saving a review.
                    post_review_job = ui_api(page, f'/api/conversations/{cid}/jobs/{jid}')
                    assert post_review_job['status'] == 200
                    assert pre_review_job == post_review_job['data'], 'review mutated job row'
                    results['scenarios'].append('I11-browser-no-apply-mutation')

                    # ---- I03 revision: update it --------------------------------------------
                    page.locator('input[name="improvement-review-decision"][value="potential_defect"]').check()
                    page.locator('#improvement-review-reason').fill('Promoted to hypothesis')
                    page.locator('#improvement-review-save').click()
                    page.locator('#improvement-review-state',
                                 has_text='Revision 2 saved').wait_for(timeout=5000)
                    results['scenarios'].append('I03-browser-review-update')

                    # ---- I06: propose an evaluation and approve it --------------------------
                    page.locator('#improvement-eval-section').locator('summary').click()
                    page.locator('#improvement-eval-kind').select_option('contains')
                    page.locator('#improvement-eval-value').fill('body-content')
                    page.locator('#improvement-eval-create').click()
                    first_eval_li = page.locator('#improvement-eval-list > li').first
                    first_eval_li.wait_for(state='attached', timeout=5000)
                    first_eval_li.locator('button:has-text("Approve")').click()
                    first_eval_li.locator('button:has-text("Run evaluation")').wait_for(timeout=5000)
                    results['scenarios'].append('I06-browser-eval-propose-approve')

                    # ---- I08: run approved evaluation ---------------------------------------
                    first_eval_li.locator('button:has-text("Run evaluation")').click()
                    # After run completes, the status chip changes.
                    page.locator('#improvement-eval-list > li[data-status="completed"]').first.wait_for(state="attached", 
                        timeout=10000)
                    results['scenarios'].append('I08-browser-eval-run-after-approve')

                    # ---- I07: a rejected evaluation has NO Run button -----------------------
                    page.locator('#improvement-eval-value').fill('impossible-marker-xyz')
                    page.locator('#improvement-eval-create').click()
                    # The new one is now a new <li> with data-status="proposed". Target the first
                    # proposed item (list order: newest first per API; be defensive).
                    proposed_items = page.locator('#improvement-eval-list > li[data-status="proposed"]')
                    proposed_items.first.wait_for(state='attached', timeout=5000)
                    proposed_items.first.locator('button:has-text("Reject")').click()
                    # Wait for the rejection to settle and verify no 'Run evaluation' is reachable on
                    # a rejected evaluation. Hard-check by querying API and by scanning the UI.
                    rejected_items = page.locator('#improvement-eval-list > li[data-status="rejected"]')
                    rejected_items.first.wait_for(state='attached', timeout=5000)
                    # No 'Run evaluation' button in a rejected row (verified via UI only).
                    assert rejected_items.first.locator('button:has-text("Run evaluation")').count() == 0
                    # Also no 'Approve' button once rejected.
                    assert rejected_items.first.locator('button:has-text("Approve")').count() == 0
                    # And the row keeps data-status=rejected after a UI refresh (API-level readback).
                    evs2 = ui_api(page, f'/api/conversations/{cid}/job-evaluations?job_id={jid}')
                    assert evs2['status'] == 200
                    rejected_api = [e for e in evs2['data']['items'] if e['status'] == 'rejected']
                    assert len(rejected_api) >= 1, evs2
                    results['scenarios'].append('I07-browser-eval-reject-not-runnable')

                    # ---- I10: proposal lifecycle --------------------------------------------
                    page.locator('#improvement-proposal-section').locator('summary').click()
                    page.locator('#improvement-proposal-issue').fill('Output omits body-content provenance')
                    page.locator('#improvement-proposal-area').fill('quality check')
                    page.locator('#improvement-proposal-current').fill('No source id in result')
                    page.locator('#improvement-proposal-required').fill('Include has_source_id check')
                    page.locator('#improvement-proposal-correction').fill('Enforce has_source_id')
                    page.locator('#improvement-proposal-create').click()
                    page.locator('#improvement-proposal-list > li[data-status="proposed"]').first.wait_for(state="attached", timeout=5000)
                    page.locator('#improvement-proposal-list > li[data-status="proposed"]').first.locator('button:has-text("Accept")').click()
                    page.locator('#improvement-proposal-list > li[data-status="accepted"]').first.wait_for(state="attached", timeout=5000)
                    page.locator('#improvement-proposal-list > li[data-status="accepted"]').first.locator('button:has-text("Mark implemented")').click()
                    page.locator('#improvement-proposal-list > li[data-status="implemented"]').first.wait_for(state="attached", timeout=5000)
                    results['scenarios'].append('I10-browser-proposal-lifecycle')

                    # Recurring defects — after at least one review, summary count is non-zero.
                    rd = ui_api(page, f'/api/conversations/{cid}/recurring-defects?min_count=1')
                    assert rd['status'] == 200
                    assert (rd['data']['reviews'] or
                            rd['data']['recurring_issue_codes']), rd

                    # Capture a screenshot for evidence.
                    page.screenshot(path=str(Path(tmp)/'improvement_loop.png'), full_page=True)
                finally:
                    browser.close()

            # ---- I15: review survives a real backend-process restart --------------------
            stop(proc)
            os.environ['ONESHOT_RATE_LIMIT_MAX'] = '2000'
            os.environ['ONESHOT_RATE_LIMIT_WINDOW_SECONDS'] = '60'
            proc = launch(port, data_dir)
            ready(url, proc)
            with sync_playwright() as driver:
                chromium = os.environ.get('ONESHOT_E2E_CHROMIUM') or shutil.which('chromium')
                browser = driver.chromium.launch(
                    executable_path=chromium or None, headless=True,
                    args=['--no-sandbox', '--disable-dev-shm-usage'] if sys.platform.startswith('linux') else [])
                try:
                    page2 = browser.new_page(viewport={'width': 1300, 'height': 1000})
                    page2.on('pageerror', lambda ex: _page_errors.append(str(ex)))
                    page2.goto(url, wait_until='domcontentloaded', timeout=15000)
                    page2.locator('#browser-password').fill(PASSWORD)
                    page2.locator('#login-submit').click()
                    page2.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page2)
                    # Rebind to the same conversation.
                    page2.evaluate(
                        f"sessionStorage.setItem('oneshot_conversation_id', '{cid}')")
                    page2.reload(wait_until='domcontentloaded')
                    page2.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page2)
                    page2.locator('#run-history-refresh').click()
                    page2.locator('.run-history-open', has_text=jid[:8]).first.click()
                    page2.locator('#improvement-loop').wait_for(state='visible')
                    page2.locator('#improvement-review-section').locator('summary').click()
                    # The decision we last saved was 'potential_defect' (revision 2).
                    assert page2.locator(
                        'input[name="improvement-review-decision"][value="potential_defect"]'
                    ).is_checked()
                    page2.locator('#improvement-review-state',
                                  has_text='Revision 2 saved').wait_for(timeout=5000)
                    results['scenarios'].append('I15-browser-review-survives-restart')
                finally:
                    browser.close()
        finally:
            stop(proc)
    results['ok'] = True
    print(json.dumps(results, sort_keys=True))
    if _page_errors: print('PAGE_ERRORS: ' + '\n'.join(_page_errors))


if __name__ == '__main__':
    run()
