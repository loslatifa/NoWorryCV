from __future__ import annotations

import json
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.schemas.jd import KnowledgeReviewCard
from backend.app.schemas.review import ATSReport, ComplianceReport
from backend.app.schemas.run_state import DraftVersion, TailorRunJobStatus, TailorRunResult
from backend.app.schemas.strategy import ResumeDraft


class PersistentRunStore:
    def __init__(self, storage_path: str) -> None:
        self._lock = Lock()
        self._path = Path(storage_path)
        self._jobs: Dict[str, TailorRunJobStatus] = {}
        self._load()

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
            self._persist_locked()
        return job.model_copy(deep=True)

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
            self._persist_locked()
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
        if not result.draft_versions and result.reviews:
            latest_review = result.reviews[-1]
            result.draft_versions.append(
                DraftVersion(
                    created_at=datetime.now(timezone.utc).isoformat(),
                    source="generated",
                    label="AI 生成版本",
                    draft=result.final_package.draft.model_copy(deep=True),
                    compliance_report=latest_review.compliance_report.model_copy(deep=True),
                    ats_report=latest_review.ats_report.model_copy(deep=True),
                )
            )
        return self.update(
            run_id,
            status="completed",
            current_stage="completed",
            progress_percent=100,
            status_message=message,
            result=result,
            error_message="",
        )

    def save_draft_version(
        self,
        run_id: str,
        draft: ResumeDraft,
        compliance_report: ComplianceReport,
        ats_report: ATSReport,
        source: str,
        label: str,
    ) -> Optional[DraftVersion]:
        version = DraftVersion(
            created_at=datetime.now(timezone.utc).isoformat(),
            source=source,
            label=label,
            draft=draft.model_copy(deep=True),
            compliance_report=compliance_report.model_copy(deep=True),
            ats_report=ats_report.model_copy(deep=True),
        )
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None or job.result is None:
                return None
            result = job.result.model_copy(deep=True)
            result.final_package.draft = draft.model_copy(deep=True)
            result.drafts.append(draft.model_copy(deep=True))
            result.draft_versions.append(version)
            updated = job.model_copy(update={"result": result}, deep=True)
            self._jobs[run_id] = updated
            self._persist_locked()
        return version.model_copy(deep=True)

    def mark_failed(self, run_id: str, message: str) -> Optional[TailorRunJobStatus]:
        return self.update(
            run_id,
            status="failed",
            current_stage="failed",
            progress_percent=100,
            status_message="任务执行失败。",
            error_message=message,
        )

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        jobs = payload.get("jobs", {})
        if not isinstance(jobs, dict):
            return
        loaded: Dict[str, TailorRunJobStatus] = {}
        for run_id, job_payload in jobs.items():
            try:
                loaded[run_id] = TailorRunJobStatus.model_validate(job_payload)
            except Exception:
                continue
        self._jobs = loaded

    def _persist_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "jobs": {
                run_id: job.model_dump(mode="json")
                for run_id, job in self._jobs.items()
            }
        }
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self._path)


@lru_cache
def get_run_store() -> PersistentRunStore:
    return PersistentRunStore(get_settings().run_store_path)


def reset_run_store_cache() -> None:
    get_run_store.cache_clear()
