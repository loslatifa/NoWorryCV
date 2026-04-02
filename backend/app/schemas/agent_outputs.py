from typing import List, Optional

from pydantic import BaseModel, Field

class TraceableBullet(BaseModel):
    text: str
    fact_ids: List[str] = Field(default_factory=list)


class TraceableSectionItem(BaseModel):
    heading: str
    subheading: Optional[str] = None
    bullets: List[TraceableBullet] = Field(default_factory=list)


class ResumeDraftStructuredOutput(BaseModel):
    headline: str = ""
    summary: str = ""
    skills_section: List[str] = Field(default_factory=list)
    experience_section: List[TraceableSectionItem] = Field(default_factory=list)
    project_section: List[TraceableSectionItem] = Field(default_factory=list)
    education_section: List[str] = Field(default_factory=list)


class JDProfileStructuredOutput(BaseModel):
    job_title: str = ""
    department: str = ""
    seniority: str = "unknown"
    hiring_track: str = "unknown"
    responsibilities: List[str] = Field(default_factory=list)
    must_have_skills: List[str] = Field(default_factory=list)
    nice_to_have_skills: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    domain_signals: List[str] = Field(default_factory=list)
    language: str = "auto"


class CompactKnowledgeReviewCard(BaseModel):
    title: str = ""
    focus_area: str = ""
    keywords: List[str] = Field(default_factory=list)


class CompactKnowledgeReviewCardDeck(BaseModel):
    review_cards: List[CompactKnowledgeReviewCard] = Field(default_factory=list)


class JDReviewDocumentStructuredOutput(BaseModel):
    title: str = "JD 复习文档"
    role_summary: str = ""
    hiring_track_hint: str = ""
    core_requirements: List[str] = Field(default_factory=list)
    foundational_questions: List[str] = Field(default_factory=list)
    review_plan: List[str] = Field(default_factory=list)


class InterviewPrepDocumentStructuredOutput(BaseModel):
    title: str = "面试准备文档"
    prep_summary: str = ""
    likely_focus_areas: List[str] = Field(default_factory=list)
    ba_gu_questions: List[str] = Field(default_factory=list)
    project_deep_dive_questions: List[str] = Field(default_factory=list)
    experience_deep_dive_questions: List[str] = Field(default_factory=list)
    behavioral_questions: List[str] = Field(default_factory=list)
    risk_alerts: List[str] = Field(default_factory=list)
    answer_framework: List[str] = Field(default_factory=list)
