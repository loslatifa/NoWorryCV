import json

from backend.app.agents.resume_parser import ResumeParserAgent
from backend.app.agents.strategy import StrategyAgent
from backend.app.schemas.candidate import CandidateBasics, CandidateProfile, EducationEntry, ProjectExperience, SkillSet
from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.strategy import GapAnalysis
from backend.app.agents.jd_analyst import JDAnalystAgent
from backend.app.services.llm.structured import StructuredLLMService
from backend.app.services.prompt_loader import PromptLoader


class FakeProvider:
    name = "fake"

    @property
    def is_available(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str, metadata=None) -> str:
        del system_prompt, user_prompt, metadata
        return json.dumps(
            {
                "job_title": "高级产品经理",
                "department": "product",
                "seniority": "senior",
                "hiring_track": "experienced",
                "responsibilities": ["负责增长策略", "负责数据分析"],
                "must_have_skills": ["SQL", "A/B Testing"],
                "nice_to_have_skills": ["用户研究"],
                "keywords": ["增长", "SQL", "A/B Testing"],
                "domain_signals": ["growth"],
                "language": "zh",
            },
            ensure_ascii=False,
        )


def test_jd_analyst_agent_accepts_structured_llm_output() -> None:
    llm_service = StructuredLLMService(
        provider=FakeProvider(),
        prompt_loader=PromptLoader(default_version="v1"),
        max_retries=1,
    )
    agent = JDAnalystAgent(llm_service=llm_service)

    profile = agent.run(
        "高级产品经理\n职责：负责增长策略、数据分析。\n要求：熟悉 SQL、A/B Testing。\n加分项：用户研究。"
    )

    assert profile.job_title == "高级产品经理"
    assert "SQL" in profile.must_have_skills
    assert profile.language == "zh"
    assert profile.hiring_track == "experienced"


def test_jd_analyst_fallback_detects_campus_track() -> None:
    agent = JDAnalystAgent()
    profile = agent.run("2026 校招产品经理\n面向应届毕业生\n要求：熟悉 SQL、用户研究。", force_fallback=True)

    assert profile.hiring_track == "campus"
    assert profile.job_title == "产品经理"
    assert "职责" not in profile.keywords
    assert "2026" not in profile.keywords
    assert "SQL" in profile.must_have_skills
    assert profile.review_cards


def test_resume_parser_fallback_skips_markdown_title_and_keeps_compound_skill() -> None:
    agent = ResumeParserAgent()
    profile, _ = agent.run(
        "# Resume\n\n张三\n\n教育背景\n某大学 | 本科 | 计算机科学\n\n技能\nSQL, A/B Testing, Tableau",
        force_fallback=True,
    )

    assert profile.basics.name == "张三"
    assert "A/B Testing" in profile.skills.hard_skills
    assert "Tableau" in profile.skills.tools


def test_strategy_fallback_prioritizes_education_for_campus_roles() -> None:
    agent = StrategyAgent()
    candidate = CandidateProfile(
        basics=CandidateBasics(name="李四", language="zh"),
        education=[EducationEntry(id="edu_1", school="某大学", degree="本科", field_of_study="信息管理")],
        projects=[ProjectExperience(id="proj_1", name="校园增长项目", bullets=["负责拉新活动分析"], skills_used=["SQL"])],
        skills=SkillSet(hard_skills=["SQL"]),
    )
    fact_cards = [
        FactCard(id="fact_1", category="project_bullet", text="负责拉新活动分析", source_span="projects.proj_1.bullets.1"),
        FactCard(id="fact_2", category="skill", text="SQL", source_span="skills"),
    ]
    gap_analysis = GapAnalysis(
        fit_score_initial=62,
        strengths=["SQL"],
        missing_keywords=["A/B Testing"],
        recommended_focus=["SQL", "校园增长项目"],
    )
    jd_profile = JDProfile(job_title="产品经理校招", hiring_track="campus", language="zh")

    strategy = agent.run(candidate, gap_analysis, fact_cards, jd_profile, "zh", force_fallback=True)

    assert strategy.section_priority[:2] == ["summary", "education"]
    assert strategy.include_projects is True
    assert strategy.summary_style == "potential_and_evidence"
