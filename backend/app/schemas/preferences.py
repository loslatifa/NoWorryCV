from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from backend.app.services.template_catalog import TEMPLATE_OPTIONS

ResumeTemplateId = Literal[tuple(TEMPLATE_OPTIONS)]


class ResumePreferences(BaseModel):
    """Explicit choices; auto preserves job detection and the legacy export format."""

    model_config = ConfigDict(extra="forbid")
    region: Literal["auto", "CN", "HK", "SG", "US", "CA", "UK", "EU"] = "auto"
    job_family: Literal["auto", "engineering", "data", "product", "design", "marketing", "operations", "finance"] = "auto"
    hiring_track: Literal["auto", "campus", "intern", "experienced"] = "auto"
    seniority: Literal["auto", "junior", "mid", "senior", "lead"] = "auto"
    language: Literal["auto", "zh", "en"] = "auto"
    tone: Literal["balanced", "concise", "formal"] = "balanced"
    page_count: Literal["auto", "1", "2"] = "auto"
    template: ResumeTemplateId = "ats_standard"


class PreferencesSave(BaseModel):
    preferences: ResumePreferences
    expected_preferences_revision: int = Field(ge=1)


PREFERENCE_OPTIONS = {
    "region": {"auto": "默认（Letter）", "CN": "中国大陆（A4）", "HK": "中国香港（A4）", "SG": "新加坡（A4）", "US": "美国（Letter）", "CA": "加拿大（Letter）", "UK": "英国（A4）", "EU": "欧洲（A4）"},
    "job_family": {"auto": "跟随岗位要求", "engineering": "研发 / 工程", "data": "数据 / 分析", "product": "产品", "design": "设计", "marketing": "市场 / 增长", "operations": "运营", "finance": "财务 / 金融"},
    "hiring_track": {"auto": "自动识别", "campus": "校园招聘", "intern": "实习", "experienced": "社会招聘"},
    "seniority": {"auto": "自动识别", "junior": "初级", "mid": "中级", "senior": "高级", "lead": "负责人"},
    "language": {"auto": "跟随 JD", "zh": "中文", "en": "英文"},
    "tone": {"balanced": "均衡", "concise": "简洁", "formal": "正式"},
    "page_count": {"auto": "默认（建议 1 页）", "1": "目标 1 页", "2": "目标 2 页"},
    "template": TEMPLATE_OPTIONS,
}
