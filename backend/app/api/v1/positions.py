from typing import Literal, Optional

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import Response

from backend.app.api.v1.profiles import _get_archive
from backend.app.api.v1.routes import _get_authorized_run, _start_tailor_job
from backend.app.schemas.position import PositionCreate, PositionGenerate, PositionInterview, PositionInterviewLink, PositionPracticeQuery, PositionRecord, PositionResume, PositionResumeLink, PositionRevision, PositionUpdate
from backend.app.schemas.run_state import TailorRunInput
from backend.app.services.applications import draft_digest, get_application_store
from backend.app.services.interviews import get_interview_store, interview_report
from backend.app.services.positions import PositionConflict, get_position_store, utc_now
from backend.app.services.preferences import export_preferences
from backend.app.services.profiles import archive_resume_text
from backend.app.services.resume_export import build_docx, build_pdf, DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE
from backend.app.services.runs.queue import get_task_queue
from backend.app.services.runs.store import get_run_store
from backend.app.schemas.position import PositionMaterial, PositionMaterialLink
from backend.app.services.materials import get_material_store, pack_zip

router = APIRouter(prefix="/candidate-profiles/{profile_id}/positions", tags=["positions"])


def record(profile_id, position_id):
    item = get_position_store().get(profile_id, position_id)
    if item is None: raise HTTPException(404, "职位不存在或无权访问。")
    return item


def mutation(call):
    try:
        item = call()
    except PositionConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if item is None: raise HTTPException(404, "职位不存在或无权访问。")
    return item


def check_revision(item, revision):
    if item.revision != revision: raise HTTPException(409, "职位已更新，请刷新后重试。")


@router.get("/sources")
def sources(profile_id: str, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    runs = [{"run_id": job.run_id, "company": job.target_company, "role": job.target_job_title,
             "status": job.status, "created_at": job.created_at, "expires_at": job.expires_at}
            for job in get_run_store().list_for_archive(profile_id)]
    applications = [{"id": item.id, "company": item.target_company, "role": item.target_role,
                     "confirmed_at": item.confirmed_at, "status": item.status}
                    for item in get_application_store().list(profile_id) if item.confirmed_at]
    return {"runs": sorted(runs, key=lambda item: item["created_at"], reverse=True), "applications": applications}


@router.post("", response_model=PositionRecord, status_code=201)
def create_position(profile_id: str, payload: PositionCreate, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    return get_position_store().create(profile_id, payload)


@router.get("")
def list_positions(profile_id: str, search: str = Query("", max_length=200),
                   status: Literal["all", "pending", "applied", "assessment", "interview", "offer", "closed"] = "all",
                   reminder: Literal["all", "none", "due", "upcoming"] = "all",
                   x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    return get_position_store().list(profile_id, search, status, reminder)


@router.get("/{position_id}", response_model=PositionRecord)
def read_position(profile_id: str, position_id: str, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    return record(profile_id, position_id)


@router.patch("/{position_id}", response_model=PositionRecord)
def update_position(profile_id: str, position_id: str, payload: PositionUpdate, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    return mutation(lambda: get_position_store().update(profile_id, position_id, payload))


@router.post("/{position_id}/jobs")
def generate_position_resume(profile_id: str, position_id: str, payload: PositionGenerate,
                             x_profile_token: Optional[str] = Header(None)):
    archive = _get_archive(profile_id, x_profile_token)
    item = record(profile_id, position_id); check_revision(item, payload.expected_revision)
    if archive.revision != payload.expected_profile_revision: raise HTTPException(409, "基础档案已更新，请刷新后重新生成。")
    job = _start_tailor_job(TailorRunInput(resume_text=archive_resume_text(archive),
        jd_text="\n".join([item.role, item.jd_text]), target_company=item.company, target_role=item.role,
        confirmed_candidate_profile=archive.candidate_profile, confirmed_fact_cards=archive.fact_cards,
        preferences=archive.preferences, max_iterations=payload.max_iterations), None, archive.id, archive.revision)
    try:
        updated = mutation(lambda: get_position_store().add_run(profile_id, position_id, payload.expected_revision, job, item.jd_text))
    except HTTPException:
        get_task_queue().delete(job.run_id); get_run_store().delete_authorized(job.run_id, x_profile_token or "")
        raise
    return {"position": updated, "job": job}


@router.post("/{position_id}/resumes", response_model=PositionRecord)
def link_resume(profile_id: str, position_id: str, payload: PositionResumeLink, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    item = record(profile_id, position_id); check_revision(item, payload.expected_revision)
    if payload.application_id:
        source = get_application_store().get(profile_id, payload.application_id)
        if source is None: raise HTTPException(404, "投递快照不存在。")
        if not source.confirmed_at or source.draft is None or source.candidate_profile is None: raise HTTPException(409, "请先在投递助手中确认简历。")
        snapshot = PositionResume(source_kind="application", run_id=source.run_id, source_profile_id=profile_id,
            profile_revision=source.profile_revision, source_company=source.target_company, source_role=source.target_role, version_id=source.version_id, application_id=source.id, label=source.target_role or "已确认投递简历", captured_at=utc_now(),
            draft_digest=source.draft_digest, draft=source.draft, candidate_profile=source.candidate_profile, fact_cards=source.fact_cards,
            jd_text=source.jd_text, jd_profile=source.jd_profile, preferences=source.preferences, resolved_language=source.resolved_language,
            risk_notes=source.risk_notes, jd_review=source.jd_review, interview_prep=source.interview_prep, provenance=source.provenance)
    else:
        job = _get_authorized_run(payload.run_id, payload.run_token or x_profile_token)
        if job.candidate_archive_id and job.candidate_archive_id != profile_id: raise HTTPException(404, "生成任务不属于当前档案。")
        if job.result is None: raise HTTPException(409, "请等待简历生成完成。")
        version = next((version for version in job.result.draft_versions if version.id == payload.version_id), None)
        if version is None: raise HTTPException(404, "已保存的简历版本不存在。")
        reports = version.compliance_report
        prepared_version = next((item for item in reversed(job.result.draft_versions) if item.source == "generated"), None)
        is_prepared_version = prepared_version is not None and version.id == prepared_version.id
        snapshot = PositionResume(source_kind="run", run_id=job.run_id, source_profile_id=job.candidate_archive_id,
            profile_revision=job.candidate_archive_revision, source_company=job.target_company, source_role=job.target_job_title, version_id=version.id, label=version.label, captured_at=utc_now(), draft_digest=draft_digest(version.draft), draft=version.draft,
            candidate_profile=job.result.candidate_profile, fact_cards=job.result.fact_cards, jd_text=next((run.jd_text for run in item.runs if run.run_id == job.run_id), job.jd_text),
            jd_profile=job.result.jd_profile, preferences=job.result.preferences, resolved_language=job.result.resolved_language,
            risk_notes=list(job.result.final_package.risk_notes) + reports.unsupported_claims + reports.exaggeration_warnings + reports.seniority_mismatches + reports.blocked_phrases + reports.keyword_stuffing_warnings,
            jd_review=job.result.final_package.jd_review_doc.markdown if is_prepared_version and job.result.final_package.jd_review_doc else "",
            interview_prep=job.result.final_package.interview_prep_doc.markdown if is_prepared_version and job.result.final_package.interview_prep_doc else "",
            provenance=version.provenance)
    return mutation(lambda: get_position_store().link_resume(profile_id, position_id, payload.expected_revision, snapshot))


@router.post("/{position_id}/resumes/{resume_id}/current", response_model=PositionRecord)
def current_resume(profile_id: str, position_id: str, resume_id: str, payload: PositionRevision, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    return mutation(lambda: get_position_store().select_resume(profile_id, position_id, payload.expected_revision, resume_id))


@router.get("/{position_id}/resumes/{resume_id}/{export_format}")
def export_resume(profile_id: str, position_id: str, resume_id: str, export_format: Literal["pdf", "docx"], x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    item = record(profile_id, position_id)
    material = next((material for material in item.resumes if material.id == resume_id), None)
    if material is None: raise HTTPException(404, "职位简历快照不存在。")
    preferences = export_preferences(material.preferences, material.resolved_language)
    content, media_type = (build_pdf(material.draft, material.candidate_profile, preferences), PDF_MEDIA_TYPE) if export_format == "pdf" else (build_docx(material.draft, material.candidate_profile, preferences), DOCX_MEDIA_TYPE)
    return Response(content, media_type=media_type, headers={"Cache-Control":"no-store", "Content-Disposition":f'attachment; filename="position-resume.{export_format}"'})


@router.get("/{position_id}/practice-sources")
def practice_sources(profile_id: str, position_id: str, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    return available_practices(profile_id, position_id, x_profile_token, {})


@router.post("/{position_id}/practice-sources")
def owned_practice_sources(profile_id: str, position_id: str, payload: PositionPracticeQuery, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    return available_practices(profile_id, position_id, x_profile_token, {item.id: item.token for item in payload.runs})


def available_practices(profile_id, position_id, profile_token, credentials):
    item = record(profile_id, position_id); candidates = []
    for resume in item.resumes:
        if not resume.version_id or not get_run_store().get_authorized(resume.run_id, credentials.get(resume.run_id) or profile_token or ""): continue
        for session in get_interview_store().list(resume.run_id):
            if session.version_id == resume.version_id and session.answered_count:
                candidates.append({"resume_id":resume.id, "resume_label":resume.label, "session":session})
    return candidates


@router.post("/{position_id}/interviews", response_model=PositionRecord)
def save_interview(profile_id: str, position_id: str, payload: PositionInterviewLink, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    item = record(profile_id, position_id); check_revision(item, payload.expected_revision)
    resume = next((resume for resume in item.resumes if resume.id == payload.resume_id), None)
    if resume is None: raise HTTPException(404, "请先关联面试使用的简历版本。")
    _get_authorized_run(resume.run_id, payload.run_token or x_profile_token)
    session = get_interview_store().get(resume.run_id, payload.session_id)
    if session is None: raise HTTPException(404, "面试练习不存在或已过期。")
    if not resume.version_id or session.version_id != resume.version_id: raise HTTPException(409, "该面试练习使用的简历版本与所选材料不同。")
    if not session.turns: raise HTTPException(409, "面试练习尚无已提交回答。")
    snapshot = PositionInterview(resume_id=resume.id, source_session_id=session.id, source_revision=session.revision,
        captured_at=utc_now(), status=session.status, answered_count=len(session.turns), report=interview_report(session))
    return mutation(lambda: get_position_store().link_interview(profile_id, position_id, payload.expected_revision, snapshot))


@router.get("/{position_id}/interviews/{interview_id}/report")
def export_interview(profile_id: str, position_id: str, interview_id: str, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    report = next((report for report in record(profile_id, position_id).interviews if report.id == interview_id), None)
    if report is None: raise HTTPException(404, "职位复习报告不存在。")
    return Response(report.report, media_type="text/markdown; charset=utf-8", headers={"Cache-Control":"no-store", "Content-Disposition":'attachment; filename="position-interview.md"'})


@router.post("/{position_id}/material-sources")
def material_sources(profile_id: str, position_id: str, payload: PositionPracticeQuery, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    item = record(profile_id, position_id)
    credentials = {entry.id: entry.token for entry in payload.runs}
    candidates = []
    for resume in item.resumes:
        if not resume.version_id or not get_run_store().get_authorized(resume.run_id, credentials.get(resume.run_id) or x_profile_token or ""):
            continue
        for pack in get_material_store().list(resume.run_id):
            if pack.version_id == resume.version_id:
                candidates.append({"resume_id":resume.id, "resume_label":resume.label, "pack":pack})
    return candidates


@router.post("/{position_id}/materials", response_model=PositionRecord)
def save_material_pack(profile_id: str, position_id: str, payload: PositionMaterialLink, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    item = record(profile_id, position_id); check_revision(item, payload.expected_revision)
    resume = next((entry for entry in item.resumes if entry.id == payload.resume_id), None)
    if resume is None:
        raise HTTPException(404, "请先关联材料使用的简历版本。")
    _get_authorized_run(resume.run_id, payload.run_token or x_profile_token)
    pack = get_material_store().get(resume.run_id, payload.pack_id)
    if pack is None:
        raise HTTPException(404, "材料包不存在或已过期。")
    if pack.revision != payload.expected_pack_revision:
        raise HTTPException(409, "材料包已更新，请重新载入并核对后关联。")
    if pack.version_id != resume.version_id or draft_digest(pack.draft) != resume.draft_digest:
        raise HTTPException(409, "材料包与关联简历不是同一个版本。")
    if resume.jd_profile is not None and pack.jd_profile != resume.jd_profile:
        raise HTTPException(409, "材料包与关联简历的目标 JD 不同。")
    if pack.jd_text.strip() not in {resume.jd_text.strip(), (resume.source_role + "\n" + resume.jd_text).strip()}:
        raise HTTPException(409, "材料包与关联简历的来源 JD 不同。")
    if any(not doc.reviewed for doc in pack.documents):
        raise HTTPException(409, "请先逐份核对并保存全部材料，再长期关联。")
    snapshot = PositionMaterial(resume_id=resume.id, captured_at=utc_now(), pack=pack.model_copy(deep=True))
    return mutation(lambda: get_position_store().link_material(profile_id, position_id, payload.expected_revision, snapshot))


@router.get("/{position_id}/materials/{material_id}/export")
def export_saved_material_pack(profile_id: str, position_id: str, material_id: str, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    material = next((entry for entry in record(profile_id, position_id).materials if entry.id == material_id), None)
    if material is None:
        raise HTTPException(404, "职位材料包不存在。")
    return Response(pack_zip(material.pack), media_type="application/zip",
        headers={"Cache-Control":"no-store", "Content-Disposition":'attachment; filename="position-materials.zip"'})


@router.delete("/{position_id}", status_code=204)
def delete_position(profile_id: str, position_id: str, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    if not get_position_store().delete(profile_id, position_id): raise HTTPException(404, "职位不存在。")
    return Response(status_code=204)
