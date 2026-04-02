import httpx

from backend.app.core.config import get_settings
from backend.app.services.llm import provider as provider_module
from backend.app.services.llm.provider import OpenAICompatibleProvider, get_llm_provider


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


def test_openai_compatible_provider_retries_connect_errors(monkeypatch) -> None:
    attempts = {"count": 0}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"status":"ok"}'}}]}

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            del url, headers, json
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise httpx.ConnectError("temporary dns failure")
            return FakeResponse()

    monkeypatch.setattr(provider_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(provider_module.time, "sleep", lambda _: None)

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        model="qwen-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    result = provider.complete("Return JSON.", '{"status":"ok"}', metadata={"expect_json": True})

    assert result == '{"status":"ok"}'
    assert attempts["count"] == 3


def test_openai_compatible_provider_surfaces_dns_message_after_retries(monkeypatch) -> None:
    class FakeClient:
        def __init__(self, timeout=None) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            del url, headers, json
            raise httpx.ConnectError("[Errno 8] nodename nor servname provided, or not known")

    monkeypatch.setattr(provider_module.httpx, "Client", FakeClient)
    monkeypatch.setattr(provider_module.time, "sleep", lambda _: None)

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        model="qwen-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    try:
        provider.complete("Return JSON.", '{"status":"ok"}', metadata={"expect_json": True, "connect_retries": 2})
    except RuntimeError as exc:
        message = str(exc)
    else:  # pragma: no cover
        raise AssertionError("Expected provider.complete to raise RuntimeError")

    assert "dashscope.aliyuncs.com" in message
    assert "DNS resolution" in message


def test_qwen3_provider_sets_enable_thinking_false_for_non_streaming_calls(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"status":"ok"}'}}]}

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            del url, headers
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(provider_module.httpx, "Client", FakeClient)

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        model="qwen3-32b",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    result = provider.complete("Return JSON.", '{"status":"ok"}', metadata={"expect_json": True})

    assert result == '{"status":"ok"}'
    assert captured["payload"]["enable_thinking"] is False


def test_non_qwen3_provider_does_not_set_enable_thinking_by_default(monkeypatch) -> None:
    captured = {}

    class FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"status":"ok"}'}}]}

    class FakeClient:
        def __init__(self, timeout=None) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def post(self, url, headers=None, json=None):
            del url, headers
            captured["payload"] = json
            return FakeResponse()

    monkeypatch.setattr(provider_module.httpx, "Client", FakeClient)

    provider = OpenAICompatibleProvider(
        api_key="test-key",
        model="qwen-plus",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    provider.complete("Return JSON.", '{"status":"ok"}', metadata={"expect_json": True})

    assert "enable_thinking" not in captured["payload"]
