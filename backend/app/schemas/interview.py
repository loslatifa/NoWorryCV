from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator

from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.quality import GenerationProvenance
from backend.app.schemas.strategy import ResumeDraft


class InterviewStart(BaseModel):
    version_id: str = Field(min_length=1, max_length=100)
    rounds: int = Field(default=3, ge=3, le=6)


class InterviewQuestion(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    round_number: int
    kind: Literal["experience", "knowledge", "reflection", "follow_up"]
    prompt: str
    jd_reference: str
    resume_reference: str
    fact_ids: List[str] = Field(default_factory=list)
    parent_question_id: str = ""


class AnswerAssessment(BaseModel):
    score: int = Field(ge=0, le=4)
    reason: str = Field(min_length=1, max_length=700)
    answer_quote: str = Field(default="", max_length=500)


class AnswerIssue(BaseModel):
    kind: Literal["inconsistent", "unverified", "expression"]
    answer_quote: str = Field(min_length=1, max_length=500)
    fact_ids: List[str] = Field(default_factory=list, max_length=20)
    explanation: str = Field(min_length=1, max_length=700)
    recommendation: str = Field(min_length=1, max_length=700)


class InterviewFeedback(BaseModel):
    structure: AnswerAssessment
    evidence: AnswerAssessment
    clarity: AnswerAssessment
    consistency: AnswerAssessment
    issues: List[AnswerIssue] = Field(default_factory=list, max_length=12)
    suggestions: List[str] = Field(default_factory=list, max_length=6)
    follow_up_focus: Literal["none", "scope", "measurement", "reasoning", "result"] = "none"
    follow_up_quote: str = Field(default="", max_length=200)
    method: Literal["heuristic", "model"] = "heuristic"


class InterviewAnswer(BaseModel):
    question_id: str = Field(min_length=1, max_length=100)
    expected_revision: int = Field(ge=1)
    answer: str = Field(min_length=1, max_length=6000)

    @field_validator("answer")
    @classmethod
    def nonblank_answer(cls, value):
        value = value.strip()
        if not value:
            raise ValueError("请填写回答后再提交。")
        return value


class InterviewTurn(BaseModel):
    question: InterviewQuestion
    answer: str
    answered_at: str
    feedback: InterviewFeedback
    provenance: GenerationProvenance = Field(default_factory=GenerationProvenance)


class InterviewSession(BaseModel):
    id: str
    run_id: str
    version_id: str
    version_label: str
    language: str
    rounds: int
    revision: int = 1
    status: Literal["active", "completed", "stopped"] = "active"
    created_at: str
    updated_at: str
    expires_at: str
    draft: ResumeDraft
    jd_profile: JDProfile
    fact_cards: List[FactCard]
    questions: List[InterviewQuestion]
    turns: List[InterviewTurn] = Field(default_factory=list)
    provenance: GenerationProvenance = Field(default_factory=GenerationProvenance)

    @property
    def current_question(self) -> Optional[InterviewQuestion]:
        return self.questions[len(self.turns)] if self.status == "active" and len(self.turns) < len(self.questions) else None


class InterviewSummary(BaseModel):
    id: str
    version_id: str
    version_label: str
    status: str
    rounds: int
    answered_count: int
    question_count: int
    created_at: str
    updated_at: str
    expires_at: str


class InterviewView(BaseModel):
    session: InterviewSession
    current_question: Optional[InterviewQuestion]
    report: str


class InterviewFinish(BaseModel):
    expected_revision: int = Field(ge=1)
