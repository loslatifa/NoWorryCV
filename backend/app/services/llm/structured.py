import json
import logging
import re
from functools import lru_cache
from typing import Any, Dict, List, Optional, Type, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from backend.app.core.config import get_settings
from backend.app.services.llm.provider import LLMOutputTruncatedError, LLMProvider, get_llm_provider
from backend.app.services.prompt_loader import PromptLoader, get_prompt_loader

ModelT = TypeVar("ModelT", bound=BaseModel)
logger = logging.getLogger(__name__)


class StructuredLLMError(RuntimeError):
    """Raised when structured output generation fails after retries."""

    def __init__(self, message: str, agent_name: str = "") -> None:
        super().__init__(message)
        self.agent_name = agent_name


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
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ModelT:
        if not self.is_available:
            raise StructuredLLMError("No live LLM provider available.", agent_name=agent_name)

        prompt = self.prompt_loader.load(agent_name)
        system_prompt = self._build_system_prompt(prompt)
        base_user_prompt = self._build_user_prompt(context, response_model)
        user_prompt = base_user_prompt
        total_attempts = max_retries or self.max_retries
        last_error: Optional[Exception] = None
        response_format = self.response_format
        request_metadata = dict(metadata or {})

        for _ in range(total_attempts):
            try:
                provider_metadata = {
                    **request_metadata,
                    "expect_json": True,
                    "schema_name": response_model.__name__.lower(),
                    "json_schema": response_model.model_json_schema(),
                    "response_format": response_format,
                }
                raw_output = self.provider.complete(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    metadata=provider_metadata,
                )
                payload_candidates = self._extract_json_candidates(raw_output)
                validation_error: Optional[Exception] = None
                for payload in payload_candidates:
                    try:
                        return response_model.model_validate_json(payload)
                    except (ValidationError, ValueError, json.JSONDecodeError) as exc:
                        validation_error = exc
                if validation_error is not None:
                    raise validation_error
                raise ValueError("Provider did not return a JSON object.")
            except Exception as exc:
                last_error = exc
                # Changing output format cannot repair credentials or a missing model.
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code in {401, 402, 403, 404}:
                    break
                if isinstance(exc, LLMOutputTruncatedError):
                    current_limit = int(request_metadata.get("max_tokens") or 2048)
                    if current_limit < 8192:
                        request_metadata["max_tokens"] = min(8192, current_limit * 2)
                    user_prompt = base_user_prompt + (
                        "\n\nThe previous response reached the output length limit. Return a complete JSON object. "
                        "Keep field names and required facts; avoid repeating the same text in multiple fields."
                    )
                    logger.warning("Structured output retry: agent=%s reason=output_truncated max_tokens=%s", agent_name, current_limit)
                    continue
                if isinstance(exc, (ValidationError, ValueError)):
                    feedback = self._validation_feedback(exc, response_model)
                    user_prompt = base_user_prompt + (
                        "\n\nCorrect the previous output's structure using this feedback: " + feedback
                        + "\nReturn one complete JSON object matching the target schema. Fix field types and required fields; "
                        "do not add facts. Use empty values only where the schema allows them."
                    )
                    logger.warning("Structured output retry: agent=%s reason=invalid_output issues=%s", agent_name, feedback)
                if response_format == "json_schema":
                    response_format = "json_object"

        raise StructuredLLMError("Structured output failed for agent '{0}': {1}".format(agent_name, last_error),
                                 agent_name=agent_name) from last_error

    def _validation_feedback(self, exc: Exception, response_model: Type[BaseModel]) -> str:
        if not isinstance(exc, ValidationError):
            return "The response was empty or was not a complete JSON object."
        # Error input and free-form messages can contain resume text. Only include
        # paths from the public schema and allowlisted validation categories.
        field_names = set()

        def collect_fields(schema):
            if isinstance(schema, dict):
                field_names.update(schema.get("properties", {}))
                for value in schema.values():
                    collect_fields(value)
            elif isinstance(schema, list):
                for value in schema:
                    collect_fields(value)

        collect_fields(response_model.model_json_schema())
        categories = {"missing", "string_type", "list_type", "dict_type", "model_type", "model_attributes_type",
                      "literal_error", "enum", "int_type", "int_parsing", "float_type", "float_parsing",
                      "bool_type", "bool_parsing", "value_error", "extra_forbidden", "greater_than", "less_than",
                      "string_too_long", "string_too_short"}
        issues = []
        for error in exc.errors(include_url=False, include_input=False, include_context=False)[:6]:
            path = [part if isinstance(part, int) or part in field_names else "<field>" for part in error["loc"]]
            category = error["type"] if error["type"] in categories else "validation_error"
            issues.append({"field": path, "type": category})
        return json.dumps(issues, ensure_ascii=False)

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
        candidates = self._extract_json_candidates(text)
        if not candidates:
            raise ValueError("Provider did not return a JSON object.")
        return candidates[0]

    def _extract_json_candidates(self, text: str) -> List[str]:
        stripped = text.strip()
        variants = [stripped]
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if len(lines) >= 3:
                variants.append("\n".join(lines[1:-1]).strip())

        candidates: List[str] = []
        seen = set()
        for variant in variants:
            fragment = self._extract_balanced_json_fragment(variant)
            if fragment and fragment not in seen:
                seen.add(fragment)
                candidates.append(fragment)

            repaired = self._repair_partial_json_fragment(variant)
            if repaired and repaired not in seen:
                seen.add(repaired)
                candidates.append(repaired)

        if not candidates:
            raise ValueError("Provider did not return a JSON object.")
        return candidates

    def _extract_balanced_json_fragment(self, text: str) -> Optional[str]:
        start = text.find("{")
        if start == -1:
            return None
        stack: List[str] = []
        in_string = False
        escape = False
        for index in range(start, len(text)):
            char = text[index]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue
            if char in "{[":
                stack.append(char)
                continue
            if char in "}]":
                if not stack:
                    break
                opener = stack[-1]
                if (opener == "{" and char == "}") or (opener == "[" and char == "]"):
                    stack.pop()
                    if not stack:
                        return text[start : index + 1].strip()
                else:
                    break
        return None

    def _repair_partial_json_fragment(self, text: str) -> Optional[str]:
        start = text.find("{")
        if start == -1:
            return None
        fragment = text[start:].strip()
        if not fragment:
            return None

        stack: List[str] = []
        in_string = False
        escape = False
        for char in fragment:
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == '"':
                    in_string = False
                continue

            if char == '"':
                in_string = True
                continue
            if char in "{[":
                stack.append(char)
            elif char in "}]":
                if not stack:
                    break
                opener = stack[-1]
                if (opener == "{" and char == "}") or (opener == "[" and char == "]"):
                    stack.pop()
                else:
                    break

        if not stack and fragment.endswith("}"):
            return None

        repaired = fragment.rstrip()
        repaired = repaired.rstrip(",")
        closing = "".join("}" if opener == "{" else "]" for opener in reversed(stack))
        repaired = repaired + closing
        repaired = re.sub(r",(\s*[}\]])", r"\1", repaired)
        return repaired.strip()


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
