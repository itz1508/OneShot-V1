"""Real Chromium -> authenticated OneShot -> pre-send review -> saved message assertions."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

from playwright.sync_api import sync_playwright

from tests.e2e_browser import PASSWORD, launch, port_available, ready, stop, ui_api, wait_for_boot

ROOT = Path(__file__).resolve().parents[1]


def run():
    assert (ROOT/'frontend'/'dist'/'presend.js').is_file(), 'Run npm run build first'
    with tempfile.TemporaryDirectory(prefix='oneshot-presend-e2e-') as tmp:
        port=port_available()
        url=f'http://127.0.0.1:{port}'
        proc=launch(port,Path(tmp)/'data')
        try:
            ready(url,proc)
            with sync_playwright() as driver:
                chromium_path=os.environ.get('ONESHOT_E2E_CHROMIUM') or shutil.which('chromium')
                browser=driver.chromium.launch(executable_path=chromium_path or None,headless=True,
                    args=['--no-sandbox','--disable-dev-shm-usage'] if sys.platform.startswith('linux') else [])
                try:
                    page=browser.new_page(viewport={'width':1300,'height':900})
                    console_errors=[]
                    page.on('pageerror',lambda ex:console_errors.append(str(ex)))
                    page.goto(url,wait_until='domcontentloaded',timeout=15000)
                    page.locator('#browser-password').fill(PASSWORD)
                    page.locator('#login-submit').click()
                    page.locator('#system-input').wait_for(state='visible')
                    wait_for_boot(page)
                    cid=page.evaluate('sessionStorage.getItem("oneshot_conversation_id")')
                    path=f'/api/conversations/{cid}'
                    def contents():
                        out=ui_api(page,path)
                        assert out['status']==200,out
                        return [m['content'] for m in out['data']['messages']]
                    assert contents()==[]

                    # A: review is optional, opt-in only. Cancel must never POST.
                    original='  Objective: Preserve all data.\nConstraints:\n- Do not delete records.  \n'
                    page.locator('#presend-enabled').check()
                    page.locator('#system-input').fill(original)
                    page.locator('#send-system').click()
                    page.get_by_role('dialog',name='Review context before sending').wait_for(state='visible')
                    assert page.locator('#presend-original').text_content()==original
                    assert page.locator('#presend-payload').text_content().endswith(original)
                    assert contents()==[]
                    # Native modal must isolate background keyboard navigation.
                    assert page.locator('#presend-dialog').evaluate('(el) => el.open')
                    assert page.evaluate('document.querySelector("#presend-dialog").matches(":modal")')
                    page.locator('#presend-cancel').click()
                    page.locator('#presend-dialog').wait_for(state='hidden')
                    assert contents()==[]
                    assert page.locator('#system-input').input_value()==original

                    # B: user edits summary; the exact preview becomes saved message.
                    page.locator('#send-system').click()
                    page.locator('#presend-summary').fill('Approved summary: keep source evidence.\nNo destructive mutation.')
                    approved=page.locator('#presend-payload').text_content()
                    assert approved.endswith(original)
                    assert 'Approved summary:' in approved
                    assert page.locator('#presend-original').text_content()==original
                    page.locator('#presend-approve').click()
                    page.locator('#presend-dialog').wait_for(state='hidden')
                    assert contents()==[approved],(contents(),approved)
                    assert page.locator('#system-input').input_value()==''
                    assert page.locator('#processing-objective').text_content()==approved

                    # C: review can send original without any summary wrapper.
                    plain='No labeled headings, but preserve this text exactly!  '
                    page.locator('#system-input').fill(plain)
                    page.locator('#send-system').click()
                    page.get_by_role('dialog').wait_for(state='visible')
                    assert page.locator('#presend-summary').input_value()==''
                    assert page.locator('#presend-payload').text_content()==plain
                    page.locator('#presend-approve').click()
                    page.locator('#presend-dialog').wait_for(state='hidden')
                    assert contents()==[approved,plain]

                    # D: turn review off; direct send still works unchanged.
                    page.locator('#presend-enabled').uncheck()
                    direct='Direct System Chat, no review requested'
                    page.locator('#system-input').fill(direct)
                    page.locator('#send-system').click()
                    page.get_by_text(direct,exact=True).first.wait_for()
                    assert contents()==[approved,plain,direct]
                    assert not console_errors,console_errors
                    print('PRESEND_BROWSER_E2E_PASS cancel=0 approved_exact=1 original_preserved=1 direct_send=1')
                finally:
                    browser.close()
        finally:
            stop(proc)

if __name__=='__main__':run()
