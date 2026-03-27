from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from backend.app.schemas.common import TraceabilityRecord


class GapAnalysis(BaseModel):
    fit_score_initial: int = 0
    strengths: List[str] = Field(default_factory=list)
    gaps: List[str] = Field(default_factory=list)
    transferable_experiences: List[str] = Field(default_factory=list)
    missing_keywords: List[str] = Field(default_factory=list)
    risk_points: List[str] = Field(default_factory=list)
    recommended_focus: List[str] = Field(default_factory=list)


class RewriteStrategy(BaseModel):
    target_resume_style: str = "ats_clean"
    audience_hint: str = "general"
    section_priority: List[str] = Field(
        default_factory=lambda: ["summary", "skills", "experience", "projects", "education"]
    )
    emphasize_fact_ids: List[str] = Field(default_factory=list)
    deemphasize_fact_ids: List[str] = Field(default_factory=list)
    keyword_plan: List[str] = Field(default_factory=list)
    terminology_map: Dict[str, str] = Field(default_factory=dict)
    tone_rules: List[str] = Field(default_factory=list)
    forbidden_claims: List[str] = Field(default_factory=list)
    max_experiences: int = 3
    max_bullets_per_experience: int = 3
    max_skills: int = 12
    include_projects: bool = False
    summary_style: str = "balanced"
    revision_notes: List[str] = Field(default_factory=list)


class ResumeSectionItem(BaseModel):
    heading: str
    subheading: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)


class ResumeDraft(BaseModel):
    headline: str = ""
    summary: str = ""
    skills_section: List[str] = Field(default_factory=list)
    experience_section: List[ResumeSectionItem] = Field(default_factory=list)
    project_section: List[ResumeSectionItem] = Field(default_factory=list)
    education_section: List[str] = Field(default_factory=list)
    markdown: str = ""
    traceability: List[TraceabilityRecord] = Field(default_factory=list)


class FinalResumePackage(BaseModel):
    draft: ResumeDraft
    change_log: List[str] = Field(default_factory=list)
    fit_summary: str = ""
    risk_notes: List[str] = Field(default_factory=list)
