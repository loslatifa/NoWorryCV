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
