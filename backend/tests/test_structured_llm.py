import json

from pydantic import BaseModel, Field

from backend.app.services.llm.structured import StructuredLLMService
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
