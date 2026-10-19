import httpx
import pytest

from backend.app.core.config import Settings, get_settings
from backend.app.services.llm import provider as provider_module
from backend.app.services.llm.provider import LLMOutputTruncatedError, OpenAICompatibleProvider, build_llm_provider, get_llm_provider


def test_provider_rejects_explicitly_truncated_output_even_when_json_prefix_is_valid():
    provider = OpenAICompatibleProvider("fake-key", "fake-model", "https://example.invalid")
    partial = {"choices": [{"finish_reason": "length", "message": {"content": '{"projects":[]}'}}]}
    with pytest.raises(LLMOutputTruncatedError):
        provider._extract_content(partial)


def test_official_deepseek_uses_its_dedicated_key_without_reusing_qwen_credentials():
    settings=Settings(_env_file=None,llm_provider="openai_compatible",llm_base_url="https://api.deepseek.com",
        llm_model="deepseek-flash",deepseek_api_key="fake-deepseek-key",qwen_api_key="fake-qwen-key")
    provider=build_llm_provider(settings)
    assert provider.is_available and provider.api_key=="fake-deepseek-key"
    assert provider.base_url=="https://api.deepseek.com" and provider.model=="deepseek-flash"
    assert not build_llm_provider(settings.model_copy(update={"deepseek_api_key":""})).is_available
    explicit=build_llm_provider(settings.model_copy(update={"llm_api_key":"fake-explicit-key"}))
    assert explicit.api_key=="fake-explicit-key"


@pytest.mark.parametrize("base_url",["https://api.openai.com/v1","https://api.deepseek.com.example/v1","https://dashscope.aliyuncs.com/compatible-mode/v1"])
def test_deepseek_key_is_not_sent_to_other_services(base_url):
    settings=Settings(_env_file=None,llm_provider="openai_compatible",llm_base_url=base_url,
        llm_model="deepseek-flash",deepseek_api_key="fake-deepseek-key",llm_api_key="")
    assert not build_llm_provider(settings).is_available


@pytest.mark.parametrize("metadata,expected",[({},"disabled"),({"enable_thinking":True},"enabled"),({"enable_thinking":False},"disabled")])
def test_deepseek_official_requests_use_native_thinking_parameter_and_json_output(monkeypatch,metadata,expected):
    captured={}
    class Response:
        def raise_for_status(self):pass
        def json(self):return {"choices":[{"message":{"content":'{"status":"ok"}'}}]}
    class Client:
        def __init__(self,**kwargs):pass
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def post(self,url,headers=None,json=None):
            captured.update(url=url,payload=json,headers=headers)
            return Response()
    monkeypatch.setattr(provider_module.httpx,"Client",Client)
    provider=OpenAICompatibleProvider("fake-deepseek-key","deepseek-flash","https://api.deepseek.com/")
    assert provider.complete("Return JSON.","{}",metadata={"expect_json":True,"response_format":"json_object",**metadata})=='{"status":"ok"}'
    assert captured["url"]=="https://api.deepseek.com/chat/completions"
    assert captured["payload"]["thinking"]=={"type":expected}
    assert "enable_thinking" not in captured["payload"]
    assert captured["payload"]["response_format"]=={"type":"json_object"}


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
