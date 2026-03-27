from typing import List

from pydantic import BaseModel, Field


class KnowledgeReviewCard(BaseModel):
    id: str
    title: str
    focus_area: str = ""
    why_it_matters: str = ""
    review_tip: str = ""
    sample_question: str = ""
    keywords: List[str] = Field(default_factory=list)


class KnowledgeReviewCardDeck(BaseModel):
    review_cards: List[KnowledgeReviewCard] = Field(default_factory=list)


class JDProfile(BaseModel):
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
    review_cards: List[KnowledgeReviewCard] = Field(default_factory=list)
