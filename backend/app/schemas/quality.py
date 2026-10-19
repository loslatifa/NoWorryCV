from typing import List, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


class GenerationProvenance(BaseModel):
    provider: str = "unknown"
    model: str = "unknown"
    prompt_version: str = "unknown"
    prompt_digest: str = ""
    scoring_version: str = "unknown"
    scoring_digest: str = ""
    pipeline_digest: str = ""
    processing_mode: str = "full"
    strict_mode: bool = True
    fingerprint: str = "unknown"


class QualityCredential(BaseModel):
    id: str
    token: str


class QualityQuery(BaseModel):
    runs: List[QualityCredential] = Field(default_factory=list, max_length=200)
    archives: List[QualityCredential] = Field(default_factory=list, max_length=100)
    hiring_track: Literal["all", "campus", "intern", "experienced", "unknown"] = "all"
    language: Literal["all", "zh", "en", "unknown"] = "all"


class FeedbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str = Field(min_length=1, max_length=100)
    scope: Literal["result", "change"] = "result"
    target_id: str = Field(default="", max_length=200)
    rating: int = Field(ge=1, le=5)
    reason: Literal["none", "accuracy", "relevance", "clarity", "format", "missing_information"] = "none"

    @model_validator(mode="after")
    def validate_target(self):
        if (self.scope == "result" and self.target_id) or (self.scope == "change" and not self.target_id):
            raise ValueError("整份反馈不指定修改项；单条反馈必须指定修改项。")
        return self


class FeedbackRecord(FeedbackRequest):
    id: str
    created_at: str
    updated_at: str
    source: str = "unknown"
    provenance: GenerationProvenance = Field(default_factory=GenerationProvenance)


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version_id: str = Field(min_length=1, max_length=100)
    target_id: str = Field(min_length=1, max_length=200)
    decision: Literal["accepted", "rejected"]
    event_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1, max_length=100)


class QualityMetrics(BaseModel):
    started_runs: int = 0
    completed_runs: int = 0
    reviewed_runs: int = 0
    edited_runs: int = 0
    exported_runs: int = 0
    confirmed_runs: int = 0
    feedback_count: int = 0
    average_rating: Optional[float] = None
    change_feedback_count: int = 0
    average_change_rating: Optional[float] = None
    satisfaction_rate: Optional[float] = None
    accepted_changes: int = 0
    rejected_changes: int = 0
    change_acceptance_rate: Optional[float] = None
    export_rate: Optional[float] = None


class QualityBreakdown(BaseModel):
    key: str
    metrics: QualityMetrics


class QualityDashboard(BaseModel):
    metrics: QualityMetrics
    by_hiring_track: List[QualityBreakdown] = Field(default_factory=list)
    by_language: List[QualityBreakdown] = Field(default_factory=list)
    by_generation_version: List[QualityBreakdown] = Field(default_factory=list)
    daily_trend: List[QualityBreakdown] = Field(default_factory=list)
    provenance: List[GenerationProvenance] = Field(default_factory=list)
    unavailable_run_ids: List[str] = Field(default_factory=list)
    disclaimer: str = "指标覆盖仍在保存期内的任务；仅明确提交的评分与修改决策参与反馈统计。满意率为整份评分达到 4 分的比例，导出率为已完成任务中成功生成文件的比例，不代表招聘结果。"
