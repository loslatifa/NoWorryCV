from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "NoWorryCV API"
    app_version: str = "0.1.0"
    api_prefix: str = "/api/v1"
    default_provider: str = "stub"
    prompt_version: str = "v1"
    llm_provider: str = "stub"
    llm_model: str = ""
    llm_api_key: str = ""
    llm_base_url: str = "https://api.openai.com/v1"
    llm_timeout_seconds: float = 45.0
    llm_max_retries: int = 2
    llm_response_format: str = "json_schema"
    llm_strict_mode: bool = True
    qwen_api_key: str = Field(
        default="",
        validation_alias=AliasChoices("QWEN_API_KEY", "DASHSCOPE_API_KEY"),
    )
    qwen_model: str = Field(
        default="qwen-plus",
        validation_alias=AliasChoices("QWEN_MODEL", "DASHSCOPE_MODEL"),
    )
    qwen_base_url: str = Field(
        default="https://dashscope-intl.aliyuncs.com/compatible-mode/v1",
        validation_alias=AliasChoices("QWEN_BASE_URL", "DASHSCOPE_BASE_URL"),
    )

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
