from typing import Dict, List

from pydantic import BaseModel, Field


class FactCard(BaseModel):
    id: str
    category: str
    text: str
    source_type: str = "resume"
    source_span: str = ""
    evidence_level: str = "explicit"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    allowed_operations: List[str] = Field(
        default_factory=lambda: ["rewrite", "reorder", "highlight"]
    )


class TraceabilityRecord(BaseModel):
    draft_span: str
    fact_ids: List[str] = Field(default_factory=list)


class AgentExecutionRecord(BaseModel):
    agent_name: str
    summary: str
    metadata: Dict[str, str] = Field(default_factory=dict)

