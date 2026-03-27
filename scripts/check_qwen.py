import json
import sys

from backend.app.core.config import get_settings
from backend.app.services.llm.provider import get_llm_provider


def main() -> int:
    settings = get_settings()
    provider = get_llm_provider()

    print("provider:", provider.name)
    print("configured_llm_provider:", settings.llm_provider)
    print("qwen_model:", settings.qwen_model)
    print("qwen_base_url:", settings.qwen_base_url)

    if not provider.is_available:
        print("provider_status: stub_fallback")
        print("hint: set LLM_PROVIDER=qwen and provide QWEN_API_KEY or DASHSCOPE_API_KEY")
        return 1

    try:
        result = provider.complete(
            system_prompt=(
                "Return valid JSON only. Keep the answer extremely short. "
                "Do not include markdown fences."
            ),
            user_prompt=(
                "Return a JSON object with one field named status and value ok."
            ),
            metadata={"expect_json": True, "response_format": settings.llm_response_format},
        )
    except Exception as exc:
        print("provider_status: request_failed")
        print("error:", str(exc))
        return 2

    print("provider_status: request_succeeded")
    print("raw_response:", result)

    try:
        parsed = json.loads(result)
    except json.JSONDecodeError:
        print("json_check: failed")
        return 3

    print("json_check: passed")
    print("parsed:", parsed)
    return 0


if __name__ == "__main__":
    sys.exit(main())

