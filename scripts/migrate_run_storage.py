"""Copy an offline JSON run store and SQLite queue to an empty PostgreSQL DB.

Source files are read-only. Run against a backup while the source app is stopped.
The import is atomic, and refuses nonempty targets or an active app owner.
"""
import argparse
import json
import sqlite3
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from backend.app.core.config import get_settings
from backend.app.schemas.run_state import TailorRunJobStatus
from backend.app.services.runs.postgres import PostgresRunStore, RUNS_DDL
from backend.app.services.runs.queue import DurableTaskQueue


def migrate(run_path: Path, queue_path: Path, database_url: str):
    payload = json.loads(run_path.read_text())
    jobs = {run_id: TailorRunJobStatus.model_validate(value) for run_id, value in payload['jobs'].items()}
    if any(key != job.run_id for key, job in jobs.items()):
        raise ValueError('Source run IDs do not match their payloads')
    with sqlite3.connect(queue_path.resolve().as_uri() + '?mode=ro', uri=True) as source:
        source.row_factory = sqlite3.Row
        tasks = [dict(row) for row in source.execute('SELECT * FROM tasks')]
        stages = [dict(row) for row in source.execute('SELECT * FROM stage_executions ORDER BY id')]
    if any(row['run_id'] not in jobs for row in tasks + stages):
        raise ValueError('Queue contains orphan task or stage records; reconcile the backup before import')
    hashes = payload.get('access_token_hashes', {})
    with psycopg.connect(database_url) as target:
        locked = target.execute('SELECT pg_try_advisory_xact_lock(%s)', (PostgresRunStore.OWNER_LOCK,)).fetchone()[0]
        if not locked:
            raise ValueError('Target database has an active application; stop it before migration')
        for statement in (RUNS_DDL + DurableTaskQueue.schema_sql().replace('INTEGER PRIMARY KEY AUTOINCREMENT', 'BIGSERIAL PRIMARY KEY')).split(';'):
            if statement.strip():
                target.execute(statement)
        for table in ['tailor_runs', 'tasks', 'stage_executions']:
            if target.execute(sql.SQL('SELECT EXISTS(SELECT 1 FROM {})').format(sql.Identifier(table))).fetchone()[0]:
                raise ValueError('Target tables must be empty; migration never overwrites existing data')
        for run_id, job in jobs.items():
            target.execute('INSERT INTO tailor_runs(run_id,payload,token_hash,expires_at) VALUES (%s,%s,%s,%s)',
                           (run_id, Jsonb(job.model_dump(mode='json', exclude={'access_token'})), hashes.get(run_id, ''), job.expires_at))
        for table, rows in [('tasks', tasks), ('stage_executions', stages)]:
            for row in rows:
                columns = list(row)
                statement = sql.SQL('INSERT INTO {} ({}) VALUES ({})').format(
                    sql.Identifier(table), sql.SQL(',').join(map(sql.Identifier, columns)),
                    sql.SQL(',').join(sql.Placeholder() for _ in columns))
                target.execute(statement, [row[column] for column in columns])
        if stages:
            target.execute("SELECT setval(pg_get_serial_sequence('stage_executions','id'), (SELECT MAX(id) FROM stage_executions))")
    return {'runs': len(jobs), 'tasks': len(tasks), 'stages': len(stages)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-store', type=Path, required=True)
    parser.add_argument('--task-queue', type=Path, required=True)
    args = parser.parse_args()
    database_url = get_settings().database_url
    if not database_url:
        parser.error('Set DATABASE_URL to a dedicated empty target database')
    print(json.dumps(migrate(args.run_store, args.task_queue, database_url)))


if __name__ == '__main__':
    main()
