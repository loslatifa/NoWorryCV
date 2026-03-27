from typing import Dict, Optional, Type, TypeVar

from backend.app.schemas.common import AgentExecutionRecord
from backend.app.services.llm.structured import StructuredLLMError, StructuredLLMService, get_structured_llm_service

ModelT = TypeVar("ModelT")


class BaseAgent:
    name = "base"
    prompt_name = ""

    def __init__(self, llm_service: Optional[StructuredLLMService] = None) -> None:
        self.llm_service = llm_service or get_structured_llm_service()

    def record(self, summary: str, metadata: Dict[str, str] = None) -> AgentExecutionRecord:
        return AgentExecutionRecord(
            agent_name=self.name,
            summary=summary,
            metadata=metadata or {},
        )

    @property
    def prompt_key(self) -> str:
        return self.prompt_name or self.name

    def invoke_structured(self, context: Dict, response_model: Type[ModelT]) -> ModelT:
        try:
            return self.llm_service.generate(
                agent_name=self.prompt_key,
                context=context,
                response_model=response_model,
            )
        except StructuredLLMError:
            raise
