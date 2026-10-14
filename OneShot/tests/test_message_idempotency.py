"""Message submission is deduplicated across uncertain network retries."""
import sqlite3
import pytest
from fastapi import HTTPException

from systems.contracts import ConversationCreate, MessageCreate
from systems.operations import add_message, create_conversation
from systems.store import Store


def test_message_retry_commits_once(tmp_path):
    store = Store(tmp_path)
    cid = create_conversation(store, ConversationCreate(title='Idempotency'))['id']
    submission = MessageCreate(channel='system', content='  exact\r\ntext  ', idempotency_key='review_01234567')
    first = add_message(store, cid, submission)
    retry = add_message(store, cid, submission)
    assert retry == first
    assert store.one('SELECT COUNT(*) AS n FROM messages WHERE conversation_id=?', (cid,))['n'] == 1
    saved = store.one('SELECT content FROM messages WHERE id=?',(first['id'],))
    assert saved['content'] == '  exact\r\ntext  '
    assert store.one("SELECT COUNT(*) AS n FROM events WHERE kind='message_saved' AND conversation_id=?",(cid,))['n'] == 1


def test_message_key_cannot_be_reused_for_changed_payload(tmp_path):
    store = Store(tmp_path)
    cid = create_conversation(store,ConversationCreate())['id']
    add_message(store,cid,MessageCreate(channel='system',content='original',idempotency_key='review_12345678'))
    with pytest.raises(HTTPException) as exc:
        add_message(store,cid,MessageCreate(channel='system',content='changed',idempotency_key='review_12345678'))
    assert exc.value.status_code == 409
    assert store.one('SELECT COUNT(*) AS n FROM messages')['n'] == 1


def test_keys_are_scoped_to_conversation(tmp_path):
    store=Store(tmp_path)
    a=create_conversation(store,ConversationCreate())['id']
    b=create_conversation(store,ConversationCreate())['id']
    key='same_123456'
    assert add_message(store,a,MessageCreate(channel='system',content='A',idempotency_key=key))['content']=='A'
    assert add_message(store,b,MessageCreate(channel='system',content='B',idempotency_key=key))['content']=='B'
    assert store.one('SELECT COUNT(*) AS n FROM messages')['n']==2


def test_legacy_messages_and_schema_reopen(tmp_path):
    root=tmp_path/'legacy';root.mkdir()
    s=Store(root)
    cid=create_conversation(s,ConversationCreate())['id']
    first=add_message(s,cid,MessageCreate(channel='system',content='legacy'))
    s=Store(root)
    assert s.one('SELECT content FROM messages WHERE id=?',(first['id'],))['content']=='legacy'
    with s.connection() as con:
        assert con.execute('PRAGMA user_version').fetchone()[0]==7
        assert con.execute('SELECT idempotency_key FROM messages WHERE id=?',(first['id'],)).fetchone()[0] is None
