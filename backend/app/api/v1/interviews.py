from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response

from backend.app.agents.mock_interview import MockInterviewAgent
from backend.app.api.v1.routes import _get_authorized_run
from backend.app.schemas.interview import InterviewAnswer, InterviewFinish, InterviewStart, InterviewSummary, InterviewView
from backend.app.services.interviews import InterviewConflict, get_interview_store, interview_report
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.provenance import capture_provenance
from backend.app.services.runs.store import get_run_store

router = APIRouter(prefix="/tailor-runs/{run_id}/interviews", tags=["mock-interviews"])


def view(session):
    if session is None:
        raise HTTPException(404, "面试练习不存在或已过期。")
    return InterviewView(session=session, current_question=session.current_question, report=interview_report(session))


def get_session(run_id, session_id, token):
    _get_authorized_run(run_id, token)
    session = get_interview_store().get(run_id, session_id)
    if session is None:
        raise HTTPException(404, "面试练习不存在或已过期。")
    return session


@router.post("", response_model=InterviewView, status_code=201)
def start_interview(run_id: str, payload: InterviewStart, x_run_token: Optional[str] = Header(None)):
    job = _get_authorized_run(run_id, x_run_token)
    if job.result is None:
        raise HTTPException(409, "请先完成简历生成并保存版本。")
    version = next((version for version in job.result.draft_versions if version.id == payload.version_id), None)
    if version is None:
        raise HTTPException(404, "已保存的简历版本不存在。")
    session = get_interview_store().create(job, version, payload.rounds)
    if get_run_store().get(run_id) is None:
        get_interview_store().delete_for_run(run_id)
        raise HTTPException(404, "生成任务已删除或过期。")
    return view(session)


@router.get("", response_model=list[InterviewSummary])
def list_interviews(run_id: str, x_run_token: Optional[str] = Header(None)):
    _get_authorized_run(run_id, x_run_token)
    return get_interview_store().list(run_id)


@router.get("/{session_id}", response_model=InterviewView)
def read_interview(run_id: str, session_id: str, x_run_token: Optional[str] = Header(None)):
    return view(get_session(run_id, session_id, x_run_token))


@router.post("/{session_id}/answers", response_model=InterviewView)
def answer_interview(run_id: str, session_id: str, payload: InterviewAnswer, x_run_token: Optional[str] = Header(None)):
    session = get_session(run_id, session_id, x_run_token)
    try:
        if not get_interview_store().check_answer(session, payload):
            return view(session)
        feedback = MockInterviewAgent().evaluate(session, payload.answer)
        updated = get_interview_store().submit(run_id, session_id, payload, feedback, capture_provenance("mock_interview"))
    except InterviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except StructuredLLMError as exc:
        raise HTTPException(503, "模型反馈暂时不可用；回答尚未保存，请保留文字并稍后重试。") from exc
    return view(updated)


@router.post("/{session_id}/finish", response_model=InterviewView)
def finish_interview(run_id: str, session_id: str, payload: InterviewFinish, x_run_token: Optional[str] = Header(None)):
    get_session(run_id, session_id, x_run_token)
    try:
        return view(get_interview_store().finish(run_id, session_id, payload.expected_revision))
    except InterviewConflict as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{session_id}/report")
def export_interview_report(run_id: str, session_id: str, x_run_token: Optional[str] = Header(None)):
    session = get_session(run_id, session_id, x_run_token)
    return Response(interview_report(session), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="interview-review.md"', "Cache-Control": "no-store"})


@router.delete("/{session_id}", status_code=204)
def delete_interview(run_id: str, session_id: str, x_run_token: Optional[str] = Header(None)):
    get_session(run_id, session_id, x_run_token)
    get_interview_store().delete(run_id, session_id)
    return Response(status_code=204)
