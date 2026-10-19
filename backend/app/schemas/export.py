from pydantic import BaseModel
from typing import Optional
from backend.app.schemas.preferences import ResumeTemplateId

from backend.app.schemas.strategy import ResumeDraft


class ResumeExportRequest(BaseModel):
    draft: ResumeDraft
    filename: str = "tailored-resume"
    template: Optional[ResumeTemplateId] = None
