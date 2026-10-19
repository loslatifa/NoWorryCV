import json

import httpx
import pytest

from backend.app.services.llm.diagnostics import safe_failure
from backend.app.services.llm.structured import StructuredLLMError, StructuredLLMService
from backend.app.services.prompt_loader import PromptLoader
from backend.tests.test_structured_llm import _CardDeck


def http_error(status, code=None):
    request = httpx.Request("POST", "https://private.example/v1?key=fake-secret")
    response = httpx.Response(status, request=request, json={"error":{"code":code,"message":"private-candidate@example.com fake-secret"}})
    return httpx.HTTPStatusError("private provider message",request=request,response=response)


@pytest.mark.parametrize("status,provider_code,expected", [
    (404,"model_not_found","model_not_found"), (404,None,"endpoint_not_found"),
    (401,None,"authentication_failed"), (403,None,"access_denied"),
    (402,None,"quota_exceeded"), (429,"insufficient_quota","quota_exceeded"),
    (429,None,"rate_limited"), (504,None,"timeout"), (500,None,"provider_error"),
    (400,None,"invalid_request"), (404,{"untrusted":"object"},"endpoint_not_found"),
])
def test_http_failure_diagnostics_are_allowlisted_and_do_not_include_provider_text(status, provider_code, expected):
    wrapped = StructuredLLMError("private prompt",agent_name="jd_analyst")
    wrapped.__cause__ = http_error(status,provider_code)
    failure = safe_failure(wrapped)
    assert failure["code"] == expected and failure["stage"] == "jd_analyst"
    assert failure["http_status"] == status
    assert not any(secret in json.dumps(failure) for secret in ("private", "fake-secret", "example.com"))


@pytest.mark.parametrize("error,expected", [(httpx.ReadTimeout("private"),"timeout"),
    (httpx.ConnectError("private"),"connection_error"), (ValueError("private JSON"),"invalid_output"),
    (RuntimeError("private"),"generation_failed")])
def test_other_errors_have_safe_categories(error, expected):
    wrapper=StructuredLLMError("private",agent_name="private-injected-stage")
    wrapper.__cause__=error
    assert safe_failure(wrapper)["code"] == expected
    assert safe_failure(wrapper)["stage"] == "unknown"
    assert "private" not in json.dumps(safe_failure(wrapper))


@pytest.mark.parametrize("status", [401,402,403,404])
def test_nonretryable_http_failures_preserve_cause_and_stop_retries(status):
    class Provider:
        is_available=True
        calls=0
        def complete(self, **kwargs):
            self.calls += 1
            raise http_error(status, "model_not_found" if status==404 else None)
    provider=Provider()
    service=StructuredLLMService(provider,PromptLoader(),max_retries=3,response_format="json_schema")
    with pytest.raises(StructuredLLMError) as raised:
        service.generate("jd_analyst",{},_CardDeck)
    assert provider.calls == 1
    assert isinstance(raised.value.__cause__,httpx.HTTPStatusError)
    assert safe_failure(raised.value)["stage"] == "jd_analyst"


def test_unsupported_response_format_still_retries_with_json_object():
    class Provider:
        is_available=True
        formats=[]
        def complete(self, **kwargs):
            self.formats.append(kwargs["metadata"]["response_format"])
            if len(self.formats)==1: raise http_error(400)
            return '{"review_cards":[{"title":"SQL"}]}'
    provider=Provider()
    service=StructuredLLMService(provider,PromptLoader(),max_retries=2,response_format="json_schema")
    assert service.generate("jd_analyst",{},_CardDeck).review_cards[0].title == "SQL"
    assert provider.formats == ["json_schema","json_object"]
