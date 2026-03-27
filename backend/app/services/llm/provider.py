from functools import lru_cache
from typing import Any, Dict, Optional, Protocol

import httpx

from backend.app.core.config import Settings, get_settings


class LLMProvider(Protocol):
    name: str

    @property
    def is_available(self) -> bool:
        ...

    def complete(self, system_prompt: str, user_prompt: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        ...


class StubLLMProvider:
    name = "stub"

    def __init__(self, reason: str = "stub provider configured") -> None:
        self.reason = reason

    @property
    def is_available(self) -> bool:
        return False

    def complete(self, system_prompt: str, user_prompt: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        del system_prompt, user_prompt, metadata
        raise RuntimeError(self.reason)


class OpenAICompatibleProvider:
    name = "openai_compatible"

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: str,
        timeout_seconds: float = 45.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    @property
    def is_available(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str, metadata: Optional[Dict[str, Any]] = None) -> str:
        metadata = metadata or {}
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": metadata.get("temperature", 0),
        }

        if metadata.get("expect_json"):
            response_format = metadata.get("response_format", "json_object")
            if response_format == "json_schema" and metadata.get("json_schema"):
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": metadata.get("schema_name", "structured_output"),
                        "strict": True,
                        "schema": metadata["json_schema"],
                    },
                }
            else:
                payload["response_format"] = {"type": "json_object"}

        headers = {
            "Authorization": "Bearer {0}".format(self.api_key),
            "Content-Type": "application/json",
        }

        with httpx.Client(timeout=self.timeout_seconds) as client:
            response = client.post(
                "{0}/chat/completions".format(self.base_url),
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        return self._extract_content(data)

    def _extract_content(self, payload: Dict[str, Any]) -> str:
        choices = payload.get("choices") or []
        if not choices:
            raise RuntimeError("No choices returned from provider.")
        message = choices[0].get("message") or {}
        content = message.get("content", "")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    parts.append(item.get("text", ""))
            return "".join(parts)
        raise RuntimeError("Unsupported provider response content format.")


def build_llm_provider(settings: Optional[Settings] = None) -> LLMProvider:
    settings = settings or get_settings()
    provider_name = (settings.llm_provider or settings.default_provider or "stub").strip().lower()
    if provider_name in {"", "stub", "none"}:
        return StubLLMProvider(reason="LLM provider set to stub.")
    if provider_name in {"qwen", "dashscope"}:
        api_key = settings.qwen_api_key or settings.llm_api_key
        model = settings.qwen_model or settings.llm_model
        base_url = settings.qwen_base_url or settings.llm_base_url
        if not api_key or not model:
            return StubLLMProvider(reason="Missing Qwen credentials or model; falling back to stub.")
        return OpenAICompatibleProvider(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    if provider_name in {"openai", "openai_compatible"}:
        if not settings.llm_api_key or not settings.llm_model:
            return StubLLMProvider(reason="Missing LLM credentials or model; falling back to stub.")
        return OpenAICompatibleProvider(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
            base_url=settings.llm_base_url,
            timeout_seconds=settings.llm_timeout_seconds,
        )
    return StubLLMProvider(reason="Unsupported provider '{0}'; falling back to stub.".format(provider_name))


@lru_cache
def get_llm_provider() -> LLMProvider:
    return build_llm_provider()


def reset_llm_provider_cache() -> None:
    get_llm_provider.cache_clear()
