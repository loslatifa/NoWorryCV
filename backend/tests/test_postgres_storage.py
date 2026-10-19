"""Integration tests use a fresh schema in TEST_DATABASE_URL; never touch app DBs."""
import json
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from uuid import uuid4

import pytest
import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

from backend.app.agents.orchestrator import ResumeTailorOrchestrator
from backend.app.core.config import reset_settings_cache
from backend.app.schemas.run_state import TailorRunInput
from backend.app.services.runs.postgres import PostgresRunStore, PostgresTaskQueue
from backend.app.services.runs.queue import DurableTaskQueue
from backend.app.services.runs.store import PersistentRunStore, get_run_store, reset_run_store_cache
from backend.app.services.db.pg_compat import PgCompatConnection
from scripts.migrate_run_storage import migrate


@pytest.fixture
def pg_url():
    url = os.environ.get('TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set TEST_DATABASE_URL to run PostgreSQL integration tests')
    schema = 'test_' + uuid4().hex
    with psycopg.connect(url, autocommit=True) as connection:
        connection.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
        try:
            yield make_conninfo(url, options=f'-c search_path={schema}')
        finally:
            reset_run_store_cache()
            connection.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


INPUT = TailorRunInput(resume_text='Test Candidate\nExperience\nAcme | Analyst\n- Built Python reports and SQL dashboards\nSkills\nPython, SQL', jd_text='Data analyst with Python and SQL', max_iterations=1, processing_mode='application')


def test_restart_draft_versions_auth_and_single_owner(pg_url):
    store = PostgresRunStore(pg_url)
    try:
        job = store.create('queued')
        with pytest.raises(RuntimeError, match='one application process'):
            PostgresRunStore(pg_url)
        result = ResumeTailorOrchestrator().run(INPUT, run_id=job.run_id)
        store.mark_completed(job.run_id, result, 'done')
        draft = result.final_package.draft.model_copy(deep=True)
        draft.summary = 'Edited summary'
        report = result.reviews[-1]
        version = store.save_draft_version(job.run_id, draft, report.compliance_report, report.ats_report, 'manual', 'edit')
    finally:
        store.close()
    reopened = PostgresRunStore(pg_url)
    try:
        restored = reopened.get_authorized(job.run_id, job.access_token)
        assert reopened.get_authorized(job.run_id, 'wrong') is None
        assert restored.result.active_version_id == version.id
        assert restored.result.final_package.draft.summary == 'Edited summary'
        assert restored.result.draft_versions[-1].id == version.id
        with psycopg.connect(pg_url) as conn:
            row = conn.execute('SELECT payload,token_hash FROM tailor_runs WHERE run_id=%s', (job.run_id,)).fetchone()
            assert job.access_token not in json.dumps(row)
        assert reopened.delete_authorized(job.run_id, job.access_token)
    finally:
        reopened.close()
    with psycopg.connect(pg_url) as conn:
        assert conn.execute('SELECT COUNT(*) FROM tailor_runs').fetchone()[0] == 0


def test_queue_idempotency_atomic_claim_checkpoint_recovery_and_cancel(pg_url):
    queue = PostgresTaskQueue(pg_url)
    expiry = '2099-01-01T00:00:00+00:00'
    for index in range(8):
        assert queue.enqueue(str(index), INPUT, f'key-{index}', expiry) is None
    assert queue.enqueue('duplicate', INPUT, 'key-0', expiry) == '0'
    with ThreadPoolExecutor(max_workers=4) as pool:
        claimed = list(pool.map(lambda _: queue._claim_next(), range(8)))
    assert len({task.run_id for task in claimed}) == 8
    task = claimed[0]
    queue.save_checkpoint(task.run_id, 'analyze_jd', 'parse_resume', {'sentinel': 42}, 20, task.attempt)
    restarted = PostgresTaskQueue(pg_url)
    assert len(restarted.recover_interrupted()) == 8
    retried = []
    for _ in range(8):
        retried.append(restarted._claim_next())
    recovered = next(item for item in retried if item.run_id == task.run_id)
    assert recovered.checkpoint_state == {'sentinel': 42}
    assert recovered.next_stage == 'parse_resume' and recovered.attempt == 2
    assert restarted.request_cancel(task.run_id)
    assert restarted.is_cancel_requested(task.run_id)
    assert restarted.retry(task.run_id)
    assert restarted.metadata(task.run_id)['status'] == 'queued'


def test_transaction_failure_rolls_back_all_statements(pg_url):
    queue = PostgresTaskQueue(pg_url)
    connection = PgCompatConnection(pg_url)
    try:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute("INSERT INTO tasks(run_id,payload_json,idempotency_key,status,max_attempts,created_at,updated_at,expires_at) VALUES (?,?,?,?,?,?,?,?)", ('rollback','{}','same','queued',3,'a','a','z'))
        with pytest.raises(Exception):
            connection.execute("INSERT INTO tasks(run_id,payload_json,idempotency_key,status,max_attempts,created_at,updated_at,expires_at) VALUES (?,?,?,?,?,?,?,?)", ('rollback2','{}','same','queued',3,'a','a','z'))
    finally:
        connection.close()
    assert queue.metadata('rollback') is None


def test_offline_migration_preserves_credentials_checkpoint_and_source(pg_url, tmp_path):
    run_path, queue_path = tmp_path/'source.json', tmp_path/'source.sqlite3'
    local = PersistentRunStore(str(run_path)); queue = DurableTaskQueue(str(queue_path))
    job = local.create('queued')
    queue.enqueue(job.run_id, INPUT, 'migration-key', job.expires_at)
    task = queue._claim_next()
    queue.save_checkpoint(job.run_id, 'analyze_jd', 'parse_resume', {'migration':True}, 5, task.attempt)
    before = (run_path.read_bytes(), queue_path.read_bytes())
    assert migrate(run_path, queue_path, pg_url) == {'runs':1,'tasks':1,'stages':1}
    assert before == (run_path.read_bytes(), queue_path.read_bytes())
    with pytest.raises(ValueError, match='empty'):
        migrate(run_path, queue_path, pg_url)
    store = PostgresRunStore(pg_url)
    try:
        assert store.get_authorized(job.run_id, job.access_token)
        assert PostgresTaskQueue(pg_url).metadata(job.run_id)['checkpoint_json'] == '{"migration": true}'
    finally:
        store.close()


def test_real_pipeline_resumes_from_saved_postgres_checkpoint(pg_url, monkeypatch):
    queue = PostgresTaskQueue(pg_url)
    queue.enqueue('resume-pipeline', INPUT, 'resume-pipeline', '2099-01-01T00:00:00+00:00')
    task = queue._claim_next()
    class Interrupted(RuntimeError): pass
    def checkpoint(stage, next_stage, state, duration):
        queue.save_checkpoint(task.run_id, stage, next_stage, state, duration, task.attempt)
        if stage == 'analyze_jd': raise Interrupted()
    with pytest.raises(Interrupted):
        ResumeTailorOrchestrator().run_resumable(INPUT, task.run_id, checkpoint_callback=checkpoint)
    restarted = PostgresTaskQueue(pg_url)
    assert restarted.recover_interrupted() == [task.run_id]
    recovered = restarted._claim_next()
    orchestrator = ResumeTailorOrchestrator()
    monkeypatch.setattr(orchestrator, '_analyze_jd_node', lambda *a, **kw: pytest.fail('Completed stage must not rerun'))
    result = orchestrator.run_resumable(INPUT, task.run_id, checkpoint_state=recovered.checkpoint_state, next_stage=recovered.next_stage)
    assert result.final_package.draft.markdown


def test_postgres_api_job_generation_and_version_save(pg_url, monkeypatch):
    import time
    from fastapi.testclient import TestClient
    from backend.app.main import create_app
    monkeypatch.setenv('DATABASE_URL', pg_url)
    reset_settings_cache(); reset_run_store_cache()
    with TestClient(create_app()) as client:
        response = client.post('/api/v1/tailor-runs/upload-jobs',
            files={'resume_file':('resume.txt',INPUT.resume_text.encode(),'text/plain')},
            data={'jd_text':INPUT.jd_text,'max_iterations':'1','processing_mode':'application'})
        assert response.status_code == 200, response.text
        submitted = response.json(); headers={'X-Run-Token':submitted['access_token']}
        for _ in range(200):
            status = client.get(f"/api/v1/tailor-runs/{submitted['run_id']}/status",headers=headers).json()
            if status['status'] in {'completed','failed'}: break
            time.sleep(.02)
        assert status['status'] == 'completed', status
        draft=status['result']['final_package']['draft']; draft['summary']='Saved via PostgreSQL API'
        saved=client.put(f"/api/v1/tailor-runs/{submitted['run_id']}/draft",headers=headers,json={'draft':draft})
        assert saved.status_code == 200, saved.text
    reopened = PostgresRunStore(pg_url)
    try:
        job = reopened.get_authorized(submitted['run_id'], submitted['access_token'])
        assert job.result.final_package.draft.summary == 'Saved via PostgreSQL API'
    finally:
        reopened.close()
