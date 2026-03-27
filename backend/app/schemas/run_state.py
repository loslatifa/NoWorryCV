from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import AgentExecutionRecord, FactCard
from backend.app.schemas.jd import JDProfile, KnowledgeReviewCard
from backend.app.schemas.review import ReviewBundle
from backend.app.schemas.strategy import FinalResumePackage, GapAnalysis, ResumeDraft, RewriteStrategy


class TailorRunInput(BaseModel):
    resume_text: str = ""
    jd_text: str = ""
    candidate_notes: str = ""
    output_language: str = "auto"
    max_iterations: int = 2
    processing_mode: str = "full"

    @field_validator("max_iterations")
    @classmethod
    def validate_iterations(cls, value: int) -> int:
        if value < 1:
            return 1
        if value > 3:
            return 3
        return value

    @field_validator("processing_mode")
    @classmethod
    def validate_processing_mode(cls, value: str) -> str:
        normalized = (value or "full").strip().lower()
        if normalized not in {"full", "fast"}:
            return "full"
        return normalized


class TailorRunState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    input: TailorRunInput
    current_iteration: int = 0
    resolved_language: str = "auto"
    candidate_profile: Optional[CandidateProfile] = None
    fact_cards: List[FactCard] = Field(default_factory=list)
    jd_profile: Optional[JDProfile] = None
    gap_analysis: Optional[GapAnalysis] = None
    rewrite_strategy: Optional[RewriteStrategy] = None
    drafts: List[ResumeDraft] = Field(default_factory=list)
    reviews: List[ReviewBundle] = Field(default_factory=list)
    final_package: Optional[FinalResumePackage] = None
    stop_reason: str = ""
    execution_log: List[AgentExecutionRecord] = Field(default_factory=list)


class TailorRunResult(BaseModel):
    run_id: str
    status: str
    iterations: int
    stop_reason: str
    candidate_profile: CandidateProfile
    jd_profile: JDProfile
    gap_analysis: GapAnalysis
    rewrite_strategy: RewriteStrategy
    drafts: List[ResumeDraft]
    reviews: List[ReviewBundle]
    final_package: FinalResumePackage


class TailorRunJobStatus(BaseModel):
    run_id: str
    status: str = "queued"
    progress_percent: int = 0
    current_stage: str = ""
    status_message: str = ""
    error_message: str = ""
    review_cards: List[KnowledgeReviewCard] = Field(default_factory=list)
    result: Optional[TailorRunResult] = None
