from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.quality import GenerationProvenance
from backend.app.schemas.strategy import ResumeDraft

MaterialKind = Literal["cover_letter", "intro_short", "intro_medium", "intro_long", "project_deep_dive", "hr_outreach", "hr_followup"]


class MaterialStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str = Field(min_length=1, max_length=100)


class MaterialEvidence(BaseModel):
    id: str
    text: str
    fact_ids: List[str]
    resume_span: str
    resume_text: str
    group: str


class MaterialPlan(BaseModel):
    """The model selects evidence, never supplies new candidate claims."""
    selections: Dict[MaterialKind, List[str]] = Field(default_factory=dict)


class MaterialIssue(BaseModel):
    quote: str
    reason: str


class MaterialDocument(BaseModel):
    id: MaterialKind
    title: str
    content: str
    original_content: str
    evidence_ids: List[str] = Field(default_factory=list)
    edited: bool = False
    reviewed: bool = False
    issues: List[MaterialIssue] = Field(default_factory=list)
    length_hint: str = ""


class MaterialPack(BaseModel):
    id: str
    run_id: str
    version_id: str
    version_label: str
    revision: int = 1
    created_at: str
    updated_at: str
    expires_at: str
    company: str
    role: str
    language: str
    jd_text: str
    jd_profile: JDProfile
    draft: ResumeDraft
    fact_cards: List[FactCard]
    evidence: List[MaterialEvidence]
    documents: List[MaterialDocument]
    notes: List[str] = Field(default_factory=list)
    method: Literal["model_selection", "rules"] = "rules"
    provenance: GenerationProvenance = Field(default_factory=GenerationProvenance)


class MaterialSummary(BaseModel):
    id: str
    version_id: str
    version_label: str
    created_at: str
    updated_at: str
    revision: int
    reviewed_count: int
    document_count: int


class MaterialEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    content: str = Field(min_length=1, max_length=16000)
    reviewed: bool = False

    @field_validator("content")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("材料内容不能为空。")
        return value.strip()
