from typing import List

from pydantic import BaseModel, Field

from backend.app.schemas.jd import KnowledgeReviewCard


class JDReviewDocument(BaseModel):
    title: str = "JD 复习文档"
    role_summary: str = ""
    hiring_track_hint: str = ""
    core_requirements: List[str] = Field(default_factory=list)
    key_topics: List[KnowledgeReviewCard] = Field(default_factory=list)
    foundational_questions: List[str] = Field(default_factory=list)
    review_plan: List[str] = Field(default_factory=list)
    markdown: str = ""


class InterviewPrepDocument(BaseModel):
    title: str = "面试准备文档"
    prep_summary: str = ""
    likely_focus_areas: List[str] = Field(default_factory=list)
    ba_gu_questions: List[str] = Field(default_factory=list)
    project_deep_dive_questions: List[str] = Field(default_factory=list)
    experience_deep_dive_questions: List[str] = Field(default_factory=list)
    behavioral_questions: List[str] = Field(default_factory=list)
    risk_alerts: List[str] = Field(default_factory=list)
    answer_framework: List[str] = Field(default_factory=list)
    markdown: str = ""
