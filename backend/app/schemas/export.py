from pydantic import BaseModel

from backend.app.schemas.strategy import ResumeDraft


class ResumeExportRequest(BaseModel):
    draft: ResumeDraft
    filename: str = "tailored-resume"
