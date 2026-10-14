from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.app.schemas.run_state import DraftVersion


class HistoryCredential(BaseModel):
    id: str
    token: str


class HistoryQuery(BaseModel):
    runs: List[HistoryCredential] = Field(default_factory=list, max_length=200)
    archives: List[HistoryCredential] = Field(default_factory=list, max_length=100)
    search: str = Field(default="", max_length=200)
    status: Literal["all", "queued", "running", "completed", "failed", "cancelled"] = "all"
    archive_filter: Literal["active", "archived", "all"] = "active"
    sort: Literal["newest", "oldest", "company", "role", "status"] = "newest"


class RunHistoryItem(BaseModel):
    run_id: str
    candidate_archive_id: str = ""
    company: str = ""
    job_title: str = ""
    jd_text: str = ""
    created_at: str
    expires_at: str
    status: str
    archived: bool
    version_count: int


class HistoryResponse(BaseModel):
    items: List[RunHistoryItem] = Field(default_factory=list)
    unavailable_run_ids: List[str] = Field(default_factory=list)


class RunMetadataUpdate(BaseModel):
    company: Optional[str] = Field(default=None, max_length=120)
    job_title: Optional[str] = Field(default=None, max_length=120)
    archived: Optional[bool] = None


class VersionMetadataUpdate(BaseModel):
    label: Optional[str] = Field(default=None, max_length=80)
    archived: Optional[bool] = None

    @field_validator("label")
    @classmethod
    def validate_label(cls, value):
        if value is not None and not value.strip():
            raise ValueError("版本名称不能为空。")
        return value.strip() if value is not None else None


class VersionReference(BaseModel):
    run_id: str
    version_id: str
    access_token: str


class VersionComparisonRequest(BaseModel):
    before: VersionReference
    after: VersionReference


class VersionDifference(BaseModel):
    field: str
    label: str
    before_text: str
    after_text: str
    change_type: Literal["added", "removed", "modified"]


class VersionComparisonResponse(BaseModel):
    before_label: str
    after_label: str
    before_job_title: str
    after_job_title: str
    differences: List[VersionDifference] = Field(default_factory=list)


class VersionListMutation(BaseModel):
    versions: List[DraftVersion]
    active_version_id: str
