from typing import Dict, List

from pydantic import BaseModel, Field


class ComplianceReport(BaseModel):
    risk_level: str = "low"
    unsupported_claims: List[str] = Field(default_factory=list)
    blocked_phrases: List[str] = Field(default_factory=list)
    exaggeration_warnings: List[str] = Field(default_factory=list)
    seniority_mismatches: List[str] = Field(default_factory=list)
    keyword_stuffing_warnings: List[str] = Field(default_factory=list)


class ATSKeywordDetail(BaseModel):
    keyword: str
    category: str
    matched: bool = False
    locations: List[str] = Field(default_factory=list)


class ATSScoreReason(BaseModel):
    category: str
    impact: int = 0
    message: str
    location: str = ""


class ATSReport(BaseModel):
    score: int = 0
    keyword_coverage: float = 0.0
    core_keyword_score: int = 0
    optional_keyword_score: int = 0
    structure_score: int = 0
    truthfulness_score: int = 100
    matched_keywords: List[str] = Field(default_factory=list)
    missing_keywords: List[str] = Field(default_factory=list)
    matched_core_keywords: List[str] = Field(default_factory=list)
    missing_core_keywords: List[str] = Field(default_factory=list)
    matched_optional_keywords: List[str] = Field(default_factory=list)
    missing_optional_keywords: List[str] = Field(default_factory=list)
    keyword_details: List[ATSKeywordDetail] = Field(default_factory=list)
    format_warnings: List[str] = Field(default_factory=list)
    deductions: List[str] = Field(default_factory=list)
    score_reasons: List[ATSScoreReason] = Field(default_factory=list)
    section_presence: Dict[str, bool] = Field(default_factory=dict)
    disclaimer: str = "JD 匹配参考分仅用于比较简历内容与当前 JD 的文本和结构匹配度，不代表 ATS 通过概率、面试机会或录用结果。"


class CriticReport(BaseModel):
    major_issues: int = 0
    minor_issues: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)


class ReviewBundle(BaseModel):
    iteration: int
    compliance_report: ComplianceReport
    ats_report: ATSReport
    critic_report: CriticReport
