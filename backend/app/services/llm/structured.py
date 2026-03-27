import json
from functools import lru_cache
from typing import Any, Dict, Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

from backend.app.core.config import get_settings
from backend.app.services.llm.provider import LLMProvider, get_llm_provider
from backend.app.services.prompt_loader import PromptLoader, get_prompt_loader

ModelT = TypeVar("ModelT", bound=BaseModel)


class StructuredLLMError(RuntimeError):
    """Raised when structured output generation fails after retries."""


class StructuredLLMService:
    def __init__(
        self,
        provider: LLMProvider,
        prompt_loader: PromptLoader,
        max_retries: int = 2,
        response_format: str = "json_object",
    ) -> None:
        self.provider = provider
        self.prompt_loader = prompt_loader
        self.max_retries = max(1, max_retries)
        self.response_format = response_format

    @property
    def is_available(self) -> bool:
        return self.provider.is_available

    @property
    def provider_name(self) -> str:
        return getattr(self.provider, "name", "unknown")

    @property
    def prompt_version(self) -> str:
        return self.prompt_loader.default_version

    def generate(
        self,
        agent_name: str,
        context: Dict[str, Any],
        response_model: Type[ModelT],
        max_retries: Optional[int] = None,
    ) -> ModelT:
        if not self.is_available:
            raise StructuredLLMError("No live LLM provider available.")

        prompt = self.prompt_loader.load(agent_name)
        system_prompt = self._build_system_prompt(prompt)
        user_prompt = self._build_user_prompt(context, response_model)
        total_attempts = max_retries or self.max_retries
        last_error: Optional[Exception] = None
        response_format = self.response_format

        for _ in range(total_attempts):
            try:
                raw_output = self.provider.complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    metadata={
                        "expect_json": True,
                        "schema_name": response_model.__name__.lower(),
                        "json_schema": response_model.model_json_schema(),
                        "response_format": response_format,
                    },
                )
                payload = self._extract_json(raw_output)
                return response_model.model_validate_json(payload)
            except (ValidationError, ValueError, json.JSONDecodeError, RuntimeError, Exception) as exc:
                last_error = exc
                if response_format == "json_schema":
                    response_format = "json_object"

        raise StructuredLLMError("Structured output failed for agent '{0}': {1}".format(agent_name, last_error))

    def _build_system_prompt(self, prompt: str) -> str:
        return (
            "{0}\n\n"
            "You must return valid JSON only. Do not include markdown fences or commentary. "
            "Do not invent facts. If information is missing, use empty strings or empty arrays.".format(prompt)
        )

    def _build_user_prompt(self, context: Dict[str, Any], response_model: Type[BaseModel]) -> str:
        schema = response_model.model_json_schema()
        return (
            "Context JSON:\n{0}\n\n"
            "Target JSON Schema:\n{1}\n\n"
            "Return a single JSON object matching the schema exactly."
        ).format(
            json.dumps(self._to_jsonable(context), ensure_ascii=False, indent=2),
            json.dumps(schema, ensure_ascii=False, indent=2),
        )

    def _to_jsonable(self, value: Any) -> Any:
        if isinstance(value, BaseModel):
            return value.model_dump(mode="json")
        if isinstance(value, dict):
            return {key: self._to_jsonable(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self._to_jsonable(item) for item in value]
        return value

    def _extract_json(self, text: str) -> str:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                stripped = "\n".join(lines[1:-1]).strip()
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start == -1 or end == -1 or end < start:
            raise ValueError("Provider did not return a JSON object.")
        return stripped[start : end + 1]


@lru_cache
def get_structured_llm_service() -> StructuredLLMService:
    settings = get_settings()
    return StructuredLLMService(
        provider=get_llm_provider(),
        prompt_loader=get_prompt_loader(),
        max_retries=settings.llm_max_retries,
        response_format=settings.llm_response_format,
    )


def reset_structured_llm_service_cache() -> None:
    get_structured_llm_service.cache_clear()
