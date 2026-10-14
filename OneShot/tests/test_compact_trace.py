"""Heavy event histories must be projectable without returning all events."""
from systems.store import Store, emit
from systems.contracts import ConversationCreate, JobCreate, InputSource, MessageCreate
from systems.operations import create_conversation, add_message, source_action, admit, trace


def test_trace_can_project_many_events_without_returning_history(tmp_path):
    store=Store(tmp_path)
    cid=create_conversation(store,ConversationCreate())['id']
    msg=add_message(store,cid,MessageCreate(channel='system',content='Audit event replay.'))['id']
    src=source_action(store,cid,InputSource(action='INPUT_SOURCE',name='source.txt',content='Evidence'))
    job=admit(store,cid,JobCreate(operation='auto_generate',prompt_message_id=msg,
        source_ids=[src['source_id']],expected_versions={src['source_id']:1},idempotency_key='trace-large-001'))['id']
    with store.tx() as con:
        for i in range(510):
            emit(con,cid,'node_started' if i % 2 == 0 else 'node_completed',job_id=job,node_id='scanner')
    full=trace(store,cid,job)
    compact=trace(store,cid,job,include_events=False)
    assert len(full['events']) >= 510
    assert compact['events'] == []
    assert full['nodes'] == compact['nodes']
    assert full['edges'] == compact['edges']
    assert next(n['status'] for n in compact['nodes'] if n['id']=='scanner') == 'completed'
