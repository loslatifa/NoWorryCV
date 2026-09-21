from threading import Thread
from urllib.parse import quote

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from backend.app.agents.orchestrator import ResumeTailorOrchestrator
from backend.app.agents.ats import ATSScoringAgent
from backend.app.agents.compliance import TruthfulnessComplianceAgent
from backend.app.agents.partial_rewrite import PartialRewriteAgent
from backend.app.graph.resume_tailor_graph import analyze_jd_payload, parse_resume_payload, run_tailor_pipeline
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
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.parsers.file_parser import extract_text_from_file
from backend.app.services.runs.store import get_run_store
from backend.app.services.resume_export import (
    DOCX_MEDIA_TYPE,
    PDF_MEDIA_TYPE,
    build_docx,
    build_pdf,
    pdf_page_count,
    sanitize_filename,
)

router = APIRouter(tags=["tailor"])


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
    return _start_tailor_job(payload)


@router.post("/tailor-runs/confirmed-jobs", response_model=TailorRunJobStatus)
def create_confirmed_tailor_run_job(payload: TailorRunInput) -> TailorRunJobStatus:
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
    return _start_tailor_job(payload)


def _start_tailor_job(payload: TailorRunInput) -> TailorRunJobStatus:
    store = get_run_store()
    job = store.create("任务已创建，等待开始。")

    def progress_callback(stage: str, percent: int, message: str, review_cards=None) -> None:
        store.mark_running(
            job.run_id,
            stage=stage,
            percent=percent,
            message=message,
            review_cards=review_cards,
        )

    def runner() -> None:
        try:
            orchestrator = ResumeTailorOrchestrator(progress_callback=progress_callback)
            result = orchestrator.run(payload, run_id=job.run_id)
            store.mark_completed(job.run_id, result=result, message="简历定制完成。")
        except Exception as exc:  # pragma: no cover - defensive path for runtime errors
            store.mark_failed(job.run_id, str(exc))

    Thread(target=runner, daemon=True).start()
    running_job = store.mark_running(job.run_id, stage="queued", percent=5, message="任务已排队，准备优先分析 JD。")
    return running_job or job


@router.get("/tailor-runs/{run_id}/draft-versions", response_model=list[DraftVersion])
def get_draft_versions(run_id: str) -> list[DraftVersion]:
    job = get_run_store().get(run_id)
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    return job.result.draft_versions


@router.post("/tailor-runs/{run_id}/draft-diff", response_model=DraftDiffResponse)
def get_draft_diff(run_id: str, payload: DraftDiffRequest) -> DraftDiffResponse:
    job = get_run_store().get(run_id)
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    return build_draft_diff(
        job.result.candidate_profile,
        job.result.fact_cards,
        payload.draft,
    )


@router.post("/tailor-runs/{run_id}/score", response_model=JDMatchScoreResponse)
def score_resume_draft(run_id: str, payload: JDMatchScoreRequest) -> JDMatchScoreResponse:
    job = get_run_store().get(run_id)
    if job is None or job.result is None:
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
def preview_resume_export(run_id: str, payload: ResumeExportRequest) -> Response:
    job = get_run_store().get(run_id)
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    pdf_bytes = build_pdf(payload.draft, job.result.candidate_profile)
    page_count = pdf_page_count(pdf_bytes)
    return Response(
        content=pdf_bytes,
        media_type=PDF_MEDIA_TYPE,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": "inline; filename=resume-preview.pdf",
            "X-Page-Count": str(page_count),
            "X-Overflow": "true" if page_count > 1 else "false",
        },
    )


@router.post("/tailor-runs/{run_id}/export/{export_format}")
def export_resume(run_id: str, export_format: str, payload: ResumeExportRequest) -> Response:
    job = get_run_store().get(run_id)
    if job is None or job.result is None:
        raise HTTPException(status_code=404, detail="Completed run not found.")
    normalized_format = export_format.lower()
    if normalized_format == "docx":
        content = build_docx(payload.draft, job.result.candidate_profile)
        media_type = DOCX_MEDIA_TYPE
    elif normalized_format == "pdf":
        content = build_pdf(payload.draft, job.result.candidate_profile)
        media_type = PDF_MEDIA_TYPE
    else:
        raise HTTPException(status_code=400, detail="Export format must be docx or pdf.")

    filename = "{0}.{1}".format(sanitize_filename(payload.filename), normalized_format)
    encoded_filename = quote(filename, safe="")
    return Response(
        content=content,
        media_type=media_type,
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": (
                "attachment; filename=tailored-resume.{0}; filename*=UTF-8''{1}".format(
                    normalized_format,
                    encoded_filename,
                )
            ),
        },
    )


@router.put("/tailor-runs/{run_id}/draft", response_model=DraftMutationResponse)
def save_manual_draft(run_id: str, payload: DraftSaveRequest) -> DraftMutationResponse:
    store = get_run_store()
    job = store.get(run_id)
    if job is None or job.result is None:
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
def rewrite_draft_part(run_id: str, payload: PartialRewriteRequest) -> DraftMutationResponse:
    if payload.target_type not in VALID_PARTIAL_TARGETS:
        raise HTTPException(status_code=400, detail="Unsupported partial rewrite target.")
    store = get_run_store()
    job = store.get(run_id)
    if job is None or job.result is None:
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
    try:
        content = await resume_file.read()
        resume_text = extract_text_from_file(resume_file.filename or "resume.txt", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Uploaded resume file did not yield readable text.")
    return resume_text


@router.get("/tailor-runs/{run_id}/status", response_model=TailorRunJobStatus)
def get_tailor_run_status(run_id: str) -> TailorRunJobStatus:
    job = get_run_store().get(run_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return job


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
    return HTTPException(
        status_code=503,
        detail="当前已关闭启发式 fallback，系统需要可用的大模型链路才能运行。原始错误：{0}".format(str(exc)),
    )
