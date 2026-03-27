from typing import Optional

from backend.app.agents.orchestrator import ResumeTailorOrchestrator
from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.run_state import TailorRunInput, TailorRunResult


def parse_resume_payload(payload: TailorRunInput) -> CandidateProfile:
    orchestrator = ResumeTailorOrchestrator()
    return orchestrator.parse_resume(payload)


def analyze_jd_payload(payload: TailorRunInput) -> JDProfile:
    orchestrator = ResumeTailorOrchestrator()
    return orchestrator.analyze_jd(payload)


def run_tailor_pipeline(payload: TailorRunInput, run_id: Optional[str] = None) -> TailorRunResult:
    orchestrator = ResumeTailorOrchestrator()
    return orchestrator.run(payload, run_id=run_id)
