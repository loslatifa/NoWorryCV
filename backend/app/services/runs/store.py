from __future__ import annotations

import json
import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from hmac import compare_digest
from pathlib import Path
from threading import Lock
from typing import Dict, List, Optional
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.schemas.jd import KnowledgeReviewCard
from backend.app.schemas.review import ATSReport, ComplianceReport
from backend.app.schemas.run_state import DraftVersion, TailorRunJobStatus, TailorRunResult
from backend.app.schemas.strategy import ResumeDraft
from backend.app.services.profiles import get_candidate_archive_store
from backend.app.services.materials import get_material_store
from backend.app.services.interviews import get_interview_store
from backend.app.services.provenance import capture_provenance
from backend.app.services.quality import get_quality_store, record_event


class VersionConflictError(ValueError):
    pass


class PersistentRunStore:
    def __init__(self, storage_path: str, anonymous_ttl_hours: int = 24) -> None:
        self._lock = Lock()
        self._path = Path(storage_path)
        self._anonymous_ttl_hours = max(1, anonymous_ttl_hours)
        self._jobs: Dict[str, TailorRunJobStatus] = {}
        self._access_token_hashes: Dict[str, str] = {}
        self._load()

    def create(self, status_message: str, review_cards: Optional[List[KnowledgeReviewCard]] = None, provenance=None) -> TailorRunJobStatus:
        run_id = str(uuid4())
        access_token = secrets.token_urlsafe(32)
        now = datetime.now(timezone.utc)
        job = TailorRunJobStatus(
            run_id=run_id,
            created_at=now.isoformat(),
            expires_at=(now + timedelta(hours=self._anonymous_ttl_hours)).isoformat(),
            status="queued",
            progress_percent=0,
            current_stage="queued",
            status_message=status_message,
            review_cards=review_cards or [],
            provenance=provenance or capture_provenance(),
        )
        with self._lock:
            self._cleanup_expired_locked(now)
            self._jobs[run_id] = job
            self._access_token_hashes[run_id] = self._hash_token(access_token)
            self._persist_locked()
        record_event(job, "started", event_id=run_id + ":started")
        return job.model_copy(update={"access_token": access_token}, deep=True)

    def get(self, run_id: str) -> Optional[TailorRunJobStatus]:
        with self._lock:
            if self._cleanup_expired_locked():
                self._persist_locked()
            job = self._jobs.get(run_id)
            return job.model_copy(deep=True) if job else None

    def get_authorized(self, run_id: str, access_token: str) -> Optional[TailorRunJobStatus]:
        with self._lock:
            if self._cleanup_expired_locked():
                self._persist_locked()
            job = self._jobs.get(run_id)
            if job is None or not self._is_authorized_locked(job, access_token):
                return None
            return job.model_copy(deep=True)

    def _is_authorized_locked(self, job: TailorRunJobStatus, token: str) -> bool:
        if not token:
            return False
        expected_hash = self._access_token_hashes.get(job.run_id, "")
        if expected_hash and compare_digest(expected_hash, self._hash_token(token)):
            return True
        return bool(job.candidate_archive_id and get_candidate_archive_store().get_authorized(
            job.candidate_archive_id, token,
        ))

    def list_for_archive(self, archive_id: str) -> List[TailorRunJobStatus]:
        """Call only after authorizing access to the archive; never return run credentials."""
        with self._lock:
            if self._cleanup_expired_locked():
                self._persist_locked()
            return [job.model_copy(deep=True) for job in self._jobs.values()
                    if job.candidate_archive_id == archive_id]

    def delete_authorized(self, run_id: str, access_token: str) -> bool:
        with self._lock:
            self._cleanup_expired_locked()
            job = self._jobs.get(run_id)
            if job is None or not self._is_authorized_locked(job, access_token):
                return False
            existed = self._jobs.pop(run_id, None) is not None
            self._access_token_hashes.pop(run_id, None)
            if existed:
                self._persist_locked()
                get_quality_store().delete_run(run_id)
                get_interview_store().delete_for_run(run_id)
                get_material_store().delete_for_run(run_id)
            return existed

    def cleanup_expired(self) -> int:
        with self._lock:
            removed = self._cleanup_expired_locked()
            if removed:
                self._persist_locked()
            return removed

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
            generated_drafts = result.drafts or [result.final_package.draft]
            for index, draft in enumerate(generated_drafts):
                review = result.reviews[min(index, len(result.reviews) - 1)]
                result.draft_versions.append(DraftVersion(
                    created_at=datetime.now(timezone.utc).isoformat(),
                    source="generated",
                    label="AI 生成版本" if len(generated_drafts) == 1 else "AI 第 {0} 轮".format(index + 1),
                    draft=draft.model_copy(deep=True),
                    compliance_report=review.compliance_report.model_copy(deep=True),
                    ats_report=review.ats_report.model_copy(deep=True),
                    provenance=result.provenance.model_copy(deep=True),
                ))
        if result.draft_versions:
            result.active_version_id = result.draft_versions[-1].id
        job = self.get(run_id)
        completed = self.update(
            run_id,
            status="completed",
            current_stage="completed",
            progress_percent=100,
            status_message=message,
            result=result,
            error_message="",
            target_job_title=(job.target_job_title if job else "") or result.jd_profile.job_title,
        )
        if completed:
            record_event(completed, "completed", result.active_version_id, event_id=run_id + ":completed")
        return completed

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
            provenance=capture_provenance("partial_rewrite" if source == "ai_partial" else "manual_edit"),
        )
        with self._lock:
            job = self._jobs.get(run_id)
            if job is None or job.result is None:
                return None
            result = job.result.model_copy(deep=True)
            result.final_package.draft = draft.model_copy(deep=True)
            result.drafts.append(draft.model_copy(deep=True))
            result.draft_versions.append(version)
            result.active_version_id = version.id
            updated = job.model_copy(update={"result": result}, deep=True)
            self._jobs[run_id] = updated
            self._persist_locked()
        if source == "manual" and draft.model_dump(exclude={"markdown", "traceability"}) != job.result.final_package.draft.model_dump(exclude={"markdown", "traceability"}):
            record_event(updated, "edit", version.id)
        return version.model_copy(deep=True)

    def mutate_version(self, run_id: str, version_id: str, action: str, **changes):
        """Apply a version operation atomically without overwriting concurrent draft saves."""
        with self._lock:
            if self._cleanup_expired_locked():
                self._persist_locked()
            job = self._jobs.get(run_id)
            if job is None or job.result is None:
                return None
            result = job.result.model_copy(deep=True)
            version = next((item for item in result.draft_versions if item.id == version_id), None)
            if version is None:
                return None
            active_id = result.active_version_id or result.draft_versions[-1].id
            if action == "delete" or (action == "metadata" and changes.get("archived")):
                if version_id == active_id:
                    raise VersionConflictError("当前使用的版本不能归档或删除，请先恢复另一个版本。")
            if action == "metadata":
                if changes.get("label") is not None:
                    version.label = changes["label"]
                if changes.get("archived") is not None:
                    version.archived = changes["archived"]
            elif action == "copy":
                version = version.model_copy(update={
                    "id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
                    "source": "copied", "label": (version.label[:75] + " · 副本"), "archived": False,
                }, deep=True)
                result.draft_versions.append(version)
            elif action == "restore":
                version.archived = False
                result.active_version_id = version.id
                result.final_package.draft = version.draft.model_copy(deep=True)
            elif action == "delete":
                result.draft_versions = [item for item in result.draft_versions if item.id != version_id]
                if not any(item.draft == version.draft for item in result.draft_versions):
                    result.drafts = [draft for draft in result.drafts if draft != version.draft]
            else:
                raise ValueError("Unsupported version action")
            self._jobs[run_id] = job.model_copy(update={"result": result}, deep=True)
            self._persist_locked()
            if action == "delete":
                get_quality_store().delete_version(run_id, version_id)
            return version.model_copy(deep=True), result.model_copy(deep=True)

    def mark_failed(
        self,
        run_id: str,
        message: str,
        stage: str = "",
        error_type: str = "",
        attempt_count: int = 0,
        max_attempts: int = 3,
    ) -> Optional[TailorRunJobStatus]:
        return self.update(
            run_id,
            status="failed",
            current_stage="failed",
            progress_percent=100,
            status_message="任务执行失败。",
            error_message=message,
            failed_stage=stage,
            error_type=error_type,
            attempt_count=attempt_count,
            max_attempts=max_attempts,
            retryable=attempt_count < max_attempts,
        )

    def mark_queued_for_recovery(self, run_id: str) -> Optional[TailorRunJobStatus]:
        return self.update(
            run_id,
            status="queued",
            status_message="服务已恢复，任务将从最近完成阶段继续。",
            error_message="",
            error_type="",
            retryable=False,
        )

    def mark_cancelled(self, run_id: str) -> Optional[TailorRunJobStatus]:
        return self.update(
            run_id,
            status="cancelled",
            current_stage="cancelled",
            status_message="任务已取消，可选择从最近完成阶段重试。",
            error_message="",
            error_type="",
            retryable=True,
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
                result = loaded[run_id].result
                if result and result.draft_versions and not result.active_version_id:
                    result.active_version_id = result.draft_versions[-1].id
            except Exception:
                continue
        self._jobs = loaded
        token_hashes = payload.get("access_token_hashes", {})
        if isinstance(token_hashes, dict):
            self._access_token_hashes = {
                run_id: value
                for run_id, value in token_hashes.items()
                if run_id in self._jobs and isinstance(value, str)
            }
        self.cleanup_expired()

    def _cleanup_expired_locked(self, now: Optional[datetime] = None) -> int:
        current_time = now or datetime.now(timezone.utc)
        expired_ids = []
        for run_id, job in self._jobs.items():
            try:
                expires_at = datetime.fromisoformat(job.expires_at)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                expired_ids.append(run_id)
                continue
            if expires_at <= current_time:
                expired_ids.append(run_id)
        for run_id in expired_ids:
            self._jobs.pop(run_id, None)
            self._access_token_hashes.pop(run_id, None)
            get_quality_store().delete_run(run_id)
            get_interview_store().delete_for_run(run_id)
            get_material_store().delete_for_run(run_id)
        return len(expired_ids)

    @staticmethod
    def _hash_token(access_token: str) -> str:
        return hashlib.sha256(access_token.encode("utf-8")).hexdigest()

    def _persist_locked(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "jobs": {
                run_id: job.model_dump(mode="json")
                for run_id, job in self._jobs.items()
            },
            "access_token_hashes": dict(self._access_token_hashes),
        }
        temp_path = self._path.with_suffix(self._path.suffix + ".tmp")
        temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(self._path)


@lru_cache
def get_run_store() -> PersistentRunStore:
    settings = get_settings()
    if settings.database_url:
        from backend.app.services.runs.postgres import PostgresRunStore
        return PostgresRunStore(settings.database_url, settings.anonymous_run_ttl_hours)
    return PersistentRunStore(settings.run_store_path, settings.anonymous_run_ttl_hours)


def reset_run_store_cache() -> None:
    if get_run_store.cache_info().currsize:
        close = getattr(get_run_store(), "close", None)
        if close:
            close()
    get_run_store.cache_clear()
