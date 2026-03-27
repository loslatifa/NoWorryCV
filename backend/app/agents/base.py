from typing import Any, Dict, Optional, Type, TypeVar

from backend.app.core.config import get_settings
from backend.app.schemas.common import AgentExecutionRecord
from backend.app.services.llm.structured import StructuredLLMError, StructuredLLMService, get_structured_llm_service

ModelT = TypeVar("ModelT")
_NO_FALLBACK = object()


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

    @property
    def strict_llm_mode(self) -> bool:
        return bool(get_settings().llm_strict_mode)

    def maybe_use_fallback(self, fallback_value: Any, force_fallback: bool = False) -> Any:
        if force_fallback:
            return fallback_value
        if not self.llm_service.is_available:
            if self.strict_llm_mode:
                raise StructuredLLMError(
                    "Agent '{0}' requires a live LLM provider; heuristic fallback is disabled.".format(self.name)
                )
            return fallback_value
        return _NO_FALLBACK

    def fallback_on_error(self, exc: StructuredLLMError, fallback_value: Any) -> Any:
        if self.strict_llm_mode:
            raise exc
        return fallback_value
