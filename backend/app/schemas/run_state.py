from typing import List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import AgentExecutionRecord, FactCard
from backend.app.schemas.jd import JDProfile, KnowledgeReviewCard
from backend.app.schemas.prep import InterviewPrepDocument, JDReviewDocument
from backend.app.schemas.review import ATSReport, ComplianceReport, ReviewBundle
from backend.app.schemas.strategy import FinalResumePackage, GapAnalysis, ResumeDraft, RewriteStrategy


class FollowUpQuestion(BaseModel):
    id: str
    prompt: str
    reason: str = ""
    priority: str = "optional"
    suggested_category: str = "general"
    related_keywords: List[str] = Field(default_factory=list)


class TailorRunInput(BaseModel):
    resume_text: str = ""
    jd_text: str = ""
    candidate_notes: str = ""
    output_language: str = "auto"
    max_iterations: int = 2
    processing_mode: str = "full"
    confirmed_candidate_profile: Optional[CandidateProfile] = None
    confirmed_fact_cards: List[FactCard] = Field(default_factory=list)
    preanalyzed_jd_profile: Optional[JDProfile] = None
    target_company: str = Field(default="", max_length=120)
    target_role: str = Field(default="", max_length=120)

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
        if normalized not in {"full", "fast", "application"}:
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
    jd_review_doc: Optional[JDReviewDocument] = None
    gap_analysis: Optional[GapAnalysis] = None
    rewrite_strategy: Optional[RewriteStrategy] = None
    drafts: List[ResumeDraft] = Field(default_factory=list)
    reviews: List[ReviewBundle] = Field(default_factory=list)
    interview_prep_doc: Optional[InterviewPrepDocument] = None
    final_package: Optional[FinalResumePackage] = None
    stop_reason: str = ""
    execution_log: List[AgentExecutionRecord] = Field(default_factory=list)


class DraftVersion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str
    source: str = "manual"
    label: str = "已保存版本"
    archived: bool = False
    draft: ResumeDraft
    compliance_report: ComplianceReport
    ats_report: ATSReport


class TailorRunResult(BaseModel):
    run_id: str
    status: str
    iterations: int
    stop_reason: str
    candidate_profile: CandidateProfile
    jd_profile: JDProfile
    gap_analysis: GapAnalysis
    rewrite_strategy: RewriteStrategy
    fact_cards: List[FactCard] = Field(default_factory=list)
    drafts: List[ResumeDraft]
    reviews: List[ReviewBundle]
    final_package: FinalResumePackage
    draft_versions: List[DraftVersion] = Field(default_factory=list)
    active_version_id: str = ""


class StageExecutionRecord(BaseModel):
    stage: str
    status: str
    attempt: int = 1
    started_at: str = ""
    finished_at: str = ""
    duration_ms: int = 0
    error_type: str = ""


class TailorRunJobStatus(BaseModel):
    run_id: str
    candidate_archive_id: str = ""
    candidate_archive_revision: int = 0
    target_job_title: str = ""
    target_company: str = ""
    jd_text: str = ""
    archived: bool = False
    access_token: Optional[str] = None
    created_at: str = ""
    expires_at: str = ""
    status: str = "queued"
    progress_percent: int = 0
    current_stage: str = ""
    status_message: str = ""
    error_message: str = ""
    error_type: str = ""
    failed_stage: str = ""
    attempt_count: int = 0
    max_attempts: int = 3
    retryable: bool = False
    stage_history: List[StageExecutionRecord] = Field(default_factory=list)
    review_cards: List[KnowledgeReviewCard] = Field(default_factory=list)
    result: Optional[TailorRunResult] = None


class ResumeParsePreview(BaseModel):
    resume_text: str
    candidate_profile: CandidateProfile
    fact_cards: List[FactCard] = Field(default_factory=list)
    jd_profile: Optional[JDProfile] = None
    gap_analysis: Optional[GapAnalysis] = None
    follow_up_questions: List[FollowUpQuestion] = Field(default_factory=list)


class DraftSaveRequest(BaseModel):
    draft: ResumeDraft
    label: str = "手工保存"


class PartialRewriteRequest(BaseModel):
    draft: ResumeDraft
    target_type: str
    section_index: Optional[int] = None
    item_index: Optional[int] = None
    instruction: str = ""


class DraftMutationResponse(BaseModel):
    version: DraftVersion
    versions: List[DraftVersion] = Field(default_factory=list)
