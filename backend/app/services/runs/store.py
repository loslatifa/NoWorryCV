from __future__ import annotations

from threading import Lock
from typing import Dict, List, Optional
from uuid import uuid4

from backend.app.schemas.jd import KnowledgeReviewCard
from backend.app.schemas.run_state import TailorRunJobStatus, TailorRunResult


class InMemoryRunStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._jobs: Dict[str, TailorRunJobStatus] = {}

    def create(self, status_message: str, review_cards: Optional[List[KnowledgeReviewCard]] = None) -> TailorRunJobStatus:
        run_id = str(uuid4())
        job = TailorRunJobStatus(
            run_id=run_id,
            status="queued",
            progress_percent=0,
            current_stage="queued",
            status_message=status_message,
            review_cards=review_cards or [],
        )
        with self._lock:
            self._jobs[run_id] = job
        return job

    def get(self, run_id: str) -> Optional[TailorRunJobStatus]:
        with self._lock:
            job = self._jobs.get(run_id)
            return job.model_copy(deep=True) if job else None

    def update(self, run_id: str, **fields) -> Optional[TailorRunJobStatus]:
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None:
                return None
            updated = job.model_copy(update=fields, deep=True)
            self._jobs[run_id] = updated
            return updated.model_copy(deep=True)

    def mark_running(
        self,
        run_id: str,
        stage: str,
        percent: int,
        message: str,
        review_cards: Optional[List[KnowledgeReviewCard]] = None,
    ) -> Optional[TailorRunJobStatus]:
        fields = {
            "run_id": run_id,
            "status": "running",
            "current_stage": stage,
            "progress_percent": max(0, min(99, percent)),
            "status_message": message,
            "error_message": "",
        }
        if review_cards is not None:
            fields["review_cards"] = review_cards
        return self.update(**fields)

    def mark_completed(self, run_id: str, result: TailorRunResult, message: str) -> Optional[TailorRunJobStatus]:
        return self.update(
            run_id,
            status="completed",
            current_stage="completed",
            progress_percent=100,
            status_message=message,
            result=result,
            error_message="",
        )

    def mark_failed(self, run_id: str, message: str) -> Optional[TailorRunJobStatus]:
        return self.update(
            run_id,
            status="failed",
            current_stage="failed",
            progress_percent=100,
            status_message="任务执行失败。",
            error_message=message,
        )


_STORE = InMemoryRunStore()


def get_run_store() -> InMemoryRunStore:
    return _STORE
