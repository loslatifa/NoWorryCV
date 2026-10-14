from __future__ import annotations

import json
import logging
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Callable, Dict, List, Optional

from backend.app.core.config import get_settings
from backend.app.schemas.run_state import StageExecutionRecord, TailorRunInput


logger = logging.getLogger(__name__)


class TaskCancelledError(RuntimeError):
    pass


@dataclass
class QueuedTask:
    run_id: str
    payload: TailorRunInput
    attempt: int
    max_attempts: int
    checkpoint_state: Optional[Dict]
    next_stage: str


class DurableTaskQueue:
    def __init__(self, database_path: str, worker_count: int = 1, max_attempts: int = 3) -> None:
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._worker_count = max(1, worker_count)
        self._max_attempts = max(1, max_attempts)
        self._stop_event = Event()
        self._wake_event = Event()
        self._start_lock = Lock()
        self._threads: List[Thread] = []
        self._processor: Optional[Callable[[QueuedTask], None]] = None
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self._path), timeout=15, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=15000")
        connection.execute("PRAGMA secure_delete=ON")
        return connection

    @contextmanager
    def _connection(self):
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connection() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS tasks (
                    run_id TEXT PRIMARY KEY,
                    payload_json TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL,
                    checkpoint_json TEXT,
                    next_stage TEXT NOT NULL DEFAULT 'analyze_jd',
                    current_stage TEXT NOT NULL DEFAULT 'queued',
                    cancel_requested INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT NOT NULL DEFAULT '',
                    error_message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_tasks_claim
                    ON tasks(status, created_at);
                CREATE TABLE IF NOT EXISTS stage_executions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    status TEXT NOT NULL,
                    attempt INTEGER NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    duration_ms INTEGER NOT NULL DEFAULT 0,
                    error_type TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_stage_run
                    ON stage_executions(run_id, id);
                """
            )

    def start(
        self,
        processor: Callable[[QueuedTask], None],
        on_recovered: Optional[Callable[[List[str]], None]] = None,
    ) -> List[str]:
        with self._start_lock:
            if self._threads:
                return []
            self._processor = processor
            self._stop_event.clear()
            recovered = self.recover_interrupted()
            if recovered and on_recovered:
                on_recovered(recovered)
            for index in range(self._worker_count):
                thread = Thread(
                    target=self._worker_loop,
                    name="noworrycv-task-worker-{0}".format(index + 1),
                    daemon=True,
                )
                thread.start()
                self._threads.append(thread)
            self._wake_event.set()
            return recovered

    def stop(self) -> None:
        self._stop_event.set()
        self._wake_event.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._threads = []

    def enqueue(
        self,
        run_id: str,
        payload: TailorRunInput,
        idempotency_key: str,
        expires_at: str,
    ) -> Optional[str]:
        now = datetime.now(timezone.utc).isoformat()
        try:
            with self._connection() as connection:
                connection.execute(
                    """
                    INSERT INTO tasks (
                        run_id, payload_json, idempotency_key, status, max_attempts,
                        created_at, updated_at, expires_at
                    ) VALUES (?, ?, ?, 'queued', ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        payload.model_dump_json(),
                        idempotency_key,
                        self._max_attempts,
                        now,
                        now,
                        expires_at,
                    ),
                )
        except sqlite3.IntegrityError:
            with self._connection() as connection:
                row = connection.execute(
                    "SELECT run_id FROM tasks WHERE idempotency_key = ?",
                    (idempotency_key,),
                ).fetchone()
            return str(row["run_id"]) if row else ""
        self._wake_event.set()
        return None

    def recover_interrupted(self) -> List[str]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT run_id, current_stage, attempt, max_attempts
                FROM tasks WHERE status = 'running' AND cancel_requested = 0
                """
            ).fetchall()
            for row in rows:
                can_retry = int(row["attempt"]) < int(row["max_attempts"])
                connection.execute(
                    """
                    UPDATE tasks
                    SET status = ?, updated_at = ?, error_type = ?, error_message = ?
                    WHERE run_id = ?
                    """,
                    (
                        "queued" if can_retry else "failed",
                        now,
                        "" if can_retry else "WorkerInterrupted",
                        "" if can_retry else "Worker stopped before the stage completed.",
                        row["run_id"],
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO stage_executions (
                        run_id, stage, status, attempt, started_at, finished_at, duration_ms, error_type
                    ) VALUES (?, ?, 'interrupted', ?, ?, ?, 0, 'WorkerInterrupted')
                    """,
                    (
                        row["run_id"],
                        row["current_stage"] or "unknown",
                        row["attempt"],
                        now,
                        now,
                    ),
                )
        return [str(row["run_id"]) for row in rows]

    def save_checkpoint(
        self,
        run_id: str,
        completed_stage: str,
        next_stage: str,
        state: Dict,
        duration_ms: int,
        attempt: int,
    ) -> None:
        finished = datetime.now(timezone.utc)
        started = datetime.fromtimestamp(
            finished.timestamp() - max(0, duration_ms) / 1000,
            tz=timezone.utc,
        )
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE tasks
                SET checkpoint_json = ?, next_stage = ?, current_stage = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (
                    json.dumps(state, ensure_ascii=False),
                    next_stage,
                    next_stage or "completed",
                    finished.isoformat(),
                    run_id,
                ),
            )
            if cursor.rowcount == 0:
                connection.execute("ROLLBACK")
                raise TaskCancelledError("Task was deleted before checkpointing.")
            connection.execute(
                """
                INSERT INTO stage_executions (
                    run_id, stage, status, attempt, started_at, finished_at, duration_ms
                ) VALUES (?, ?, 'completed', ?, ?, ?, ?)
                """,
                (
                    run_id,
                    completed_stage,
                    attempt,
                    started.isoformat(),
                    finished.isoformat(),
                    max(0, duration_ms),
                ),
            )
            connection.execute("COMMIT")

    def mark_stage_running(self, run_id: str, stage: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                "UPDATE tasks SET current_stage = ?, updated_at = ? WHERE run_id = ? AND status = 'running'",
                (stage, now, run_id),
            )

    def mark_completed(self, run_id: str) -> None:
        self._set_status(run_id, "completed", current_stage="completed")

    def mark_failed(self, run_id: str, stage: str, error_type: str, message: str, attempt: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE tasks
                SET status = 'failed', current_stage = ?, error_type = ?, error_message = ?, updated_at = ?
                WHERE run_id = ?
                """,
                (stage, error_type, message, now, run_id),
            )
            connection.execute(
                """
                INSERT INTO stage_executions (
                    run_id, stage, status, attempt, started_at, finished_at, duration_ms, error_type
                ) VALUES (?, ?, 'failed', ?, ?, ?, 0, ?)
                """,
                (run_id, stage or "unknown", attempt, now, now, error_type),
            )
            connection.execute("COMMIT")

    def request_cancel(self, run_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET cancel_requested = 1, status = 'cancelled', updated_at = ?
                WHERE run_id = ? AND status IN ('queued', 'running', 'failed')
                """,
                (now, run_id),
            )
        self._wake_event.set()
        return cursor.rowcount > 0

    def retry(self, run_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET status = 'queued', cancel_requested = 0, error_type = '', error_message = '', updated_at = ?
                WHERE run_id = ? AND status IN ('failed', 'cancelled') AND attempt < max_attempts
                """,
                (now, run_id),
            )
        if cursor.rowcount:
            self._wake_event.set()
        return cursor.rowcount > 0

    def is_cancel_requested(self, run_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT cancel_requested FROM tasks WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        return row is None or bool(row["cancel_requested"])

    def metadata(self, run_id: str) -> Optional[Dict]:
        with self._connection() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        return dict(row)

    def stage_history(self, run_id: str) -> List[StageExecutionRecord]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT stage, status, attempt, started_at, finished_at, duration_ms, error_type
                FROM stage_executions WHERE run_id = ? ORDER BY id
                """,
                (run_id,),
            ).fetchall()
        return [StageExecutionRecord.model_validate(dict(row)) for row in rows]

    def delete(self, run_id: str) -> None:
        with self._connection() as connection:
            connection.execute("DELETE FROM stage_executions WHERE run_id = ?", (run_id,))
            connection.execute("DELETE FROM tasks WHERE run_id = ?", (run_id,))

    def cleanup_expired(self) -> int:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            rows = connection.execute("SELECT run_id FROM tasks WHERE expires_at <= ?", (now,)).fetchall()
            for row in rows:
                connection.execute("DELETE FROM stage_executions WHERE run_id = ?", (row["run_id"],))
            cursor = connection.execute("DELETE FROM tasks WHERE expires_at <= ?", (now,))
        return cursor.rowcount

    def _set_status(self, run_id: str, status: str, current_stage: str) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE tasks SET status = ?, current_stage = ?, updated_at = ? WHERE run_id = ?
                """,
                (status, current_stage, now, run_id),
            )

    def _claim_next(self) -> Optional[QueuedTask]:
        now = datetime.now(timezone.utc).isoformat()
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM tasks
                WHERE status = 'queued' AND cancel_requested = 0
                    AND attempt < max_attempts AND expires_at > ?
                ORDER BY created_at LIMIT 1
                """,
                (now,),
            ).fetchone()
            if row is None:
                connection.execute("COMMIT")
                return None
            attempt = int(row["attempt"]) + 1
            connection.execute(
                """
                UPDATE tasks
                SET status = 'running', attempt = ?, current_stage = next_stage, updated_at = ?
                WHERE run_id = ?
                """,
                (attempt, now, row["run_id"]),
            )
            connection.execute("COMMIT")
        checkpoint = json.loads(row["checkpoint_json"]) if row["checkpoint_json"] else None
        return QueuedTask(
            run_id=str(row["run_id"]),
            payload=TailorRunInput.model_validate_json(row["payload_json"]),
            attempt=attempt,
            max_attempts=int(row["max_attempts"]),
            checkpoint_state=checkpoint,
            next_stage=str(row["next_stage"] or "analyze_jd"),
        )

    def _worker_loop(self) -> None:
        while not self._stop_event.is_set():
            task = self._claim_next()
            if task is None:
                self._wake_event.wait(timeout=0.5)
                self._wake_event.clear()
                continue
            try:
                if self._processor is None:
                    raise RuntimeError("Task queue processor is not configured.")
                self._processor(task)
                if self.is_cancel_requested(task.run_id):
                    raise TaskCancelledError("Task was cancelled.")
                self.mark_completed(task.run_id)
            except TaskCancelledError:
                self._set_status(task.run_id, "cancelled", current_stage="cancelled")
            except Exception as exc:  # pragma: no cover - defensive worker boundary
                metadata = self.metadata(task.run_id) or {}
                stage = str(metadata.get("current_stage") or task.next_stage or "unknown")
                error_type = type(exc).__name__
                logger.exception("Durable task %s failed at %s", task.run_id, stage, exc_info=exc)
                self.mark_failed(task.run_id, stage, error_type, str(exc), task.attempt)


@lru_cache
def get_task_queue() -> DurableTaskQueue:
    settings = get_settings()
    return DurableTaskQueue(
        settings.task_queue_path,
        worker_count=settings.task_worker_count,
        max_attempts=settings.task_max_attempts,
    )


def reset_task_queue_cache() -> None:
    if get_task_queue.cache_info().currsize:
        get_task_queue().stop()
    get_task_queue.cache_clear()
