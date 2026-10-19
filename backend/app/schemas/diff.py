from typing import List, Optional

from pydantic import BaseModel, Field

from backend.app.schemas.strategy import ResumeDraft


class DraftDiffRequest(BaseModel):
    draft: ResumeDraft


class DraftDiffItem(BaseModel):
    id: str
    change_type: str
    target_type: str
    label: str
    original_text: str = ""
    revised_text: str = ""
    draft_span: str = ""
    section_index: Optional[int] = None
    item_index: Optional[int] = None
    restore_section_index: Optional[int] = None
    fact_ids: List[str] = Field(default_factory=list)
    source_excerpts: List[str] = Field(default_factory=list)
    risk_level: str = "low"
    risk_message: str = ""


class DraftDiffResponse(BaseModel):
    version_id: str = ""
    items: List[DraftDiffItem] = Field(default_factory=list)
    added_count: int = 0
    modified_count: int = 0
    removed_count: int = 0
    ungrounded_count: int = 0
