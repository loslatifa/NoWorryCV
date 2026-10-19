import json

from pydantic import BaseModel, Field, ValidationError

from backend.app.services.llm.structured import StructuredLLMService
from backend.app.services.llm.provider import LLMOutputTruncatedError
from backend.app.services.prompt_loader import PromptLoader


class _CardItem(BaseModel):
    title: str = ""


class _CardDeck(BaseModel):
    review_cards: list[_CardItem] = Field(default_factory=list)


class _FakeProvider:
    name = "fake"

    def __init__(self, response: str) -> None:
        self.response = response

    @property
    def is_available(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str, metadata=None) -> str:
        del system_prompt, user_prompt, metadata
        return self.response


def test_structured_llm_extracts_json_from_fenced_output_with_commentary() -> None:
    response = """这里是结果：

```json
{
  "review_cards": [
    {"title": "SQL 与数据口径"}
  ]
}
```
"""
    service = StructuredLLMService(
        provider=_FakeProvider(response),
        prompt_loader=PromptLoader(default_version="v1"),
        max_retries=1,
    )

    result = service.generate("jd_review_card", {"jd_text": "SQL"}, _CardDeck)

    assert result.review_cards[0].title == "SQL 与数据口径"


def test_structured_llm_repairs_truncated_json_object() -> None:
    response = """{
  "review_cards": [
    {"title": "SQL 与数据口径"},
    {"title": "A/B Testing 与实验设计"}
  ]
"""
    service = StructuredLLMService(
        provider=_FakeProvider(response),
        prompt_loader=PromptLoader(default_version="v1"),
        max_retries=1,
    )

    result = service.generate("jd_review_card", {"jd_text": "SQL"}, _CardDeck)

    assert len(result.review_cards) == 2
    assert result.review_cards[1].title == "A/B Testing 与实验设计"


def test_structured_llm_extract_json_returns_first_repair_candidate() -> None:
    response = '{"review_cards":[{"title":"SQL 与数据口径"}]'
    service = StructuredLLMService(
        provider=_FakeProvider(response),
        prompt_loader=PromptLoader(default_version="v1"),
        max_retries=1,
    )

    payload = service._extract_json(response)

    assert json.loads(payload)["review_cards"][0]["title"] == "SQL 与数据口径"


def test_length_retry_increases_budget_with_a_cap_without_switching_json_format():
    class Provider:
        is_available = True
        metadata = []

        def complete(self, system_prompt, user_prompt, metadata):
            self.metadata.append(metadata.copy())
            if len(self.metadata) < 3:
                raise LLMOutputTruncatedError("truncated")
            return '{"review_cards":[{"title":"SQL"},{"title":"Python"}]}'

    provider = Provider()
    service = StructuredLLMService(provider, PromptLoader(), max_retries=3, response_format="json_schema")
    result = service.generate("jd_review_card", {"jd_text": "SQL"}, _CardDeck, metadata={"max_tokens": 4096})
    assert len(result.review_cards) == 2
    assert [item["max_tokens"] for item in provider.metadata] == [4096, 8192, 8192]
    assert all(item["response_format"] == "json_schema" for item in provider.metadata)


def test_validation_retry_explains_schema_fields_without_echoing_failed_input(caplog):
    class Provider:
        is_available = True
        prompts = []

        def complete(self, system_prompt, user_prompt, metadata):
            self.prompts.append(user_prompt)
            if len(self.prompts) == 1:
                return '{"review_cards":[{"title":{"private-secret":"private-resume"}}]}'
            assert "review_cards" in user_prompt and "title" in user_prompt and "string_type" in user_prompt
            assert "private-secret" not in user_prompt and "private-resume" not in user_prompt
            return '{"review_cards":[{"title":"SQL"}]}'

    provider = Provider()
    service = StructuredLLMService(provider, PromptLoader(), max_retries=2)
    assert service.generate("jd_review_card", {"jd_text": "SQL"}, _CardDeck).review_cards[0].title == "SQL"
    assert len(provider.prompts) == 2
    assert "private-secret" not in caplog.text and "private-resume" not in caplog.text


def test_empty_output_retry_requests_a_complete_json_object():
    class Provider:
        is_available = True
        calls = 0

        def complete(self, system_prompt, user_prompt, metadata):
            self.calls += 1
            if self.calls == 1:
                return ""
            assert "empty or was not a complete JSON object" in user_prompt
            return '{"review_cards":[{"title":"SQL"}]}'

    provider = Provider()
    result = StructuredLLMService(provider, PromptLoader(), max_retries=2).generate("jd_review_card", {}, _CardDeck)
    assert result.review_cards[0].title == "SQL" and provider.calls == 2


def test_validation_feedback_does_not_log_free_form_dictionary_keys():
    class DictionaryOutput(BaseModel):
        review_cards: dict[str, int]

    try:
        DictionaryOutput.model_validate({"review_cards": {"private-email@example.invalid": "private-secret"}})
    except ValidationError as error:
        service = StructuredLLMService(_FakeProvider(""), PromptLoader())
        feedback = service._validation_feedback(error, DictionaryOutput)
    assert "review_cards" in feedback and "int_parsing" in feedback
    assert "private-email" not in feedback and "private-secret" not in feedback
