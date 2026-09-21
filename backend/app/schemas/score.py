from pydantic import BaseModel

from backend.app.schemas.review import ATSReport, ComplianceReport
from backend.app.schemas.strategy import ResumeDraft


class JDMatchScoreRequest(BaseModel):
    draft: ResumeDraft


class JDMatchScoreResponse(BaseModel):
    baseline: ATSReport
    tailored: ATSReport
    score_delta: int = 0
    compliance_report: ComplianceReport
