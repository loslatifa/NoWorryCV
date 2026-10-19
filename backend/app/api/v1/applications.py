from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response

from backend.app.services.preferences import export_preferences, merge_preferences
from backend.app.api.v1.profiles import _get_archive
from backend.app.api.v1.routes import _start_tailor_job
from backend.app.schemas.application import (
    ApplicationConfirm, ApplicationCreate, ApplicationFillReport, ApplicationRecord,
)
from backend.app.schemas.run_state import TailorRunInput
from backend.app.services.applications import (
    ApplicationConflict, build_form_resume, draft_digest, get_application_store, utc_now,
)
from backend.app.services.profiles import archive_resume_text
from backend.app.services.resume_export import build_docx, build_pdf, DOCX_MEDIA_TYPE, PDF_MEDIA_TYPE
from backend.app.services.runs.store import get_run_store
from backend.app.services.runs.queue import get_task_queue

router = APIRouter(prefix="/candidate-profiles/{profile_id}/applications", tags=["applications"])


def _record(profile_id, application_id):
    record = get_application_store().get(profile_id, application_id)
    if record is None:
        raise HTTPException(404, "投递记录不存在。")
    return record


def _refresh(profile_id, application_id):
    record = _record(profile_id, application_id)
    if record.confirmed_at:
        return record
    job = get_run_store().get(record.run_id)
    if job is None:
        if record.draft is not None:
            return record
        def expire(current):
            if not current.confirmed_at:
                current.status = "expired"
                current.status_message = "生成任务已过期，请重新生成。"
        return get_application_store().update(profile_id, application_id, expire)

    def refresh(current):
        if current.confirmed_at:
            return
        current.progress_percent = job.progress_percent
        current.status_message = job.status_message or job.error_message
        if job.result is None:
            current.status = job.status if job.status in {"failed", "cancelled"} else "generating"
            return
        result = job.result
        draft = result.final_package.draft.model_copy(deep=True)
        current.draft = draft
        current.preferences = result.preferences.model_copy(deep=True)
        current.resolved_language = result.resolved_language
        current.draft_digest = draft_digest(draft)
        current.candidate_profile = result.candidate_profile.model_copy(deep=True)
        current.fact_cards = [fact.model_copy(deep=True) for fact in result.fact_cards]
        current.form_resume, warnings = build_form_resume(result.candidate_profile, draft, result.fact_cards)
        current.risk_notes = list(result.final_package.risk_notes) + warnings
        active_version = next((version for version in result.draft_versions
                               if version.id == result.active_version_id), None)
        report = active_version.compliance_report if active_version else (
            result.reviews[-1].compliance_report if result.reviews else None)
        if report:
            current.risk_notes += (report.unsupported_claims + report.exaggeration_warnings
                                   + report.blocked_phrases + report.seniority_mismatches
                                   + report.keyword_stuffing_warnings)
        current.change_log = list(result.final_package.change_log)
        current.status = "awaiting_confirmation"
    return get_application_store().update(profile_id, application_id, refresh)


@router.post("", response_model=ApplicationRecord, status_code=201)
def create_application(profile_id: str, payload: ApplicationCreate,
                       x_profile_token: Optional[str] = Header(None),
                       idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key")):
    archive = _get_archive(profile_id, x_profile_token)
    if archive.revision != payload.expected_revision:
        raise HTTPException(409, "基础档案已更新，请重新载入。")
    payload = payload.model_copy(update={"preferences": merge_preferences(archive.preferences, payload.preferences)}, deep=True)
    # Application mode retains real JD analysis, rewriting and review; skips study documents.
    jd_for_analysis = "\n".join(part for part in (payload.target_role.strip(), payload.jd_text.strip()) if part)
    job = _start_tailor_job(TailorRunInput(
        preferences=payload.preferences,
        resume_text=archive_resume_text(archive), jd_text=jd_for_analysis,
        confirmed_candidate_profile=archive.candidate_profile, confirmed_fact_cards=archive.fact_cards,
        max_iterations=1, processing_mode="application", output_language=payload.output_language,
        target_company=payload.target_company, target_role=payload.target_role,
    ), "application:{0}:{1}".format(profile_id, idempotency_key) if idempotency_key else None,
        archive.id, archive.revision)
    return get_application_store().create(archive.id, archive.revision, job.run_id, payload, job.expires_at)


@router.get("", response_model=list[ApplicationRecord])
def list_applications(profile_id: str, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    return get_application_store().list(profile_id)


@router.get("/{application_id}", response_model=ApplicationRecord)
def get_application(profile_id: str, application_id: str, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    return _refresh(profile_id, application_id)


@router.post("/{application_id}/confirm", response_model=ApplicationRecord)
def confirm_application(profile_id: str, application_id: str, payload: ApplicationConfirm,
                        x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    _refresh(profile_id, application_id)

    def confirm(current):
        if current.draft is None or current.status not in {"awaiting_confirmation", "confirmed", "filled", "partial"}:
            raise ApplicationConflict("简历尚未生成完成。")
        if current.draft_digest != payload.draft_digest:
            raise ApplicationConflict("简历版本已变化，请查看最新版本后再确认。")
        if not current.confirmed_at:
            current.confirmed_at = utc_now()
            current.status = "confirmed"
            current.status_message = "已确认简历并保存，可以填写投递页面。"
    try:
        return get_application_store().update(profile_id, application_id, confirm)
    except ApplicationConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{application_id}/fill-report", response_model=ApplicationRecord)
def save_fill_report(profile_id: str, application_id: str, payload: ApplicationFillReport,
                     x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    _record(profile_id, application_id)

    def report(current):
        if not current.confirmed_at:
            raise ApplicationConflict("请先确认简历再填写页面。")
        if str(payload.page_url) != current.page_url:
            raise ApplicationConflict("投递页面已变化，请为当前页面创建新记录。")
        current.fill_report = payload
        current.status = "filled" if payload.results and all(item.status == "filled" for item in payload.results) else "partial"
        current.status_message = "填写结果已保存，请检查页面并手动提交。"
    try:
        return get_application_store().update(profile_id, application_id, report)
    except ApplicationConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{application_id}/resume/{export_format}")
def export_application_resume(profile_id: str, application_id: str, export_format: str,
                              x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    record = _record(profile_id, application_id)
    if not record.confirmed_at or record.draft is None:
        raise HTTPException(409, "请先确认简历。")
    if export_format == "pdf":
        content, media_type = build_pdf(record.draft, record.candidate_profile, export_preferences(record.preferences, record.resolved_language)), PDF_MEDIA_TYPE
    elif export_format == "docx":
        content, media_type = build_docx(record.draft, record.candidate_profile, export_preferences(record.preferences, record.resolved_language)), DOCX_MEDIA_TYPE
    else:
        raise HTTPException(400, "仅支持 PDF 或 DOCX。")
    return Response(content, media_type=media_type, headers={
        "Cache-Control": "no-store",
        "Content-Disposition": 'attachment; filename="tailored-resume.{0}"'.format(export_format),
    })


@router.delete("/{application_id}", status_code=204)
def delete_application(profile_id: str, application_id: str, x_profile_token: Optional[str] = Header(None)):
    _get_archive(profile_id, x_profile_token)
    record = _record(profile_id, application_id)
    get_task_queue().delete(record.run_id)
    get_run_store().delete_authorized(record.run_id, x_profile_token or "")
    get_application_store().delete(profile_id, application_id)
    return Response(status_code=204)
