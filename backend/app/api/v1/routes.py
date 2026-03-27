from threading import Thread

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from backend.app.agents.orchestrator import ResumeTailorOrchestrator
from backend.app.graph.resume_tailor_graph import analyze_jd_payload, parse_resume_payload, run_tailor_pipeline
from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.run_state import TailorRunInput, TailorRunJobStatus, TailorRunResult
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.parsers.file_parser import extract_text_from_file
from backend.app.services.runs.store import get_run_store

router = APIRouter(tags=["tailor"])


@router.post("/resume/parse", response_model=CandidateProfile)
def parse_resume(payload: TailorRunInput) -> CandidateProfile:
    try:
        return parse_resume_payload(payload)
    except StructuredLLMError as exc:
        raise _llm_required_error(exc) from exc


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
    try:
        content = await resume_file.read()
        resume_text = extract_text_from_file(resume_file.filename or "resume.txt", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Uploaded resume file did not yield readable text.")
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
    try:
        content = await resume_file.read()
        resume_text = extract_text_from_file(resume_file.filename or "resume.txt", content)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not resume_text.strip():
        raise HTTPException(status_code=400, detail="Uploaded resume file did not yield readable text.")
    if not jd_text.strip():
        raise HTTPException(status_code=400, detail="JD text cannot be empty.")

    payload = _build_upload_payload(
        resume_text=resume_text,
        jd_text=jd_text,
        candidate_notes=candidate_notes,
        output_language=output_language,
        max_iterations=max_iterations,
    )
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
