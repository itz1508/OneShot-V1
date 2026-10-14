"""Fault injection tests for atomic schema creation and upgrades."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from systems.store import Store, SCHEMA, execute_schema


class InterruptedStore(Store):
    fail_at = 2

    def _schema_step(self, con, script):
        # Failure after actual DDL work but before migration version commit.
        execute_schema(con, script)
        if con.execute('PRAGMA user_version').fetchone()[0] == self.fail_at:
            raise RuntimeError('simulated interruption after DDL')


def test_empty_database_migration_failure_rolls_back_all_ddl(tmp_path):
    class BrokenFresh(Store):
        def _schema_step(self, con, script):
            super()._schema_step(con, script)
            raise RuntimeError('interrupted before commit')

    with pytest.raises(RuntimeError, match='interrupted'):
        BrokenFresh(tmp_path)
    with sqlite3.connect(tmp_path / 'oneshot.sqlite3') as con:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 0
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE type='table' AND name='conversations'").fetchone()[0] == 0
    assert Store(tmp_path).one("SELECT count(*) AS n FROM conversations")['n'] == 0


def test_upgrade_failure_rolls_back_schema_and_preserves_data(tmp_path):
    root = tmp_path / 'v2'
    root.mkdir()
    db_path = root / 'oneshot.sqlite3'
    with sqlite3.connect(db_path) as con:
        execute_schema(con, SCHEMA)
        con.execute('ALTER TABLE jobs ADD COLUMN prompt_message_id TEXT REFERENCES messages(id)')
        con.execute('PRAGMA user_version=2')
        con.execute("INSERT INTO conversations VALUES('legacy','legacy title',0)")
        con.commit()

    with pytest.raises(RuntimeError, match='simulated interruption'):
        InterruptedStore(root)
    with sqlite3.connect(db_path) as con:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 2
        assert con.execute("SELECT count(*) FROM sqlite_master WHERE name='background_evaluations'").fetchone()[0] == 0
        assert con.execute("SELECT title FROM conversations WHERE id='legacy'").fetchone()[0] == 'legacy title'
    upgraded = Store(root)
    assert upgraded.one("SELECT title FROM conversations WHERE id='legacy'")['title'] == 'legacy title'
    assert upgraded.one('PRAGMA user_version')['user_version'] == 7
    assert upgraded.one("SELECT count(*) AS n FROM background_evaluations")['n'] == 0


def test_simultaneous_schema_openers_serialize(tmp_path):
    with ThreadPoolExecutor(max_workers=3) as pool:
        versions = list(pool.map(lambda _: Store(tmp_path).one('PRAGMA user_version')['user_version'], range(3)))
    assert versions == [7, 7, 7]


def test_v3_to_v4_failure_preserves_old_message_schema(tmp_path):
    from systems.store import BACKGROUND_SCHEMA
    root = tmp_path / 'v3'
    root.mkdir()
    db_path = root / 'oneshot.sqlite3'
    with sqlite3.connect(db_path) as con:
        execute_schema(con, SCHEMA)
        con.execute('ALTER TABLE jobs ADD COLUMN prompt_message_id TEXT REFERENCES messages(id)')
        execute_schema(con, BACKGROUND_SCHEMA)
        con.execute('PRAGMA user_version=3')
        con.execute("INSERT INTO conversations VALUES('legacy','retained',0)")
        con.commit()

    class InterruptedV4(Store):
        def _schema_step(self, con, script):
            execute_schema(con, script)
            if con.execute('PRAGMA user_version').fetchone()[0] == 3:
                raise RuntimeError('fault after ALTER and CREATE UNIQUE INDEX')

    with pytest.raises(RuntimeError, match='fault after ALTER'):
        InterruptedV4(root)
    with sqlite3.connect(db_path) as con:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 3
        columns = [r[1] for r in con.execute('PRAGMA table_info(messages)')]
        assert 'idempotency_key' not in columns
        assert con.execute("SELECT title FROM conversations WHERE id='legacy'").fetchone()[0] == 'retained'
    Store(root)
    with sqlite3.connect(db_path) as con:
        assert con.execute('PRAGMA user_version').fetchone()[0] == 7
        assert 'idempotency_key' in [r[1] for r in con.execute('PRAGMA table_info(messages)')]
