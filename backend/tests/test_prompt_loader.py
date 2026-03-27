from backend.app.services.prompt_loader import PromptLoader


def test_prompt_loader_loads_prompt_by_alias() -> None:
    loader = PromptLoader(default_version="v1")

    prompt = loader.load("resume_rewrite")

    assert "Resume Rewrite Agent" in prompt

