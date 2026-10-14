"""Source association and deletion must make one serialized decision."""
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from fastapi import HTTPException

from systems.contracts import AddSource, ConversationCreate, DeleteSource, InputSource
from systems.operations import create_conversation, source_action
from systems.store import Store


def test_attach_cannot_race_with_tombstone(tmp_path):
    store = Store(tmp_path)
    for _ in range(8):
        a = create_conversation(store, ConversationCreate())['id']
        b = create_conversation(store, ConversationCreate())['id']
        s = source_action(store, a, InputSource(action='INPUT_SOURCE', name='source.md', content='Evidence'))['source_id']
        barrier = Barrier(2)

        def attach():
            barrier.wait()
            try:
                source_action(store, b, AddSource(action='ADD_SOURCE', source_id=s))
                return 201
            except HTTPException as exc:
                return exc.status_code

        def delete():
            barrier.wait()
            try:
                source_action(store, a, DeleteSource(action='DELETE_SOURCE', source_id=s, confirm_delete=True))
                return 201
            except HTTPException as exc:
                return exc.status_code

        with ThreadPoolExecutor(max_workers=2) as pool:
            attached_future = pool.submit(attach)
            deleted_future = pool.submit(delete)
            attached, deleted = attached_future.result(), deleted_future.result()
        assert (attached, deleted) in ((201, 409), (404, 201))
        row = store.one('SELECT deleted FROM sources WHERE id=?', (s,))
        b_link = store.one('SELECT COUNT(*) AS n FROM source_links WHERE source_id=? AND conversation_id=?', (s, b))['n']
        assert not (row['deleted'] and b_link), 'Deleted source must never have a new link'


def test_duplicate_attach_does_not_emit_fictitious_event(tmp_path):
    store = Store(tmp_path)
    a = create_conversation(store, ConversationCreate())['id']
    b = create_conversation(store, ConversationCreate())['id']
    sid = source_action(store, a, InputSource(action='INPUT_SOURCE', name='s.txt', content='A'))['source_id']
    body = AddSource(action='ADD_SOURCE', source_id=sid)
    source_action(store, b, body)
    source_action(store, b, body)
    assert store.one("SELECT COUNT(*) AS n FROM events WHERE conversation_id=? AND kind='source_attached'", (b,))['n'] == 1
