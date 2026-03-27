from typing import Dict, List

from pydantic import BaseModel, Field


class ComplianceReport(BaseModel):
    risk_level: str = "low"
    unsupported_claims: List[str] = Field(default_factory=list)
    blocked_phrases: List[str] = Field(default_factory=list)
    exaggeration_warnings: List[str] = Field(default_factory=list)
    seniority_mismatches: List[str] = Field(default_factory=list)
    keyword_stuffing_warnings: List[str] = Field(default_factory=list)


class ATSReport(BaseModel):
    score: int = 0
    keyword_coverage: float = 0.0
    matched_keywords: List[str] = Field(default_factory=list)
    missing_keywords: List[str] = Field(default_factory=list)
    format_warnings: List[str] = Field(default_factory=list)
    section_presence: Dict[str, bool] = Field(default_factory=dict)


class CriticReport(BaseModel):
    major_issues: int = 0
    minor_issues: List[str] = Field(default_factory=list)
    next_actions: List[str] = Field(default_factory=list)


class ReviewBundle(BaseModel):
    iteration: int
    compliance_report: ComplianceReport
    ats_report: ATSReport
    critic_report: CriticReport
