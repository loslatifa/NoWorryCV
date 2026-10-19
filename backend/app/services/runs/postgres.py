"""PostgreSQL persistence for a single application process and thread workers."""
import hashlib
import json
from datetime import datetime, timezone

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend.app.schemas.run_state import TailorRunInput, TailorRunJobStatus
from backend.app.services.db.pg_compat import PgCompatConnection
from backend.app.services.runs.queue import DurableTaskQueue, QueuedTask
from backend.app.services.runs.store import PersistentRunStore


RUNS_DDL = """
CREATE TABLE IF NOT EXISTS tailor_runs (
    run_id TEXT PRIMARY KEY,
    payload JSONB NOT NULL,
    token_hash TEXT,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tailor_runs_expires ON tailor_runs(expires_at);
"""


class PostgresRunStore(PersistentRunStore):
    # One writer process per database, including across restarts/deployments.
    OWNER_LOCK = 0x4E6F576F727279

    def __init__(self, database_url, anonymous_ttl_hours=24):
        self._fingerprints = {}
        self._connection = psycopg.connect(database_url, autocommit=True, row_factory=dict_row, connect_timeout=10)
        try:
            locked = self._connection.execute('SELECT pg_try_advisory_lock(%s) AS locked', (self.OWNER_LOCK,)).fetchone()['locked']
            if not locked:
                raise RuntimeError('PostgreSQL mode supports one application process per database. Stop the other instance before starting.')
            for statement in RUNS_DDL.split(';'):
                if statement.strip():
                    self._connection.execute(statement)
            super().__init__('.dist/unused_postgres_store', anonymous_ttl_hours)
        except BaseException:
            self._connection.close()
            raise

    @staticmethod
    def _fingerprint(payload, token_hash):
        return hashlib.sha256(json.dumps([payload, token_hash], sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def _load(self):
        rows = self._connection.execute('SELECT run_id, payload, token_hash FROM tailor_runs').fetchall()
        for row in rows:
            job = TailorRunJobStatus.model_validate(row['payload'])
            if job.run_id != row['run_id']:
                raise ValueError('PostgreSQL task payload has a mismatched run ID')
            if job.result and job.result.draft_versions and not job.result.active_version_id:
                job.result.active_version_id = job.result.draft_versions[-1].id
            self._jobs[job.run_id] = job
            self._access_token_hashes[job.run_id] = row['token_hash'] or ''
            self._fingerprints[job.run_id] = self._fingerprint(row['payload'], row['token_hash'] or '')
        self.cleanup_expired()

    def _persist_locked(self):
        changes = []
        for run_id, job in self._jobs.items():
            payload = job.model_dump(mode='json', exclude={'access_token'})
            token_hash = self._access_token_hashes.get(run_id, '')
            digest = self._fingerprint(payload, token_hash)
            if digest != self._fingerprints.get(run_id):
                changes.append((run_id, payload, token_hash, job.expires_at, digest))
        removed = set(self._fingerprints) - self._jobs.keys()
        if not changes and not removed:
            return
        with self._connection.transaction():
            for run_id, payload, token_hash, expires_at, _digest in changes:
                self._connection.execute('''
                    INSERT INTO tailor_runs(run_id,payload,token_hash,expires_at)
                    VALUES (%s,%s,%s,%s)
                    ON CONFLICT(run_id) DO UPDATE SET payload=EXCLUDED.payload,
                        token_hash=EXCLUDED.token_hash,expires_at=EXCLUDED.expires_at,updated_at=now()
                ''', (run_id, Jsonb(payload), token_hash, expires_at))
            for run_id in removed:
                self._connection.execute('DELETE FROM tailor_runs WHERE run_id=%s', (run_id,))
        for run_id, _payload, _token, _expiry, digest in changes:
            self._fingerprints[run_id] = digest
        for run_id in removed:
            self._fingerprints.pop(run_id, None)

    def close(self):
        with self._lock:
            self._connection.close()


class PostgresTaskQueue(DurableTaskQueue):
    def __init__(self, database_url, worker_count=1, max_attempts=3):
        self._database_url = database_url
        super().__init__('.dist/unused_postgres_queue', worker_count, max_attempts)

    def _connect(self):
        return PgCompatConnection(self._database_url)

    def _initialize(self):
        # Keep the queue schema identical, changing only the sequence type.
        # The schema is shared so future fields cannot drift between backends.
        with self._connection() as connection:
            connection.executescript(self.schema_sql().replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY'))

    def _claim_next(self):
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            row = connection.execute('''
                UPDATE tasks SET status='running',attempt=attempt+1,
                    current_stage=next_stage,updated_at=?
                WHERE run_id=(
                    SELECT run_id FROM tasks
                    WHERE status='queued' AND cancel_requested=0
                        AND attempt<max_attempts AND expires_at>?
                    ORDER BY created_at,run_id LIMIT 1 FOR UPDATE SKIP LOCKED
                ) RETURNING *
            ''', (now, now)).fetchone()
        if row is None:
            return None
        return QueuedTask(run_id=row['run_id'], payload=TailorRunInput.model_validate_json(row['payload_json']),
                          attempt=row['attempt'], max_attempts=row['max_attempts'],
                          checkpoint_state=json.loads(row['checkpoint_json']) if row['checkpoint_json'] else None,
                          next_stage=row['next_stage'] or 'analyze_jd')
