import pytest

from backend.app.core.config import reset_settings_cache
from backend.app.services.llm.provider import reset_llm_provider_cache
from backend.app.services.llm.structured import reset_structured_llm_service_cache
from backend.app.services.prompt_loader import reset_prompt_loader_cache
from backend.app.services.runs.store import reset_run_store_cache
from backend.app.services.runs.queue import reset_task_queue_cache
from backend.app.services.profiles import reset_candidate_archive_store_cache
from backend.app.services.applications import get_application_store


@pytest.fixture(autouse=True)
def reset_runtime_caches(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_STRICT_MODE", "false")
    monkeypatch.setenv("RUN_STORE_PATH", str(tmp_path / "run_store.json"))
    monkeypatch.setenv("TASK_QUEUE_PATH", str(tmp_path / "task_queue.sqlite3"))
    monkeypatch.setenv("CANDIDATE_ARCHIVE_PATH", str(tmp_path / "candidate_archives.sqlite3"))
    monkeypatch.setenv("APPLICATION_STORE_PATH", str(tmp_path / "applications.sqlite3"))
    monkeypatch.setenv("QWEN_API_KEY", "")
    monkeypatch.setenv("DASHSCOPE_API_KEY", "")
    monkeypatch.setenv("LLM_API_KEY", "")
    monkeypatch.setenv("DEEPSEEK_API_KEY", "")
    reset_settings_cache()
    reset_llm_provider_cache()
    reset_structured_llm_service_cache()
    reset_prompt_loader_cache()
    reset_run_store_cache()
    reset_task_queue_cache()
    reset_candidate_archive_store_cache()
    get_application_store.cache_clear()
    yield
    reset_settings_cache()
    reset_llm_provider_cache()
    reset_structured_llm_service_cache()
    reset_prompt_loader_cache()
    reset_run_store_cache()
    reset_task_queue_cache()
    reset_candidate_archive_store_cache()
    get_application_store.cache_clear()
