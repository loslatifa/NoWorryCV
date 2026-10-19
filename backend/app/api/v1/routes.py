import logging
import json
import hashlib
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from fastapi import Request, APIRouter, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import Response, StreamingResponse

from backend.app.services.preferences import export_preferences, target_pages
from backend.app.agents.orchestrator import ResumeTailorOrchestrator
from backend.app.agents.ats import ATSScoringAgent
from backend.app.agents.compliance import TruthfulnessComplianceAgent
from backend.app.agents.partial_rewrite import PartialRewriteAgent
from backend.app.graph.resume_tailor_graph import analyze_jd_payload, parse_resume_payload, run_tailor_pipeline
from backend.app.core.config import get_settings
from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.diff import DraftDiffRequest, DraftDiffResponse
from backend.app.schemas.export import ResumeExportRequest
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.run_state import (
    DraftMutationResponse,
    DraftSaveRequest,
    DraftVersion,
    PartialRewriteRequest,
    ResumeParsePreview,
    TailorRunInput,
    TailorRunJobStatus,
    TailorRunResult,
)
from backend.app.schemas.score import JDMatchScoreRequest, JDMatchScoreResponse
from backend.app.services.draft_editing import (
    VALID_PARTIAL_TARGETS,
    apply_partial_rewrite,
    normalize_manual_draft,
)
from backend.app.services.draft_diff import build_draft_diff
from backend.app.services.provenance import capture_provenance
from backend.app.services.quality import record_event, saved_version_id
from backend.app.schemas.preferences import PREFERENCE_OPTIONS, ResumePreferences
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.llm.diagnostics import safe_failure
from backend.app.services.llm.provider import get_llm_provider
from backend.app.services.parsers.file_parser import extract_text_from_file
from backend.app.services.runs.store import get_run_store
from backend.app.services.runs.queue import get_task_queue
from backend.app.services.runs.worker import start_task_workers
from backend.app.services.resume_export import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    build_docx,
    build_pdf,
    pdf_page_count,
    sanitize_filename,
)

router = APIRouter(tags=["tailor"])
logger = logging.getLogger(__name__)
SUPPORTED_RESUME_SUFFIXES = {".pdf", ".docx", ".md", ".txt"}


@router.post("/resume/parse", response_model=CandidateProfile)
def parse_resume(payload: TailorRunInput) -> CandidateProfile:
    try:
        return parse_resume_payload(payload)
    except StructuredLLMError as exc:
        raise _llm_required_error(exc) from exc


@router.post("/resume/parse-upload", response_model=ResumeParsePreview)
async def parse_resume_upload(
    resume_file: UploadFile = File(...),
    candidate_notes: str = Form(""),
    jd_text: str = Form(""),
) -> ResumeParsePreview:
    resume_text = await _extract_uploaded_resume(resume_file)
    payload = TailorRunInput(
        resume_text=resume_text,
        candidate_notes=candidate_notes,
        jd_text=jd_text,
        processing_mode="full",
    )
    try:
        orchestrator = ResumeTailorOrchestrator()
        if jd_text.strip():
            candidate_profile, fact_cards, jd_profile, gap_analysis, follow_up_questions = (
                orchestrator.prepare_confirmation(payload)
            )
        else:
            candidate_profile, fact_cards = orchestrator.parse_resume_with_facts(payload)
            jd_profile = None
            gap_analysis = None
            follow_up_questions = []
    except StructuredLLMError as exc:
        raise _llm_required_error(exc) from exc
    return ResumeParsePreview(
        resume_text=resume_text,
        candidate_profile=candidate_profile,
        fact_cards=fact_cards,
        jd_profile=jd_profile,
        gap_analysis=gap_analysis,
        follow_up_questions=follow_up_questions,
    )


@router.get("/resume-preferences")
def preference_options():
    from backend.app.services.template_catalog import public_templates, import_issues
    return {"defaults": ResumePreferences().model_dump(), "options": PREFERENCE_OPTIONS,
            "templates": public_templates(), "template_issues": import_issues()}


@router.post("/jd/analyze", response_model=JDProfile)
def analyze_jd(payload: TailorRunInput) -> JDProfile:
    try:
        return analyze_jd_payload(payload)
    except StructuredLLMError as exc:
        raise _llm_required_error(exc) from exc


@router.post("/tailor-runs", response_model=TailorRunResult)
def create_tailor_run(payload: TailorRunInput) -> TailorRunResult:
    try:
        return run_tailor_pipeline(payload)
    except StructuredLLMError as exc:
        raise _llm_required_error(exc) from exc


@router.post("/tailor-runs/upload", response_model=TailorRunResult)
async def create_tailor_run_from_upload(
    resume_file: UploadFile = File(...),
    jd_text: str = Form(...),
    candidate_notes: str = Form(""),
    output_language: str = Form("auto"),
    max_iterations: int = Form(2),
) -> TailorRunResult:
    resume_text = await _extract_uploaded_resume(resume_file)
    if not jd_text.strip():
        raise HTTPException(status_code=400, detail="JD text cannot be empty.")

    payload = _build_upload_payload(
        resume_text=resume_text,
        jd_text=jd_text,
        candidate_notes=candidate_notes,
        output_language=output_language,
        max_iterations=max_iterations,
    )
    try:
        return run_tailor_pipeline(payload)
    except StructuredLLMError as exc:
        raise _llm_required_error(exc) from exc


@router.post("/tailor-runs/upload-jobs", response_model=TailorRunJobStatus)
async def create_tailor_run_job_from_upload(
    resume_file: UploadFile = File(...),
    jd_text: str = Form(...),
    candidate_notes: str = Form(""),
    output_language: str = Form("auto"),
    max_iterations: int = Form(2),
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> TailorRunJobStatus:
    resume_text = await _extract_uploaded_resume(resume_file)
    if not jd_text.strip():
        raise HTTPException(status_code=400, detail="JD text cannot be empty.")

    payload = _build_upload_payload(
        resume_text=resume_text,
        jd_text=jd_text,
        candidate_notes=candidate_notes,
        output_language=output_language,
        max_iterations=max_iterations,
    )
    return _start_tailor_job(payload, idempotency_key)


@router.post("/tailor-runs/confirmed-jobs", response_model=TailorRunJobStatus)
def create_confirmed_tailor_run_job(
    payload: TailorRunInput,
    idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
) -> TailorRunJobStatus:
    if not payload.resume_text.strip():
        raise HTTPException(status_code=400, detail="Resume text cannot be empty.")
    if not payload.jd_text.strip():
        raise HTTPException(status_code=400, detail="JD text cannot be empty.")
    if payload.confirmed_candidate_profile is None:
        raise HTTPException(status_code=400, detail="Confirmed candidate profile is required.")
    if not payload.confirmed_fact_cards:
        raise HTTPException(status_code=400, detail="At least one confirmed fact is required.")
    if any(not card.confirmed for card in payload.confirmed_fact_cards):
        raise HTTPException(status_code=400, detail="Every submitted fact must be confirmed.")
    if any(not card.text.strip() for card in payload.confirmed_fact_cards):
        raise HTTPException(status_code=400, detail="Confirmed facts cannot be empty.")
    fact_ids = [card.id for card in payload.confirmed_fact_cards]
    if len(fact_ids) != len(set(fact_ids)):
        raise HTTPException(status_code=400, detail="Confirmed fact IDs must be unique.")
    return _start_tailor_job(payload, idempotency_key)


def _start_tailor_job(
    payload: TailorRunInput,
    idempotency_key: Optional[str] = None,
    candidate_archive_id: str = "",
    candidate_archive_revision: int = 0,
) -> TailorRunJobStatus:
    store = get_run_store()
    payload = payload.model_copy(update={"provenance": capture_provenance(payload.processing_mode)}, deep=True)
    job = store.create("任务已创建，等待开始。", provenance=payload.provenance)
    normalized_key = (idempotency_key or "").strip()
    if not normalized_key:
        payload_fingerprint = hashlib.sha256(json.dumps(payload.model_dump(mode="json", exclude={"provenance"}), sort_keys=True).encode("utf-8")).hexdigest()
        normalized_key = "auto:{0}:{1}".format(payload_fingerprint, int(time.time() // 60))
    queued_job = store.update(
        job.run_id,
        status="queued",
        current_stage="queued",
        progress_percent=5,
        status_message="任务已进入持久化队列，准备优先分析 JD。",
        max_attempts=get_settings().task_max_attempts,
        candidate_archive_id=candidate_archive_id,
        candidate_archive_revision=candidate_archive_revision,
        target_job_title=payload.target_role.strip() or (payload.preanalyzed_jd_profile.job_title if payload.preanalyzed_jd_profile else ""),
        target_company=payload.target_company.strip(),
        jd_text=payload.jd_text,
    )
    duplicate_run_id = get_task_queue().enqueue(
        job.run_id,
        payload,
        normalized_key,
        job.expires_at,
    )
    if duplicate_run_id:
        store.delete_authorized(job.run_id, job.access_token or "")
        raise HTTPException(status_code=409, detail="相同任务已提交，请继续查看原任务。")
    start_task_workers()
    response = queued_job or job
    return response.model_copy(update={"access_token": job.access_token}, deep=True)


@router.get("/tailor-runs/{run_id}/draft-versions", response_model=list[DraftVersion])
def get_draft_versions(run_id: str, x_run_token: Optional[str] = Header(None)) -> list[DraftVersion]:
    job = _get_authorized_run(run_id, x_run_token)
    if job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    return job.result.draft_versions


@router.post("/tailor-runs/{run_id}/draft-diff", response_model=DraftDiffResponse)
def get_draft_diff(
    run_id: str,
    payload: DraftDiffRequest,
    x_run_token: Optional[str] = Header(None),
) -> DraftDiffResponse:
    job = _get_authorized_run(run_id, x_run_token)
    if job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    response = build_draft_diff(
        job.result.candidate_profile,
        job.result.fact_cards,
        payload.draft,
    )
    response.version_id = saved_version_id(job.result, payload.draft)
    return response


@router.post("/tailor-runs/{run_id}/score", response_model=JDMatchScoreResponse)
def score_resume_draft(
    run_id: str,
    payload: JDMatchScoreRequest,
    x_run_token: Optional[str] = Header(None),
) -> JDMatchScoreResponse:
    job = _get_authorized_run(run_id, x_run_token)
    if job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    draft = normalize_manual_draft(
        job.result.final_package.draft,
        payload.draft,
    )
    compliance_report = TruthfulnessComplianceAgent().run(
        draft,
        job.result.fact_cards,
    )
    scoring_agent = ATSScoringAgent()
    baseline = scoring_agent.run_candidate(
        job.result.candidate_profile,
        job.result.jd_profile,
    )
    tailored = scoring_agent.run(
        draft,
        job.result.jd_profile,
        compliance_report,
    )
    return JDMatchScoreResponse(
        baseline=baseline,
        tailored=tailored,
        score_delta=tailored.score - baseline.score,
        compliance_report=compliance_report,
    )


@router.post("/tailor-runs/{run_id}/export-preview")
def preview_resume_export(
    run_id: str,
    payload: ResumeExportRequest,
    x_run_token: Optional[str] = Header(None),
) -> Response:
    job = _get_authorized_run(run_id, x_run_token)
    if job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    preferences = export_preferences(job.result.preferences, job.result.resolved_language)
    if payload.template is not None:
        preferences = preferences.model_copy(update={"template": payload.template})
    pdf_bytes = build_pdf(payload.draft, job.result.candidate_profile, preferences)
    page_count = pdf_page_count(pdf_bytes)
    return Response(
        content=pdf_bytes,
        media_type=PDF_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "inline; filename=resume-preview.pdf",
            "X-Page-Count": str(page_count),
            "X-Overflow": "true" if page_count > target_pages(job.result.preferences) else "false",
            "X-Target-Pages": job.result.preferences.page_count,
            "X-Resume-Template": preferences.template,
        },
    )


@router.post("/tailor-runs/{run_id}/export/{export_format}")
def export_resume(
    run_id: str,
    export_format: str,
    payload: ResumeExportRequest,
    x_run_token: Optional[str] = Header(None),
) -> Response:
    job = _get_authorized_run(run_id, x_run_token)
    if job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    normalized_format = export_format.lower()
    preferences = export_preferences(job.result.preferences, job.result.resolved_language)
    if payload.template is not None:
        preferences = preferences.model_copy(update={"template": payload.template})
    if normalized_format == "docx":
        content = build_docx(payload.draft, job.result.candidate_profile, preferences)
        media_type = DOCX_MEDIA_TYPE
    elif normalized_format == "pdf":
        content = build_pdf(payload.draft, job.result.candidate_profile, preferences)
        media_type = PDF_MEDIA_TYPE
    else:
        raise HTTPException(status_code=400, detail="Export format must be docx or pdf.")

    filename = "{0}.{1}".format(sanitize_filename(payload.filename), normalized_format)
    encoded_filename = quote(filename, safe="")
    version_id = saved_version_id(job.result, payload.draft)
    record_event(job, "export", version_id)
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "X-Resume-Template": preferences.template,
            "Content-Disposition": (
                "attachment; filename=tailored-resume.{0}; filename*=UTF-8''{1}".format(
                    normalized_format,
                    encoded_filename,
                )
            ),
        },
    )


@router.put("/tailor-runs/{run_id}/draft", response_model=DraftMutationResponse)
def save_manual_draft(
    run_id: str,
    payload: DraftSaveRequest,
    x_run_token: Optional[str] = Header(None),
) -> DraftMutationResponse:
    store = get_run_store()
    job = _get_authorized_run(run_id, x_run_token)
    if job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    draft = normalize_manual_draft(job.result.final_package.draft, payload.draft)
    compliance_report = TruthfulnessComplianceAgent().run(draft, job.result.fact_cards)
    manually_changed_fields = []
    if draft.headline != job.result.final_package.draft.headline:
        manually_changed_fields.append("标题")
    if draft.summary != job.result.final_package.draft.summary:
        manually_changed_fields.append("个人摘要")
    if manually_changed_fields:
        compliance_report.exaggeration_warnings.append(
            "{0}包含手工修改，请确认新增表述能够由事实卡支撑。".format("、".join(manually_changed_fields))
        )
        if compliance_report.risk_level == "low":
            compliance_report.risk_level = "medium"
    ats_report = ATSScoringAgent().run(draft, job.result.jd_profile, compliance_report)
    version = store.save_draft_version(
        run_id,
        draft,
        compliance_report,
        ats_report,
        source="manual",
        label=payload.label.strip() or "手工保存",
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    updated_job = store.get(run_id)
    return DraftMutationResponse(version=version, versions=updated_job.result.draft_versions)


@router.post("/tailor-runs/{run_id}/rewrite-part", response_model=DraftMutationResponse)
def rewrite_draft_part(
    run_id: str,
    payload: PartialRewriteRequest,
    x_run_token: Optional[str] = Header(None),
) -> DraftMutationResponse:
    if payload.target_type not in VALID_PARTIAL_TARGETS:
        raise HTTPException(status_code=400, detail="Unsupported partial rewrite target.")
    store = get_run_store()
    job = _get_authorized_run(run_id, x_run_token)
    if job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    try:
        output = PartialRewriteAgent().run(
            payload,
            job.result.fact_cards,
            job.result.jd_profile,
        )
        draft = apply_partial_rewrite(payload, output)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except StructuredLLMError as exc:
        raise _llm_required_error(exc) from exc

    compliance_report = TruthfulnessComplianceAgent().run(draft, job.result.fact_cards)
    ats_report = ATSScoringAgent().run(draft, job.result.jd_profile, compliance_report)
    version = store.save_draft_version(
        run_id,
        draft,
        compliance_report,
        ats_report,
        source="ai_partial",
        label="局部重写：{0}".format(payload.target_type),
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    updated_job = store.get(run_id)
    return DraftMutationResponse(version=version, versions=updated_job.result.draft_versions)


async def _extract_uploaded_resume(resume_file: UploadFile) -> str:
    settings = get_settings()
    max_upload_bytes = max(1, settings.max_upload_bytes)
    filename = resume_file.filename or ""
    if Path(filename).suffix.lower() not in SUPPORTED_RESUME_SUFFIXES:
        raise HTTPException(status_code=400, detail="仅支持 PDF、DOCX、Markdown 和 TXT 简历。")
    try:
        content = await resume_file.read(max_upload_bytes + 1)
        if len(content) > max_upload_bytes:
            raise HTTPException(
                status_code=413,
                detail="简历文件不能超过 {0} MB。".format(
                    max(1, (max_upload_bytes + 1024 * 1024 - 1) // (1024 * 1024))
                ),
            )
        resume_text = extract_text_from_file(filename, content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.warning("Resume file parsing failed for %s: %s", filename, exc)
        raise HTTPException(status_code=400, detail="无法读取该简历文件，请检查文件是否损坏或改用其他格式。") from exc
    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Uploaded resume file did not yield readable text.")
    return resume_text


@router.get("/tailor-runs/{run_id}/events")
def get_tailor_run_events(request: Request, run_id: str, x_run_token: Optional[str] = Header(None)):
    from backend.app.services.runs.events import status_events
    _get_authorized_run(run_id, x_run_token)

    def read_status():
        job = get_run_store().get_authorized(run_id, x_run_token or "")
        return _enrich_queue_metadata(job) if job else None

    return StreamingResponse(status_events(request, read_status), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache, no-store", "X-Accel-Buffering": "no"})


@router.get("/tailor-runs/{run_id}/status", response_model=TailorRunJobStatus)
def get_tailor_run_status(
    run_id: str,
    x_run_token: Optional[str] = Header(None),
) -> TailorRunJobStatus:
    return _enrich_queue_metadata(_get_authorized_run(run_id, x_run_token))


@router.post("/tailor-runs/{run_id}/cancel", response_model=TailorRunJobStatus)
def cancel_tailor_run(
    run_id: str,
    x_run_token: Optional[str] = Header(None),
) -> TailorRunJobStatus:
    _get_authorized_run(run_id, x_run_token)
    if not get_task_queue().request_cancel(run_id):
        raise HTTPException(status_code=409, detail="当前任务状态无法取消。")
    job = get_run_store().mark_cancelled(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Run not found or access denied.")
    return _enrich_queue_metadata(job)


@router.post("/tailor-runs/{run_id}/retry", response_model=TailorRunJobStatus)
def retry_tailor_run(
    run_id: str,
    x_run_token: Optional[str] = Header(None),
) -> TailorRunJobStatus:
    _get_authorized_run(run_id, x_run_token)
    if not get_task_queue().retry(run_id):
        raise HTTPException(status_code=409, detail="当前任务不可重试或已达到最大尝试次数。")
    job = get_run_store().mark_queued_for_recovery(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Run not found or access denied.")
    return _enrich_queue_metadata(job)


@router.delete("/tailor-runs/{run_id}", status_code=204)
def delete_tailor_run(run_id: str, x_run_token: Optional[str] = Header(None)) -> Response:
    _get_authorized_run(run_id, x_run_token)
    get_task_queue().delete(run_id)
    if not get_run_store().delete_authorized(run_id, x_run_token or ""):
        raise HTTPException(status_code=404, detail="Run not found or access denied.")
    return Response(status_code=204)


@router.get("/privacy")
def get_privacy_summary() -> dict:
    settings = get_settings()
    return {
        "anonymous_retention_hours": settings.anonymous_run_ttl_hours,
        "max_upload_bytes": settings.max_upload_bytes,
        "supported_file_types": sorted(SUPPORTED_RESUME_SUFFIXES),
        "saved_profile_retention": "用户明确同意保存的基础档案保留至主动删除；历史任务仍按匿名任务期限清理。",
        "usage": "简历与 JD 用于解析、生成、审查、编辑和导出本次求职材料；本地记录版本反馈及接受、拒绝、保存编辑、导出行为用于质量分析，反馈不收集自由文本并随任务删除或过期清理。",
    }


def _build_upload_payload(
    resume_text: str,
    jd_text: str,
    candidate_notes: str,
    output_language: str,
    max_iterations: int,
) -> TailorRunInput:
    return TailorRunInput(
        resume_text=resume_text,
        jd_text=jd_text,
        candidate_notes=candidate_notes,
        output_language=output_language,
        max_iterations=max_iterations,
        processing_mode="full",
    )


def _llm_required_error(exc: Exception) -> HTTPException:
    diagnostic = safe_failure(exc)
    code = diagnostic["code"]
    if code == "generation_failed" and not get_llm_provider().is_available:
        code = "provider_unavailable"
    messages = {
        "provider_unavailable": "未配置可用的模型服务，请检查模型名称和对应密钥，修改配置后重启后端。",
        "authentication_failed": "模型密钥未通过验证，请检查对应服务商的 API key，修改后重启后端。",
        "access_denied": "模型服务拒绝访问，请检查账号的模型权限和服务地区。",
        "quota_exceeded": "模型服务额度或余额不足，请补充额度后重试。",
        "model_not_found": "配置的模型不存在或未获授权，请核对模型名称和账号权限。",
        "endpoint_not_found": "模型接口地址或模型名称无效，请检查模型配置。",
        "timeout": "模型请求超时，请稍后重试；若持续出现，请检查网络和模型服务状态。",
        "connection_error": "无法连接模型服务，请检查网络或代理设置后重试。",
        "invalid_output": "模型返回内容不完整或格式不符合要求，请重新解析；若反复出现，请检查模型的 JSON 输出配置。",
        "output_truncated": "模型返回内容达到长度限制，自动重试后仍未完整生成；请精简重复内容后重试。",
        "invalid_request": "模型服务不接受当前请求参数，请检查模型和输出格式配置。",
        "rate_limited": "模型服务限流，请稍后重试。",
        "provider_error": "模型服务暂时异常，请稍后重试。",
    }
    stage = {"resume_parser": "简历解析", "jd_analyst": "岗位分析", "gap_analysis": "缺口分析"}.get(diagnostic["stage"])
    detail = messages.get(code, "模型服务暂时不可用，请检查服务配置或稍后重试。")
    if stage:
        detail = f"{stage}未完成：{detail}"
    logger.warning("LLM request failed: stage=%s code=%s upstream_status=%s error_type=%s", diagnostic["stage"], code, diagnostic["http_status"], diagnostic["error_type"])
    return HTTPException(
        status_code=503,
        detail=detail,
        headers={"X-Error-Code": code},
    )


def _get_authorized_run(run_id: str, access_token: Optional[str]) -> TailorRunJobStatus:
    job = get_run_store().get_authorized(run_id, access_token or "")
    if job is None:
        raise HTTPException(status_code=404, detail="Run not found or access denied.")
    return job


def _enrich_queue_metadata(job: TailorRunJobStatus) -> TailorRunJobStatus:
    metadata = get_task_queue().metadata(job.run_id)
    if metadata is None:
        return job
    attempt_count = int(metadata.get("attempt") or 0)
    max_attempts = int(metadata.get("max_attempts") or job.max_attempts)
    queue_status = str(metadata.get("status") or job.status)
    return job.model_copy(
        update={
            "jd_text": job.jd_text or json.loads(metadata["payload_json"]).get("jd_text", ""),
            "attempt_count": attempt_count,
            "max_attempts": max_attempts,
            "retryable": queue_status in {"failed", "cancelled"} and attempt_count < max_attempts,
            "failed_stage": str(metadata.get("current_stage") or job.failed_stage) if queue_status == "failed" else job.failed_stage,
            "error_type": str(metadata.get("error_type") or job.error_type),
            "stage_history": get_task_queue().stage_history(job.run_id),
        },
        deep=True,
    )
