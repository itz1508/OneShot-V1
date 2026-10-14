"""System Background regression tests, including negative security/recovery cases."""
import json
from concurrent.futures import ThreadPoolExecutor

from systems.background import (
    BackgroundWorker, MAX_ATTEMPTS, admit_terminal, recover_background,
    report, _claim,
)
from systems.store import Store
from tests.test_workflow import admit, ingest


def _job(conversation, name='private.txt', contents='TOP_SECRET_UNTRUSTED_INPUT'):
    c,app,cid=conversation
    src=ingest(c,cid,name,contents)
    jid=admit(c,cid,[src],key='eval-'+str(len(contents))+'-'+src['source_id'][:8]).json()['id']
    return c,app,cid,src,jid


def test_background_completed_job_independent_and_private(conversation):
    c,app,cid,src,jid=_job(conversation)
    store=app.state.store
    # No new synchronous evaluation when a user job is completed.
    assert app.state.worker.step()==jid
    assert store.one('SELECT COUNT(*) AS n FROM background_evaluations')['n']==0
    background=app.state.background_worker
    assert background.step() is not None
    assert background.step() is None  # no duplicates
    report_response=c.get(f'/api/conversations/{cid}/background')
    assert report_response.status_code==200
    data=report_response.json()
    assert data['summary']['states']=={'completed':1}
    result=data['evaluations'][0]['result']
    assert result['outcome']=='recorded_consistently'
    assert result['learning_label']=='none_verified'
    assert result['semantic_quality']=='not_evaluated'
    assert all(result['checks'].values())
    assert data['learning']['model_promoted'] is False
    assert 'TOP_SECRET_UNTRUSTED_INPUT' not in report_response.text
    assert 'TOP_SECRET_UNTRUSTED_INPUT' not in json.dumps(store.all('SELECT result_json FROM background_evaluations'))
    assert c.get(f"/api/conversations/{cid}/sources/{src['source_id']}/content").content==b'TOP_SECRET_UNTRUSTED_INPUT'
    kinds=[e['kind'] for e in c.get(f'/api/conversations/{cid}/events').json()['events']]
    assert kinds[-3:]==['background_queued','background_started','background_completed']
    # The original job remains unchanged, no implicit Apply or production model promotions.
    assert c.get(f'/api/conversations/{cid}/jobs/{jid}').json()['status']=='completed'
    assert store.one('SELECT COUNT(*) AS n FROM applied')['n']==0


def test_negative_evaluation_missing_terminal_event(conversation):
    c,app,cid,src,jid=_job(conversation)
    app.state.worker.step()
    with app.state.store.tx() as con:
        con.execute("DELETE FROM events WHERE job_id=? AND kind='job_completed'",(jid,))
    app.state.background_worker.step()
    result=c.get(f'/api/conversations/{cid}/background').json()['evaluations'][0]['result']
    assert result['outcome']=='inconsistent'
    assert 'missing_terminal_event' in result['issue_codes']
    assert not result['checks']['terminal_event']


def test_deleted_source_never_becomes_learning_sample(conversation):
    c,app,cid,src,jid=_job(conversation)
    app.state.worker.step()
    with app.state.store.tx() as con:
        con.execute('UPDATE sources SET deleted=1 WHERE id=?',(src['source_id'],))
    app.state.background_worker.step()
    result=c.get(f'/api/conversations/{cid}/background').json()['evaluations'][0]
    assert result['status']=='skipped'
    assert result['result']['reason']=='source_unavailable_or_deleted'
    assert 'verified' not in str(result['result'])


def test_hash_corruption_detected_without_rewriting_original(conversation):
    c,app,cid,src,jid=_job(conversation)
    app.state.worker.step()
    path=app.state.store.files.root/src['sha256'][:2]/src['sha256']
    path.write_bytes(b'CORRUPTED_ORIGINAL')
    app.state.background_worker.step()
    result=c.get(f'/api/conversations/{cid}/background').json()['evaluations'][0]['result']
    assert result['outcome']=='inconsistent'
    assert 'source_integrity_failed' in result['issue_codes']
    assert path.read_bytes()==b'CORRUPTED_ORIGINAL'


def test_blocked_job_detected_but_not_successfully_generated(conversation):
    import base64
    c,app,cid=conversation
    src=c.post(f'/api/conversations/{cid}/sources/actions',json={
        'action':'IMPORT_SOURCE','name':'chart.png','content_base64':base64.b64encode(b'fake image').decode()}).json()
    jid=admit(c,cid,[src],key='imageback01').json()['id']
    app.state.worker.step()
    assert c.get(f'/api/conversations/{cid}/jobs/{jid}').json()['status']=='blocked'
    app.state.background_worker.step()
    result=c.get(f'/api/conversations/{cid}/background').json()['evaluations'][0]['result']
    assert result['observed_job_status']=='blocked'
    assert 'job_blocked' in result['issue_codes']
    assert result['semantic_quality']=='not_evaluated'


def test_same_job_cannot_admit_twice_under_concurrency(conversation):
    c,app,cid,src,jid=_job(conversation)
    app.state.worker.step()
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _:admit_terminal(app.state.store),range(8)))
    rows=app.state.store.all('SELECT * FROM background_evaluations')
    assert len(rows)==1
    assert rows[0]['status']=='queued'
    assert app.state.background_worker.step()==rows[0]['id']


def test_restart_recovery_fences_old_claim_and_preserves_existing_result(conversation):
    c,app,cid,src,jid=_job(conversation)
    store=app.state.store
    app.state.worker.step()
    admit_terminal(store)
    old=_claim(store)
    assert old['status']=='queued'
    assert recover_background(store)==1
    assert store.one('SELECT status,attempt FROM background_evaluations')['status']=='queued'
    worker=BackgroundWorker(Store(store.root))
    worker.step()
    row=store.one('SELECT * FROM background_evaluations')
    assert row['status']=='completed' and row['attempt']==2
    # Old pre-crash worker cannot finalize because its token has been revoked.
    with store.tx() as con:
        stale=con.execute('''UPDATE background_evaluations SET status='failed' WHERE id=?
            AND status='running' AND lease_token=?''',(row['id'],old['lease_token']))
        assert stale.rowcount==0
    assert store.one('SELECT status FROM background_evaluations')['status']=='completed'


def test_retry_is_bounded_and_does_not_break_foreground(conversation,monkeypatch):
    import systems.background as bg
    c,app,cid,src,jid=_job(conversation)
    app.state.worker.step()
    def explode(*args):raise RuntimeError('CONFIDENTIAL_PASSWORD')
    monkeypatch.setattr(bg,'_evaluate',explode)
    for _ in range(MAX_ATTEMPTS):app.state.background_worker.step()
    row=app.state.store.one('SELECT status,attempt,error_code FROM background_evaluations')
    assert row=={'status':'failed','attempt':MAX_ATTEMPTS,'error_code':'evaluation_error'}
    assert app.state.background_worker.step() is None
    assert c.get(f'/api/conversations/{cid}/jobs/{jid}').json()['status']=='completed'
    body=c.get(f'/api/conversations/{cid}/background').text
    assert 'CONFIDENTIAL_PASSWORD' not in body


def test_cid_isolation_and_auth_of_background_report(conversation):
    c,app,cid,src,jid=_job(conversation)
    app.state.worker.step();app.state.background_worker.step()
    other=c.post('/api/conversations',json={'title':'other'}).json()['id']
    assert c.get(f'/api/conversations/{other}/background').json()['summary']['total']==0
    assert c.get(f'/api/conversations/{cid}/background',headers={'Authorization':'Bearer wrong'}).status_code==401
    assert c.get(f'/api/conversations/{cid}/background?limit=1001').status_code==422
    assert c.get('/api/conversations/'+'0'*32+'/background').status_code==404


def test_repeated_patterns_are_proposals_not_policies(conversation):
    c,app,cid=conversation
    import base64
    for idx in range(2):
        src=c.post(f'/api/conversations/{cid}/sources/actions',json={
            'action':'IMPORT_SOURCE','name':f'visual{idx}.png',
            'content_base64':base64.b64encode(b'data').decode()}).json()
        jid=admit(c,cid,[src],key=f'visual-{idx}-123').json()['id']
        app.state.worker.step();app.state.background_worker.step()
    data=c.get(f'/api/conversations/{cid}/background').json()
    assert any(p['code']=='job_blocked' and p['count']==2 and p['status']=='proposal_only' for p in data['patterns'])
    assert data['summary']['production_promotions']==0
    assert data['summary']['verified_semantic_labels']==0


def test_reopen_existing_schema_v2_migrates_without_data_loss(tmp_path):
    from systems.store import SCHEMA
    import sqlite3
    path=tmp_path/'migration';path.mkdir()
    con=sqlite3.connect(path/'oneshot.sqlite3')
    con.executescript(SCHEMA)
    con.execute('ALTER TABLE jobs ADD COLUMN prompt_message_id TEXT REFERENCES messages(id)')
    con.execute('PRAGMA user_version=2')
    con.execute("INSERT INTO conversations(id,title) VALUES('legacy','preserved')")
    con.commit();con.close()
    s=Store(path)
    assert s.one('SELECT title FROM conversations WHERE id=?',('legacy',))['title']=='preserved'
    assert s.one("SELECT COUNT(*) AS n FROM background_evaluations")['n']==0
    with s.connection() as con:
        assert con.execute('PRAGMA user_version').fetchone()[0]==7


def test_foreground_priority_defers_background_until_idle(conversation):
    c,app,cid,src,first=_job(conversation)
    assert app.state.worker.step()==first
    second=admit(c,cid,[src],key='prioritysecond01').json()['id']
    # An accepted foreground request prevents optional background admission.
    assert app.state.background_worker.step() is None
    assert app.state.store.one('SELECT COUNT(*) AS n FROM background_evaluations')['n']==0
    assert app.state.worker.step()==second
    assert app.state.background_worker.step() is not None
    assert app.state.background_worker.step() is not None
    assert app.state.background_worker.step() is None


def test_interrupted_foreground_job_is_not_false_terminal_gap(conversation):
    from systems.operations import recover
    from systems.store import uid
    c,app,cid,src,jid=_job(conversation)
    with app.state.store.tx() as con:
        con.execute("UPDATE jobs SET status='running' WHERE id=?",(jid,))
        con.execute("INSERT INTO runs(id,job_id,attempt,status,started_at) VALUES(?,?,1,'running',?)",
                    (uid(),jid,'before-restart'))
    recover(app.state.store)
    assert app.state.background_worker.step() is not None
    result=c.get(f'/api/conversations/{cid}/background').json()['evaluations'][0]['result']
    assert result['checks']['terminal_event'] is True
    assert result['observed_job_status']=='failed'
    assert 'job_failed' in result['issue_codes']
