from typing import Any, Dict, List, Literal, Optional

from backend.app.schemas.preferences import ResumePreferences

from pydantic import BaseModel, Field, HttpUrl, model_validator

from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from backend.app.schemas.strategy import ResumeDraft
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.quality import GenerationProvenance


class ApplicationCreate(BaseModel):
    preferences: Optional[ResumePreferences] = None
    page_url: HttpUrl
    job_url: Optional[HttpUrl] = None
    jd_text: str = Field(min_length=20, max_length=30000)
    target_company: str = Field(default="", max_length=120)
    target_role: str = Field(default="", max_length=120)
    expected_revision: int = Field(ge=1)
    output_language: Literal["auto", "zh", "en"] = "auto"

    @model_validator(mode="after")
    def nonempty_jd(self):
        if len(self.jd_text.strip()) < 20:
            raise ValueError("岗位要求过短，请检查识别结果或补充 JD。")
        return self


class ApplicationConfirm(BaseModel):
    draft_digest: str = Field(min_length=64, max_length=64)
    confirmed: bool = False
    storage_consent: bool = False

    @model_validator(mode="after")
    def require_consent(self):
        if not self.confirmed or not self.storage_consent:
            raise ValueError("请确认简历内容并同意保存本次岗位与简历版本。")
        return self


class FillOutcome(BaseModel):
    selector: str = Field(default="", max_length=2000)
    field_label: str = Field(default="", max_length=300)
    status: Literal["filled", "failed", "skipped"]
    reason: str = Field(default="", max_length=500)


class ApplicationFillReport(BaseModel):
    page_url: HttpUrl
    results: List[FillOutcome] = Field(default_factory=list, max_length=500)


class ApplicationRecord(BaseModel):
    id: str
    profile_id: str
    profile_revision: int
    run_id: str
    created_at: str
    updated_at: str
    expires_at: str = ""
    page_url: str
    job_url: str = ""
    jd_text: str
    target_company: str = ""
    target_role: str = ""
    status: str = "generating"
    progress_percent: int = 0
    status_message: str = ""
    draft_digest: str = ""
    confirmed_at: str = ""
    draft: Optional[ResumeDraft] = None
    candidate_profile: Optional[CandidateProfile] = None
    fact_cards: List[FactCard] = Field(default_factory=list)
    form_resume: Dict[str, Any] = Field(default_factory=dict)
    risk_notes: List[str] = Field(default_factory=list)
    change_log: List[str] = Field(default_factory=list)
    fill_report: Optional[ApplicationFillReport] = None
    version_id: str = ""
    jd_profile: Optional[JDProfile] = None
    jd_review: str = ""
    interview_prep: str = ""
    resolved_language: str = "auto"
    preferences: ResumePreferences = Field(default_factory=ResumePreferences)
    provenance: GenerationProvenance = Field(default_factory=GenerationProvenance)
