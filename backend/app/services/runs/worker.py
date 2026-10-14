from __future__ import annotations

import logging

from backend.app.agents.orchestrator import ResumeTailorOrchestrator, RunCancelledError
from backend.app.services.runs.queue import QueuedTask, TaskCancelledError, get_task_queue
from backend.app.services.runs.store import get_run_store


logger = logging.getLogger(__name__)


def process_tailor_task(task: QueuedTask) -> None:
    queue = get_task_queue()
    store = get_run_store()
    if store.get(task.run_id) is None:
        queue.delete(task.run_id)
        raise TaskCancelledError("Run data no longer exists.")

    store.update(
        task.run_id,
        attempt_count=task.attempt,
        max_attempts=task.max_attempts,
        retryable=False,
        error_type="",
        failed_stage="",
        error_message="",
    )

    def progress_callback(stage: str, percent: int, message: str, review_cards=None) -> None:
        if queue.is_cancel_requested(task.run_id):
            raise RunCancelledError("Run was cancelled by the user.")
        queue.mark_stage_running(task.run_id, stage)
        updated = store.mark_running(
            task.run_id,
            stage=stage,
            percent=percent,
            message=message,
            review_cards=review_cards,
        )
        if updated is None:
            raise RunCancelledError("Run data was deleted.")

    def checkpoint_callback(
        completed_stage: str,
        next_stage: str,
        state: dict,
        duration_ms: int,
    ) -> None:
        queue.save_checkpoint(
            task.run_id,
            completed_stage,
            next_stage,
            state,
            duration_ms,
            task.attempt,
        )
        store.update(task.run_id, stage_history=queue.stage_history(task.run_id))

    try:
        orchestrator = ResumeTailorOrchestrator(progress_callback=progress_callback)
        result = orchestrator.run_resumable(
            task.payload,
            run_id=task.run_id,
            checkpoint_state=task.checkpoint_state,
            next_stage=task.next_stage,
            checkpoint_callback=checkpoint_callback,
            should_cancel=lambda: queue.is_cancel_requested(task.run_id),
        )
        completed = store.mark_completed(task.run_id, result=result, message="简历定制完成。")
        if completed is None:
            raise TaskCancelledError("Run data was deleted before completion.")
        store.update(
            task.run_id,
            attempt_count=task.attempt,
            max_attempts=task.max_attempts,
            retryable=False,
            stage_history=queue.stage_history(task.run_id),
        )
    except RunCancelledError as exc:
        store.mark_cancelled(task.run_id)
        raise TaskCancelledError(str(exc)) from exc
    except TaskCancelledError:
        raise
    except Exception as exc:
        metadata = queue.metadata(task.run_id) or {}
        failed_stage = str(metadata.get("current_stage") or task.next_stage or "unknown")
        store.mark_failed(
            task.run_id,
            "任务在“{0}”阶段失败，可从该阶段重试。".format(failed_stage),
            stage=failed_stage,
            error_type=type(exc).__name__,
            attempt_count=task.attempt,
            max_attempts=task.max_attempts,
        )
        raise


def start_task_workers() -> None:
    queue = get_task_queue()
    store = get_run_store()

    def mark_recovered_runs(run_ids) -> None:
        for run_id in run_ids:
            metadata = queue.metadata(run_id) or {}
            if metadata.get("status") == "failed":
                store.mark_failed(
                    run_id,
                    "服务中断次数已达到上限，请重新创建任务。",
                    stage=str(metadata.get("current_stage") or "unknown"),
                    error_type="WorkerInterrupted",
                    attempt_count=int(metadata.get("attempt") or 0),
                    max_attempts=int(metadata.get("max_attempts") or 0),
                )
            else:
                store.mark_queued_for_recovery(run_id)

    queue.start(process_tailor_task, on_recovered=mark_recovered_runs)
