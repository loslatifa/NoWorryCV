from typing import List, Optional

from backend.app.schemas.preferences import ResumePreferences

from pydantic import BaseModel, Field, model_validator

from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile


class CandidateArchiveSave(BaseModel):
    label: str = Field(default="基础档案", min_length=1, max_length=80)
    candidate_profile: CandidateProfile
    fact_cards: List[FactCard]
    confirmed: bool = False
    storage_consent: bool = False
    expected_revision: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_confirmation(self):
        if not self.confirmed or not self.storage_consent:
            raise ValueError("请确认资料准确并同意长期保存基础档案。")
        if not self.label.strip():
            raise ValueError("档案名称不能为空。")
        if not self.fact_cards or any(not fact.confirmed or not fact.text.strip() for fact in self.fact_cards):
            raise ValueError("基础档案只能保存非空且已确认的事实。")
        ids = [fact.id for fact in self.fact_cards]
        if any(not fact_id.strip() for fact_id in ids) or len(ids) != len(set(ids)):
            raise ValueError("事实 ID 必须非空且唯一。")
        return self


class CandidateArchive(BaseModel):
    id: str
    label: str
    revision: int
    created_at: str
    updated_at: str
    candidate_profile: CandidateProfile
    fact_cards: List[FactCard]
    preferences: ResumePreferences = Field(default_factory=ResumePreferences)
    preferences_revision: int = 1
    access_token: Optional[str] = None


class ProfileJobRequest(BaseModel):
    preferences: Optional[ResumePreferences] = None
    jd_text: str = Field(min_length=1)
    candidate_notes: str = ""
    output_language: str = "auto"
    max_iterations: int = 2
    expected_revision: int = Field(ge=1)
    preanalyzed_jd_profile: Optional[JDProfile] = None
    target_company: str = Field(default="", max_length=120)
    target_role: str = Field(default="", max_length=120)


class ProfileRunReference(BaseModel):
    run_id: str
    profile_revision: int
    status: str
    created_at: str
    job_title: str = ""
    affected: bool


class ProfileUsage(BaseModel):
    current_revision: int
    runs: List[ProfileRunReference] = Field(default_factory=list)
