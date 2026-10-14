import json
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response

from backend.app.api.v1.routes import _get_authorized_run
from backend.app.schemas.history import (
    HistoryQuery, HistoryResponse, RunHistoryItem, RunMetadataUpdate,
    VersionComparisonRequest, VersionComparisonResponse, VersionListMutation, VersionMetadataUpdate,
)
from backend.app.schemas.run_state import DraftMutationResponse
from backend.app.services.profiles import get_candidate_archive_store
from backend.app.services.runs.store import VersionConflictError, get_run_store
from backend.app.services.runs.queue import get_task_queue
from backend.app.services.version_comparison import compare_versions

router = APIRouter(prefix="/tailor-runs", tags=["history"])


@router.post("/history", response_model=HistoryResponse)
def get_run_history(payload: HistoryQuery) -> HistoryResponse:
    store = get_run_store()
    jobs, unavailable = {}, []
    for credential in payload.runs:
        job = store.get_authorized(credential.id, credential.token)
        if job is None:
            unavailable.append(credential.id)
        else:
            jobs[job.run_id] = job
    for credential in payload.archives:
        archive = get_candidate_archive_store().get_authorized(credential.id, credential.token)
        if archive is not None:
            jobs.update({job.run_id: job for job in store.list_for_archive(archive.id)})
    items = []
    search = payload.search.strip().casefold()
    for job in jobs.values():
        if not job.jd_text:
            # Tasks saved before history support may still have their original queue input.
            metadata = get_task_queue().metadata(job.run_id)
            if metadata:
                job.jd_text = json.loads(metadata["payload_json"]).get("jd_text", "")
        title = job.target_job_title or (job.result.jd_profile.job_title if job.result else "")
        if payload.status != "all" and job.status != payload.status:
            continue
        if payload.archive_filter == "active" and job.archived:
            continue
        if payload.archive_filter == "archived" and not job.archived:
            continue
        if search and search not in " ".join([title, job.target_company, job.jd_text]).casefold():
            continue
        items.append(RunHistoryItem(
            run_id=job.run_id, candidate_archive_id=job.candidate_archive_id,
            company=job.target_company, job_title=title, jd_text=job.jd_text,
            created_at=job.created_at, expires_at=job.expires_at, status=job.status,
            archived=job.archived, version_count=len(job.result.draft_versions) if job.result else 0,
        ))
    if payload.sort in {"newest", "oldest"}:
        items.sort(key=lambda item: (item.created_at, item.run_id), reverse=payload.sort == "newest")
    else:
        attr = {"company": "company", "role": "job_title", "status": "status"}[payload.sort]
        items.sort(key=lambda item: (getattr(item, attr).casefold(), item.created_at, item.run_id))
    return HistoryResponse(items=items, unavailable_run_ids=unavailable)


@router.patch("/{run_id}/metadata", response_model=RunHistoryItem)
def update_run_metadata(run_id: str, payload: RunMetadataUpdate, x_run_token: Optional[str] = Header(None)):
    _get_authorized_run(run_id, x_run_token)
    changes = {}
    if payload.company is not None:
        changes["target_company"] = payload.company.strip()
    if payload.job_title is not None:
        changes["target_job_title"] = payload.job_title.strip()
    if payload.archived is not None:
        changes["archived"] = payload.archived
    job = get_run_store().update(run_id, **changes)
    if job is None:
        raise HTTPException(status_code=404, detail="任务已过期或不存在。")
    return RunHistoryItem(
        run_id=job.run_id, candidate_archive_id=job.candidate_archive_id,
        company=job.target_company, job_title=job.target_job_title,
        jd_text=job.jd_text, created_at=job.created_at, expires_at=job.expires_at,
        status=job.status, archived=job.archived,
        version_count=len(job.result.draft_versions) if job.result else 0,
    )


def _mutate_version(run_id, version_id, token, action, **changes):
    _get_authorized_run(run_id, token)
    try:
        mutated = get_run_store().mutate_version(run_id, version_id, action, **changes)
    except VersionConflictError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if mutated is None:
        raise HTTPException(status_code=404, detail="版本不存在或已删除。")
    return mutated


@router.patch("/{run_id}/draft-versions/{version_id}", response_model=VersionListMutation)
def update_version_metadata(
    run_id: str, version_id: str, payload: VersionMetadataUpdate,
    x_run_token: Optional[str] = Header(None),
):
    _, result = _mutate_version(run_id, version_id, x_run_token, "metadata", **payload.model_dump())
    return VersionListMutation(versions=result.draft_versions, active_version_id=result.active_version_id)


@router.post("/{run_id}/draft-versions/{version_id}/copy", response_model=VersionListMutation)
def copy_version(run_id: str, version_id: str, x_run_token: Optional[str] = Header(None)):
    _, result = _mutate_version(run_id, version_id, x_run_token, "copy")
    return VersionListMutation(versions=result.draft_versions, active_version_id=result.active_version_id)


@router.post("/{run_id}/draft-versions/{version_id}/restore", response_model=DraftMutationResponse)
def restore_version(run_id: str, version_id: str, x_run_token: Optional[str] = Header(None)):
    version, result = _mutate_version(run_id, version_id, x_run_token, "restore")
    return DraftMutationResponse(version=version, versions=result.draft_versions)


@router.delete("/{run_id}/draft-versions/{version_id}", status_code=204)
def delete_version(run_id: str, version_id: str, x_run_token: Optional[str] = Header(None)):
    _mutate_version(run_id, version_id, x_run_token, "delete")
    return Response(status_code=204)


@router.post("/version-comparison", response_model=VersionComparisonResponse)
def compare_saved_versions(payload: VersionComparisonRequest):
    before_job = _get_authorized_run(payload.before.run_id, payload.before.access_token)
    after_job = _get_authorized_run(payload.after.run_id, payload.after.access_token)
    before = next((v for v in before_job.result.draft_versions if v.id == payload.before.version_id), None) if before_job.result else None
    after = next((v for v in after_job.result.draft_versions if v.id == payload.after.version_id), None) if after_job.result else None
    if before is None or after is None:
        raise HTTPException(status_code=404, detail="所选版本不存在或已删除。")
    return VersionComparisonResponse(
        before_label=before.label, after_label=after.label,
        before_job_title=before_job.target_job_title or before_job.result.jd_profile.job_title,
        after_job_title=after_job.target_job_title or after_job.result.jd_profile.job_title,
        differences=compare_versions(before.draft, after.draft),
    )
