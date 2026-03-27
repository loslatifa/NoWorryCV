from functools import lru_cache
from pathlib import Path

from backend.app.core.config import get_settings


PROMPT_ALIASES = {
    "resume_rewrite": "rewrite",
}


class PromptLoader:
    def __init__(self, base_dir: Path = None, default_version: str = "v1") -> None:
        repo_root = Path(__file__).resolve().parents[3]
        self.base_dir = base_dir or (repo_root / "prompts")
        self.default_version = default_version

    def load(self, agent_name: str, version: str = None) -> str:
        prompt_name = PROMPT_ALIASES.get(agent_name, agent_name)
        prompt_version = version or self.default_version
        prompt_path = self.base_dir / prompt_version / "{0}.md".format(prompt_name)
        if not prompt_path.exists():
            raise FileNotFoundError("Prompt not found for agent '{0}' at {1}".format(agent_name, prompt_path))
        return prompt_path.read_text(encoding="utf-8").strip()


@lru_cache
def get_prompt_loader() -> PromptLoader:
    settings = get_settings()
    return PromptLoader(default_version=settings.prompt_version)


def reset_prompt_loader_cache() -> None:
    get_prompt_loader.cache_clear()

