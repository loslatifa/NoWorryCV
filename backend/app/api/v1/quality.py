import hashlib
import json
from typing import Optional

from fastapi import APIRouter, Header, HTTPException

from backend.app.api.v1.routes import _get_authorized_run
from backend.app.schemas.quality import DecisionRequest, FeedbackRecord, FeedbackRequest, QualityDashboard, QualityQuery
from backend.app.services.draft_diff import build_draft_diff
from backend.app.services.profiles import get_candidate_archive_store
from backend.app.services.quality import get_quality_store, record_event
from backend.app.services.runs.store import get_run_store

router = APIRouter(tags=["quality"])


def validate_target(job, version_id, target_id=""):
    if job.result is None:
        raise HTTPException(409, "任务尚未生成完成。")
    version = next((item for item in job.result.draft_versions if item.id == version_id), None)
    if version is None:
        raise HTTPException(404, "所评价的简历版本不存在或已删除。")
    identity = [version.id, "result"]
    if target_id:
        diff = build_draft_diff(job.result.candidate_profile, job.result.fact_cards, version.draft)
        target = next((item for item in diff.items if item.id == target_id), None)
        if target is None:
            raise HTTPException(422, "该修改项不属于所选版本。请保存草稿并刷新对比后反馈。")
        identity = [version.id, target.id, target.original_text, target.revised_text]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode("utf-8")).hexdigest(), version


@router.post("/tailor-runs/{run_id}/feedback", response_model=FeedbackRecord)
def submit_feedback(run_id: str, payload: FeedbackRequest, x_run_token: Optional[str] = Header(None)):
    job = _get_authorized_run(run_id, x_run_token)
    target_hash, version = validate_target(job, payload.version_id, payload.target_id)
    store = get_quality_store()
    store.ensure_run(job)
    feedback = store.feedback(run_id, payload, target_hash, version)
    record_event(job, "reviewed", payload.version_id, event_id=run_id + ":reviewed")
    return feedback


@router.get("/tailor-runs/{run_id}/feedback", response_model=list[FeedbackRecord])
def get_feedback(run_id: str, x_run_token: Optional[str] = Header(None)):
    _get_authorized_run(run_id, x_run_token)
    return get_quality_store().feedback_for_run(run_id)


@router.post("/tailor-runs/{run_id}/change-decisions")
def record_change_decision(run_id: str, payload: DecisionRequest, x_run_token: Optional[str] = Header(None)):
    job = _get_authorized_run(run_id, x_run_token)
    target_hash, _ = validate_target(job, payload.version_id, payload.target_id)
    store = get_quality_store()
    store.ensure_run(job)
    store.event(run_id, payload.decision, payload.version_id, target_hash, run_id + ":" + payload.event_id)
    store.event(run_id, "reviewed", payload.version_id, event_id=run_id + ":reviewed")
    return {"status": "recorded"}


@router.post("/quality/dashboard", response_model=QualityDashboard)
def get_dashboard(payload: QualityQuery):
    jobs, unavailable = {}, []
    run_store = get_run_store()
    for credential in payload.runs:
        job = run_store.get_authorized(credential.id, credential.token)
        if job is None:
            unavailable.append(credential.id)
        else:
            jobs[job.run_id] = job
    for credential in payload.archives:
        archive = get_candidate_archive_store().get_authorized(credential.id, credential.token)
        if archive is not None:
            jobs.update({job.run_id: job for job in run_store.list_for_archive(archive.id)})
    # Backfill truthful completion metadata for old runs; never invent user actions.
    for job in jobs.values():
        if job.result:
            record_event(job, "completed", job.result.active_version_id, event_id=job.run_id + ":completed")
        else:
            get_quality_store().ensure_run(job)
    dashboard = get_quality_store().dashboard(set(jobs), payload.hiring_track, payload.language)
    dashboard.unavailable_run_ids = unavailable
    return dashboard
