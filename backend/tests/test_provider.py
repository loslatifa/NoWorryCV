from backend.app.core.config import get_settings
from backend.app.services.llm.provider import get_llm_provider


def test_provider_falls_back_to_stub_when_credentials_missing(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "openai_compatible")
    monkeypatch.delenv("LLM_API_KEY", raising=False)
    monkeypatch.delenv("LLM_MODEL", raising=False)

    settings = get_settings()
    provider = get_llm_provider()

    assert settings.llm_provider == "openai_compatible"
    assert provider.name == "stub"
    assert provider.is_available is False


def test_qwen_provider_uses_qwen_env_vars(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.setenv("QWEN_API_KEY", "test-qwen-key")
    monkeypatch.setenv("QWEN_MODEL", "qwen-plus")
    monkeypatch.setenv("QWEN_BASE_URL", "https://dashscope-intl.aliyuncs.com/compatible-mode/v1")

    settings = get_settings()
    provider = get_llm_provider()

    assert settings.llm_provider == "qwen"
    assert provider.name == "openai_compatible"
    assert provider.is_available is True


def test_qwen_provider_accepts_official_dashscope_api_key_env(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "qwen")
    monkeypatch.delenv("QWEN_API_KEY", raising=False)
    monkeypatch.setenv("DASHSCOPE_API_KEY", "test-dashscope-key")
    monkeypatch.setenv("QWEN_MODEL", "qwen-plus")

    settings = get_settings()
    provider = get_llm_provider()

    assert settings.qwen_api_key == "test-dashscope-key"
    assert provider.name == "openai_compatible"
    assert provider.is_available is True
