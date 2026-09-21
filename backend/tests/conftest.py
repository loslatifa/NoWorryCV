import pytest

from backend.app.core.config import reset_settings_cache
from backend.app.services.llm.provider import reset_llm_provider_cache
from backend.app.services.llm.structured import reset_structured_llm_service_cache
from backend.app.services.prompt_loader import reset_prompt_loader_cache
from backend.app.services.runs.store import reset_run_store_cache


@pytest.fixture(autouse=True)
def reset_runtime_caches(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_STRICT_MODE", "false")
    monkeypatch.setenv("RUN_STORE_PATH", str(tmp_path / "run_store.json"))
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.delenv("DASHSCOPE_API_KEY", raising=False)
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    reset_settings_cache()
    reset_llm_provider_cache()
    reset_structured_llm_service_cache()
    reset_prompt_loader_cache()
    reset_run_store_cache()
    yield
    reset_settings_cache()
    reset_llm_provider_cache()
    reset_structured_llm_service_cache()
    reset_prompt_loader_cache()
    reset_run_store_cache()
