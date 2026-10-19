from datetime import datetime, timezone
from typing import Dict, List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.preferences import ResumePreferences
from backend.app.schemas.quality import GenerationProvenance
from backend.app.schemas.strategy import ResumeDraft
from backend.app.schemas.history import HistoryCredential
from backend.app.schemas.material import MaterialPack

PositionStatus = Literal["pending", "applied", "assessment", "interview", "offer", "closed"]
STATUS_LABELS = {"pending": "待投递", "applied": "已投递", "assessment": "笔试", "interview": "面试", "offer": "Offer", "closed": "关闭"}


class PositionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    company: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)
    jd_text: str = Field(min_length=1, max_length=30000)
    job_url: Optional[HttpUrl] = None
    storage_consent: bool = False

    @field_validator("company", "role", "jd_text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("公司、职位和 JD 不能为空。")
        return value.strip()

    @model_validator(mode="after")
    def consent(self):
        if not self.storage_consent:
            raise ValueError("请同意将职位保存至主动删除。")
        return self


class PositionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=1)
    company: Optional[str] = Field(default=None, min_length=1, max_length=120)
    role: Optional[str] = Field(default=None, min_length=1, max_length=120)
    jd_text: Optional[str] = Field(default=None, min_length=1, max_length=30000)
    job_url: Optional[HttpUrl] = None
    status: Optional[PositionStatus] = None
    next_action: Optional[str] = Field(default=None, max_length=1000)
    remind_at: Optional[datetime] = None
    note: str = Field(default="", max_length=1000)

    @field_validator("remind_at")
    @classmethod
    def timezone_required(cls, value):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("提醒时间需要明确时区。")
            return value.astimezone(timezone.utc)
        return value

    @model_validator(mode="after")
    def valid_fields(self):
        for key in self.model_fields_set & {"company", "role", "jd_text", "status", "next_action"}:
            value = getattr(self, key)
            if value is None or (key != "next_action" and not value.strip()):
                raise ValueError("职位内容和状态不能设置为空。")
            setattr(self, key, value.strip())
        return self


class PositionRevision(BaseModel):
    expected_revision: int = Field(ge=1)


class PositionGenerate(PositionRevision):
    expected_profile_revision: int = Field(ge=1)
    max_iterations: int = Field(default=2, ge=1, le=3)


class PositionResumeLink(PositionRevision):
    run_id: str = Field(default="", max_length=100)
    version_id: str = Field(default="", max_length=100)
    application_id: str = Field(default="", max_length=100)
    run_token: str = Field(default="", max_length=200)
    storage_consent: bool = False

    @model_validator(mode="after")
    def valid_source(self):
        if not self.storage_consent:
            raise ValueError("请确认所选简历，并同意将材料长期关联到职位。")
        if bool(self.application_id) == bool(self.run_id and self.version_id):
            raise ValueError("请选择一个已保存版本或一个已确认投递快照。")
        if self.application_id and (self.run_id or self.version_id or self.run_token):
            raise ValueError("投递快照与生成版本只能选择其中一种来源。")
        return self


class PositionInterviewLink(PositionRevision):
    resume_id: str = Field(min_length=1, max_length=100)
    session_id: str = Field(min_length=1, max_length=100)
    run_token: str = Field(default="", max_length=200)
    storage_consent: bool = False

    @model_validator(mode="after")
    def consent(self):
        if not self.storage_consent:
            raise ValueError("请同意将含面试回答的复习报告长期关联到职位。")
        return self


class PositionPracticeQuery(BaseModel):
    runs: List[HistoryCredential] = Field(default_factory=list, max_length=200)


class PositionMaterialLink(PositionRevision):
    resume_id: str = Field(min_length=1, max_length=100)
    pack_id: str = Field(min_length=1, max_length=100)
    expected_pack_revision: int = Field(ge=1)
    run_token: str = Field(default="", max_length=200)
    storage_consent: bool = False

    @model_validator(mode="after")
    def consent(self):
        if not self.storage_consent:
            raise ValueError("请同意将已核对的求职材料包长期保存到职位。")
        return self


class PositionResume(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    source_kind: Literal["run", "application"]
    run_id: str
    source_profile_id: str = ""
    profile_revision: int = 0
    source_company: str = ""
    source_role: str = ""
    version_id: str = ""
    application_id: str = ""
    label: str
    captured_at: str
    draft_digest: str
    draft: ResumeDraft
    candidate_profile: CandidateProfile
    fact_cards: List[FactCard]
    jd_text: str
    jd_profile: Optional[JDProfile] = None
    preferences: ResumePreferences = Field(default_factory=ResumePreferences)
    resolved_language: str = "auto"
    risk_notes: List[str] = Field(default_factory=list)
    jd_review: str = ""
    interview_prep: str = ""
    provenance: GenerationProvenance = Field(default_factory=GenerationProvenance)


class PositionInterview(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    resume_id: str
    source_session_id: str
    source_revision: int
    captured_at: str
    status: str
    answered_count: int
    report: str


class PositionMaterial(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    resume_id: str
    captured_at: str
    pack: MaterialPack


class PositionEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    at: str
    kind: str
    summary: str
    changes: Dict[str, List[Optional[str]]] = Field(default_factory=dict)
    note: str = ""


class PositionRun(BaseModel):
    run_id: str
    created_at: str
    jd_text: str


class PositionRecord(BaseModel):
    id: str
    profile_id: str
    revision: int = 1
    company: str
    role: str
    jd_text: str
    job_url: str = ""
    status: PositionStatus = "pending"
    next_action: str = ""
    remind_at: Optional[str] = None
    created_at: str
    updated_at: str
    current_resume_id: Optional[str] = None
    resumes: List[PositionResume] = Field(default_factory=list)
    interviews: List[PositionInterview] = Field(default_factory=list)
    materials: List[PositionMaterial] = Field(default_factory=list)
    runs: List[PositionRun] = Field(default_factory=list)
    timeline: List[PositionEvent] = Field(default_factory=list)


class PositionSummary(BaseModel):
    id: str
    company: str
    role: str
    status: PositionStatus
    next_action: str
    remind_at: Optional[str]
    updated_at: str
    current_resume_label: str = ""
    resume_count: int
    interview_count: int
    reminder: Literal["none", "due", "upcoming"]
