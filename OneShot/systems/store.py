"""SQLite owner. Each transaction gets a dedicated connection, avoiding shared-cursor races."""
import sqlite3,uuid,json,time
from pathlib import Path
from datetime import datetime,timezone
from contextlib import contextmanager
from .file_store import FileStore

def uid()->str:return uuid.uuid4().hex
def timestamp()->str:return datetime.now(timezone.utc).isoformat()

SCHEMA='''
CREATE TABLE conversations(id TEXT PRIMARY KEY,title TEXT NOT NULL,agent_active INTEGER NOT NULL DEFAULT 0);
CREATE TABLE messages(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),channel TEXT NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE sources(id TEXT PRIMARY KEY,name TEXT NOT NULL,kind TEXT NOT NULL,origin TEXT,sha256 TEXT,version INTEGER NOT NULL,deleted INTEGER NOT NULL DEFAULT 0,created_at TEXT NOT NULL);
CREATE TABLE source_links(conversation_id TEXT NOT NULL REFERENCES conversations(id),source_id TEXT NOT NULL REFERENCES sources(id),PRIMARY KEY(conversation_id,source_id));
CREATE TABLE jobs(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),operation TEXT NOT NULL,scope_json TEXT NOT NULL,idempotency_key TEXT NOT NULL,status TEXT NOT NULL,error TEXT,artifact_id TEXT,created_at TEXT NOT NULL,updated_at TEXT NOT NULL,UNIQUE(conversation_id,idempotency_key));
CREATE TABLE runs(id TEXT PRIMARY KEY,job_id TEXT NOT NULL REFERENCES jobs(id),attempt INTEGER NOT NULL,status TEXT NOT NULL,error TEXT,started_at TEXT NOT NULL,ended_at TEXT,UNIQUE(job_id,attempt));
CREATE TABLE artifacts(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),job_id TEXT NOT NULL REFERENCES jobs(id),kind TEXT NOT NULL,content TEXT NOT NULL,provider TEXT NOT NULL,source_ids_json TEXT NOT NULL,limitations_json TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE TABLE events(conversation_id TEXT NOT NULL REFERENCES conversations(id),seq INTEGER NOT NULL,job_id TEXT,run_id TEXT,kind TEXT NOT NULL,node_id TEXT,edge_id TEXT,payload_json TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(conversation_id,seq));
CREATE TABLE drafts(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),source_id TEXT NOT NULL REFERENCES sources(id),revision INTEGER NOT NULL);
CREATE TABLE draft_revisions(draft_id TEXT NOT NULL REFERENCES drafts(id),revision INTEGER NOT NULL,content TEXT NOT NULL,created_at TEXT NOT NULL,PRIMARY KEY(draft_id,revision));
CREATE TABLE apply_intents(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),artifact_id TEXT NOT NULL REFERENCES artifacts(id),destination TEXT NOT NULL,expected_hash TEXT,expires_at REAL NOT NULL,state TEXT NOT NULL);
CREATE TABLE applied(id TEXT PRIMARY KEY,conversation_id TEXT NOT NULL REFERENCES conversations(id),artifact_id TEXT NOT NULL REFERENCES artifacts(id),destination TEXT NOT NULL,baseline_hash TEXT,result_hash TEXT NOT NULL,diff TEXT NOT NULL,created_at TEXT NOT NULL);
CREATE INDEX events_replay_idx ON events(conversation_id,seq);
CREATE INDEX jobs_queue_idx ON jobs(status,created_at);
'''
def execute_schema(con: sqlite3.Connection, script: str) -> None:
    """Execute DDL within the caller's transaction (executescript commits it).

    SQLite's complete_statement handles multiline CREATE statements without
    treating each individual line as a separate SQL statement.
    """
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                con.execute(statement)
            buffer = ""
    if buffer.strip():
        raise ValueError("Incomplete SQLite schema statement")




PROMPT_SCHEMA = """CREATE TABLE prompt_assets(
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    name TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(conversation_id, name)
                );
                CREATE TABLE prompt_versions(
                    id TEXT PRIMARY KEY,
                    prompt_asset_id TEXT NOT NULL REFERENCES prompt_assets(id),
                    version_number INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    variables_json TEXT NOT NULL,
                    content_sha256 TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    restored_from TEXT REFERENCES prompt_versions(id),
                    UNIQUE(prompt_asset_id, version_number)
                );
                CREATE INDEX prompt_versions_asset_idx ON prompt_versions(prompt_asset_id, version_number);
                CREATE TABLE prompt_drafts(
                    id TEXT PRIMARY KEY,
                    prompt_asset_id TEXT NOT NULL REFERENCES prompt_assets(id) UNIQUE,
                    revision INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    variables_json TEXT NOT NULL,
                    base_version_id TEXT REFERENCES prompt_versions(id),
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE prompt_evaluations(
                    id TEXT PRIMARY KEY,
                    prompt_version_id TEXT NOT NULL REFERENCES prompt_versions(id),
                    job_id TEXT REFERENCES jobs(id),
                    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','failed')),
                    criteria_json TEXT NOT NULL,
                    findings_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX prompt_evaluations_version_idx ON prompt_evaluations(prompt_version_id, created_at);
                CREATE TABLE prompt_optimizations(
                    id TEXT PRIMARY KEY,
                    prompt_asset_id TEXT NOT NULL REFERENCES prompt_assets(id),
                    base_version_id TEXT REFERENCES prompt_versions(id),
                    base_draft_revision INTEGER,
                    provider TEXT NOT NULL,
                    model TEXT,
                    proposed_content TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('proposed','accepted','rejected')),
                    created_at TEXT NOT NULL
                );
                CREATE INDEX prompt_optimizations_asset_idx ON prompt_optimizations(prompt_asset_id, created_at);
                ALTER TABLE jobs ADD COLUMN prompt_version_id TEXT REFERENCES prompt_versions(id);
                ALTER TABLE jobs ADD COLUMN resolved_variables_json TEXT;
"""

BACKGROUND_SCHEMA = """CREATE TABLE background_evaluations(
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    evaluator_version TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('queued','running','completed','skipped','failed')),
                    attempt INTEGER NOT NULL DEFAULT 0,
                    lease_token TEXT,lease_until REAL,
                    outcome TEXT,evidence_hash TEXT,
                    result_json TEXT NOT NULL DEFAULT '{}',
                    error_code TEXT,
                    created_at TEXT NOT NULL,updated_at TEXT NOT NULL,
                    UNIQUE(job_id,evaluator_version)
                );
                CREATE INDEX background_queue_idx ON background_evaluations(status,created_at);
                CREATE INDEX background_conversation_idx ON background_evaluations(conversation_id,created_at);
"""



IMPROVEMENT_LOOP_SCHEMA = """CREATE TABLE job_reviews(
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    revision INTEGER NOT NULL DEFAULT 1,
                    decision TEXT NOT NULL CHECK(decision IN
                        ('observed_defect','reviewer_expectation','potential_defect','unresolved_decision')),
                    required TEXT NOT NULL DEFAULT '',
                    prohibited TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    limitations TEXT NOT NULL DEFAULT '',
                    evidence_source_ids TEXT NOT NULL DEFAULT '[]',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(job_id)
                );
                CREATE INDEX job_reviews_conv_idx ON job_reviews(conversation_id, created_at);
                CREATE TABLE job_evaluations(
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    job_id TEXT NOT NULL REFERENCES jobs(id),
                    review_id TEXT REFERENCES job_reviews(id),
                    status TEXT NOT NULL CHECK(status IN
                        ('proposed','approved','rejected','running','completed','failed')),
                    criteria_json TEXT NOT NULL,
                    findings_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX job_evaluations_job_idx ON job_evaluations(job_id, created_at);
                CREATE TABLE improvement_proposals(
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id),
                    issue_summary TEXT NOT NULL,
                    affected_responsibility TEXT NOT NULL,
                    current_behavior TEXT NOT NULL DEFAULT '',
                    required_behavior TEXT NOT NULL DEFAULT '',
                    proposed_correction TEXT NOT NULL DEFAULT '',
                    risks TEXT NOT NULL DEFAULT '',
                    evidence_json TEXT NOT NULL DEFAULT '{}',
                    status TEXT NOT NULL CHECK(status IN
                        ('proposed','accepted','rejected','implemented')),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX improvement_proposals_conv_idx ON improvement_proposals(conversation_id, created_at);
"""


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        self.path = root / 'oneshot.sqlite3'
        self.files = FileStore(root / 'files')
        # WAL mode persists in the database. Competing first-time openers can
        # collide while switching modes; retry only SQLITE_BUSY/locked, bounded.
        for attempt in range(15):
            try:
                with self.connection() as con:
                    if con.execute('PRAGMA journal_mode').fetchone()[0].lower() != 'wal':
                        con.execute('PRAGMA journal_mode=WAL')
                break
            except sqlite3.OperationalError as exc:
                if 'locked' not in str(exc).lower() and 'busy' not in str(exc).lower():
                    raise
                if attempt == 14:
                    raise
                time.sleep(min(.03 * (attempt + 1), .25))
        # BEGIN IMMEDIATE serializes initialization across competing processes.
        # Every schema change and its recorded version commit or roll back together.
        with self.tx() as con:
            version = con.execute('PRAGMA user_version').fetchone()[0]
            if version > 7:
                raise RuntimeError(f'Database version {version} is newer than implementation')
            if version < 1:
                self._schema_step(con, SCHEMA)
                con.execute('PRAGMA user_version=1')
            if version < 2:
                self._schema_step(con, 'ALTER TABLE jobs ADD COLUMN prompt_message_id TEXT REFERENCES messages(id);')
                con.execute('PRAGMA user_version=2')
            if version < 3:
                self._schema_step(con, BACKGROUND_SCHEMA)
                con.execute('PRAGMA user_version=3')
            if version < 4:
                self._schema_step(con, """ALTER TABLE messages ADD COLUMN idempotency_key TEXT;
                    CREATE UNIQUE INDEX messages_request_key_idx
                      ON messages(conversation_id,idempotency_key) WHERE idempotency_key IS NOT NULL;""")
                con.execute('PRAGMA user_version=4')
            if version < 5:
                self._schema_step(con,"ALTER TABLE messages ADD COLUMN role TEXT NOT NULL DEFAULT 'user';")
                con.execute('PRAGMA user_version=5')
            if version < 6:
                self._schema_step(con, PROMPT_SCHEMA)
                con.execute('PRAGMA user_version=6')
            if version < 7:
                self._schema_step(con, IMPROVEMENT_LOOP_SCHEMA)
                con.execute('PRAGMA user_version=7')

    def _schema_step(self, con: sqlite3.Connection, script: str) -> None:
        """Override in injected-failure tests; always called inside Store.tx."""
        execute_schema(con, script)

    @contextmanager
    def connection(self):
        con=sqlite3.connect(self.path,timeout=5,isolation_level=None)
        con.row_factory=sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON');con.execute('PRAGMA busy_timeout=5000')
        try:yield con
        finally:con.close()
    @contextmanager
    def tx(self):
        with self.connection() as con:
            con.execute('BEGIN IMMEDIATE')
            try:yield con;con.commit()
            except BaseException:con.rollback();raise
    def one(self,sql,args=()):
        with self.connection() as con:
            r=con.execute(sql,args).fetchone();return dict(r) if r else None
    def all(self,sql,args=()):
        with self.connection() as con:return [dict(r) for r in con.execute(sql,args).fetchall()]

def emit(con,cid,kind,*,job_id=None,run_id=None,node_id=None,edge_id=None,payload=None):
    seq=con.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events WHERE conversation_id=?',(cid,)).fetchone()[0]
    con.execute('INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)',(cid,seq,job_id,run_id,kind,node_id,edge_id,json.dumps(payload or {},sort_keys=True),timestamp()))
    return seq
