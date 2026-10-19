import json
from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response

from backend.app.schemas.preferences import PreferencesSave
from backend.app.services.preferences import apply_jd_preferences, merge_preferences
from backend.app.agents.orchestrator import ResumeTailorOrchestrator
from backend.app.api.v1.routes import _llm_required_error, _start_tailor_job
from backend.app.schemas.profile import (
    CandidateArchive, CandidateArchiveSave, ProfileJobRequest, ProfileRunReference, ProfileUsage,
)
from backend.app.schemas.run_state import ResumeParsePreview, TailorRunInput, TailorRunJobStatus
from backend.app.services.follow_up_questions import build_follow_up_questions
from backend.app.services.confirmed_profile import align_confirmed_profile
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.profiles import (
    ProfileRevisionConflict, archive_resume_text, get_candidate_archive_store,
)
from backend.app.services.runs.store import get_run_store
from backend.app.services.applications import get_application_store

router = APIRouter(prefix="/candidate-profiles", tags=["candidate-profiles"])


def _get_archive(archive_id: str, token: Optional[str]) -> CandidateArchive:
    archive = get_candidate_archive_store().get_authorized(archive_id, token or "")
    if archive is None:
        raise HTTPException(status_code=404, detail="基础档案不存在或无权访问。")
    return archive


def _check_revision(archive: CandidateArchive, payload: ProfileJobRequest) -> None:
    if archive.revision != payload.expected_revision:
        raise HTTPException(status_code=409, detail="基础档案已更新，请重新载入后再创建任务。")
    if not payload.jd_text.strip():
        raise HTTPException(status_code=400, detail="请填写目标 JD。")


@router.post("", response_model=CandidateArchive, status_code=201)
def create_profile(payload: CandidateArchiveSave) -> CandidateArchive:
    return get_candidate_archive_store().create(payload)


@router.get("/{archive_id}", response_model=CandidateArchive)
def get_profile(archive_id: str, x_profile_token: Optional[str] = Header(None)) -> CandidateArchive:
    return _get_archive(archive_id, x_profile_token)


@router.put("/{archive_id}", response_model=CandidateArchive)
def update_profile(
    archive_id: str, payload: CandidateArchiveSave, x_profile_token: Optional[str] = Header(None),
) -> CandidateArchive:
    try:
        archive = get_candidate_archive_store().update_authorized(archive_id, x_profile_token or "", payload)
    except ProfileRevisionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if archive is None:
        raise HTTPException(status_code=404, detail="基础档案不存在或无权访问。")
    return archive


@router.patch("/{archive_id}/preferences", response_model=CandidateArchive)
def save_profile_preferences(archive_id: str, payload: PreferencesSave,
                             x_profile_token: Optional[str] = Header(None)):
    try:
        archive = get_candidate_archive_store().save_preferences(archive_id, x_profile_token or "", payload)
    except ProfileRevisionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if archive is None:
        raise HTTPException(404, "基础档案不存在或无权访问。")
    return archive


@router.delete("/{archive_id}", status_code=204)
def delete_profile(archive_id: str, x_profile_token: Optional[str] = Header(None)) -> Response:
    if not get_candidate_archive_store().delete_authorized(archive_id, x_profile_token or ""):
        raise HTTPException(status_code=404, detail="基础档案不存在或无权访问。")
    get_application_store().delete_for_profile(archive_id)
    return Response(status_code=204)


@router.get("/{archive_id}/export")
def export_profile(archive_id: str, x_profile_token: Optional[str] = Header(None)) -> Response:
    archive = _get_archive(archive_id, x_profile_token)
    content = json.dumps(archive.model_dump(mode="json", exclude={"access_token"}), ensure_ascii=False, indent=2)
    return Response(
        content=content, media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="candidate-profile.json"'},
    )


@router.get("/{archive_id}/usage", response_model=ProfileUsage)
def get_profile_usage(archive_id: str, x_profile_token: Optional[str] = Header(None)) -> ProfileUsage:
    archive = _get_archive(archive_id, x_profile_token)
    references = []
    for job in get_run_store().list_for_archive(archive.id):
        jd_profile = job.result.jd_profile if job.result else None
        references.append(ProfileRunReference(
            run_id=job.run_id, profile_revision=job.candidate_archive_revision,
            status=job.status, created_at=job.created_at,
            job_title=jd_profile.job_title if jd_profile else job.target_job_title,
            affected=job.candidate_archive_revision < archive.revision,
        ))
    return ProfileUsage(current_revision=archive.revision, runs=references)


@router.post("/{archive_id}/preview", response_model=ResumeParsePreview)
def preview_profile_for_jd(
    archive_id: str, payload: ProfileJobRequest, x_profile_token: Optional[str] = Header(None),
) -> ResumeParsePreview:
    archive = _get_archive(archive_id, x_profile_token)
    _check_revision(archive, payload)
    orchestrator = ResumeTailorOrchestrator()
    candidate = archive.candidate_profile.model_copy(deep=True)
    align_confirmed_profile(candidate, archive.fact_cards)
    try:
        jd = orchestrator.jd_analyst.run(payload.jd_text)
        effective_jd = apply_jd_preferences(jd, merge_preferences(archive.preferences, payload.preferences))
        gap = orchestrator.gap_analysis.run(candidate, archive.fact_cards, effective_jd)
    except StructuredLLMError as exc:
        raise _llm_required_error(exc) from exc
    return ResumeParsePreview(
        resume_text=archive_resume_text(archive), candidate_profile=candidate,
        fact_cards=archive.fact_cards, jd_profile=jd, gap_analysis=gap,
        follow_up_questions=build_follow_up_questions(candidate, archive.fact_cards, jd, gap),
    )


@router.post("/{archive_id}/jobs", response_model=TailorRunJobStatus)
def create_profile_job(
    archive_id: str, payload: ProfileJobRequest,
    x_profile_token: Optional[str] = Header(None),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> TailorRunJobStatus:
    archive = _get_archive(archive_id, x_profile_token)
    _check_revision(archive, payload)
    run_input = TailorRunInput(
        preferences=merge_preferences(archive.preferences, payload.preferences),
        resume_text=archive_resume_text(archive), jd_text=payload.jd_text,
        candidate_notes=payload.candidate_notes, output_language=payload.output_language,
        max_iterations=payload.max_iterations,
        confirmed_candidate_profile=archive.candidate_profile,
        confirmed_fact_cards=archive.fact_cards,
        preanalyzed_jd_profile=payload.preanalyzed_jd_profile,
        target_company=payload.target_company, target_role=payload.target_role,
    )
    scoped_key = "profile:{0}:{1}".format(archive.id, idempotency_key) if idempotency_key else None
    return _start_tailor_job(run_input, scoped_key, archive.id, archive.revision)
