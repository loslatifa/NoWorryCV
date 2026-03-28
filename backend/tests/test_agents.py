import json

from backend.app.agents.resume_parser import ResumeParserAgent
from backend.app.agents.rewrite import ResumeRewriteAgent
from backend.app.agents.strategy import StrategyAgent
from backend.app.agents.compliance import TruthfulnessComplianceAgent
from backend.app.agents.critic import CriticAgent
from backend.app.agents.jd_review_card import JDReviewCardAgent
from backend.app.agents.jd_review_doc import JDReviewDocAgent
from backend.app.agents.interview_prep import InterviewPrepAgent
from backend.app.schemas.candidate import CandidateBasics, CandidateProfile, EducationEntry, ProjectExperience, SkillSet
from backend.app.schemas.common import FactCard, TraceabilityRecord
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.review import ATSReport, ComplianceReport, CriticReport, ReviewBundle
from backend.app.schemas.strategy import GapAnalysis, ResumeDraft, ResumeSectionItem, RewriteStrategy
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


class PartialRewriteProvider:
    name = "fake"

    @property
    def is_available(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str, metadata=None) -> str:
        del system_prompt, user_prompt, metadata
        return json.dumps(
            {
                "headline": "张三 | 面向 增长产品经理 的定制简历",
                "summary": "具备 SQL、A/B Testing 和增长分析相关经验，曾推动转化率提升。",
                "skills_section": ["SQL", "A/B Testing"],
                "experience_section": [
                    {
                        "heading": "产品经理",
                        "subheading": "A公司",
                        "bullets": [
                            {
                                "text": "推动 A/B 测试与漏斗优化，提升转化率 12%",
                                "fact_ids": ["fact_1"],
                            }
                        ],
                    }
                ],
                "project_section": [],
                "education_section": [],
            },
            ensure_ascii=False,
        )


class JDTailRewriteProvider:
    name = "fake"

    @property
    def is_available(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str, metadata=None) -> str:
        del system_prompt, user_prompt, metadata
        return json.dumps(
            {
                "headline": "张三 | 面向 增长产品经理 的定制简历",
                "summary": "具备 SQL、A/B Testing 和增长分析相关经验，曾推动转化率提升。",
                "skills_section": ["SQL", "A/B Testing"],
                "experience_section": [
                    {
                        "heading": "产品经理",
                        "subheading": "A公司",
                        "bullets": [
                            {
                                "text": "推动 A/B 测试与漏斗优化，提升转化率 12% - 对应 JD 的数据分析要求",
                                "fact_ids": ["fact_1"],
                            }
                        ],
                    }
                ],
                "project_section": [
                    {
                        "heading": "增长实验项目",
                        "subheading": "项目负责人",
                        "bullets": [
                            {
                                "text": "使用 SQL 复盘实验结果（符合岗位要求）",
                                "fact_ids": ["fact_5"],
                            }
                        ],
                    }
                ],
                "education_section": ["某大学 | 本科 | 信息管理"],
            },
            ensure_ascii=False,
        )


class FakeReviewCardProvider:
    name = "fake"

    @property
    def is_available(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str, metadata=None) -> str:
        del system_prompt, user_prompt, metadata
        return json.dumps(
            {
                "review_cards": [
                    {
                        "id": "review_1",
                        "title": "SQL 与增长漏斗分析",
                        "focus_area": "硬技能",
                        "why_it_matters": "JD 强调 SQL 和增长分析，说明岗位希望你能用数据支撑产品判断。",
                        "review_tip": "准备一个用 SQL 分析漏斗并推动动作的案例。",
                        "sample_question": "如果让你分析注册到付费的漏斗掉点，你会怎么拆？",
                        "keywords": ["SQL", "增长漏斗"],
                    },
                    {
                        "id": "review_2",
                        "title": "A/B 测试与实验复盘",
                        "focus_area": "方法论",
                        "why_it_matters": "JD 提到实验设计，说明岗位会看你是否能从假设到复盘完整闭环。",
                        "review_tip": "准备实验假设、指标和结论解释的真实经历。",
                        "sample_question": "你如何判断一次实验结果是否可信？",
                        "keywords": ["A/B Testing", "实验设计"],
                    },
                ]
            },
            ensure_ascii=False,
        )


class FakeJDReviewDocProvider:
    name = "fake"

    @property
    def is_available(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str, metadata=None) -> str:
        del system_prompt, user_prompt, metadata
        return json.dumps(
            {
                "title": "增长产品经理 JD 复习文档",
                "role_summary": "这个岗位重点看 SQL、增长分析和实验设计。",
                "hiring_track_hint": "这是社招岗位，面试会重点追问职责范围和结果。",
                "core_requirements": ["SQL", "增长分析", "A/B Testing"],
                "key_topics": [
                    {
                        "id": "review_1",
                        "title": "SQL 与增长漏斗分析",
                        "focus_area": "硬技能",
                        "why_it_matters": "岗位希望你能用数据支撑判断。",
                        "review_tip": "准备一个 SQL 分析漏斗的案例。",
                        "sample_question": "如果让你分析注册到付费的漏斗掉点，你会怎么拆？",
                        "keywords": ["SQL", "增长漏斗"],
                    }
                ],
                "foundational_questions": ["如果让你解释一次增长漏斗分析，你会怎么讲？"],
                "review_plan": ["先复习 SQL，再复习实验设计。"],
            },
            ensure_ascii=False,
        )


class FakeInterviewPrepProvider:
    name = "fake"

    @property
    def is_available(self) -> bool:
        return True

    def complete(self, system_prompt: str, user_prompt: str, metadata=None) -> str:
        del system_prompt, user_prompt, metadata
        return json.dumps(
            {
                "title": "增长产品经理 面试准备文档",
                "prep_summary": "这轮面试会重点追问 SQL、实验设计和增长分析经历。",
                "likely_focus_areas": ["SQL", "A/B Testing", "增长分析"],
                "ba_gu_questions": ["请解释 A/B 测试为什么需要先定义主指标。"],
                "project_deep_dive_questions": ["请完整讲一次增长实验项目的背景、动作和结果。"],
                "experience_deep_dive_questions": ["请展开说明你在 A 公司如何推动转化率提升 12%。"],
                "behavioral_questions": ["如果多个团队目标不一致，你会如何推进？"],
                "risk_alerts": ["社招岗位会追问职责范围和结果归因。"],
                "answer_framework": ["背景-目标-动作-结果-反思。"],
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


def test_jd_review_card_agent_accepts_structured_llm_output() -> None:
    llm_service = StructuredLLMService(
        provider=FakeReviewCardProvider(),
        prompt_loader=PromptLoader(default_version="v1"),
        max_retries=1,
    )
    agent = JDReviewCardAgent(llm_service=llm_service)
    jd_profile = JDProfile(
        job_title="增长产品经理",
        department="product",
        hiring_track="experienced",
        responsibilities=["负责增长漏斗分析与实验复盘"],
        must_have_skills=["SQL", "A/B Testing"],
        domain_signals=["growth"],
        language="zh",
    )

    cards = agent.run(jd_profile, "负责增长漏斗分析与实验复盘，要求熟悉 SQL 和 A/B Testing")

    assert len(cards) == 2
    assert cards[0].title == "SQL 与增长漏斗分析"
    assert "SQL" in cards[0].keywords


def test_jd_review_doc_agent_accepts_structured_llm_output() -> None:
    llm_service = StructuredLLMService(
        provider=FakeJDReviewDocProvider(),
        prompt_loader=PromptLoader(default_version="v1"),
        max_retries=1,
    )
    agent = JDReviewDocAgent(llm_service=llm_service)
    jd_profile = JDProfile(
        job_title="增长产品经理",
        department="product",
        hiring_track="experienced",
        responsibilities=["负责增长漏斗分析与实验复盘"],
        must_have_skills=["SQL", "A/B Testing"],
        domain_signals=["growth"],
        language="zh",
        review_cards=[],
    )

    document = agent.run(
        jd_profile,
        "负责增长漏斗分析与实验复盘，要求熟悉 SQL 和 A/B Testing",
        review_cards=[],
    )

    assert document.title == "增长产品经理 JD 复习文档"
    assert document.core_requirements[0] == "SQL"
    assert document.markdown


def test_resume_parser_fallback_skips_markdown_title_and_keeps_compound_skill() -> None:
    agent = ResumeParserAgent()
    profile, _ = agent.run(
        "# Resume\n\n张三\n\n教育背景\n某大学 | 本科 | 计算机科学\n\n技能\nSQL, A/B Testing, Tableau",
        force_fallback=True,
    )

    assert profile.basics.name == "张三"
    assert "A/B Testing" in profile.skills.hard_skills
    assert "Tableau" in profile.skills.tools


def test_resume_parser_fallback_splits_multiple_experience_and_project_blocks() -> None:
    agent = ResumeParserAgent()
    profile, _ = agent.run(
        (
            "张三\n\n"
            "工作经历\n"
            "A公司 | 产品经理\n"
            "负责增长漏斗优化，提升转化率 12%\n"
            "推动实验分析\n"
            "B公司 | 增长运营\n"
            "- 负责渠道投放复盘\n"
            "- 搭建周报看板\n\n"
            "项目经历\n"
            "用户增长实验项目\n"
            "产品经理\n"
            "设计实验方案并完成复盘\n"
            "数据看板项目\n"
            "- 使用 SQL 和 Power BI 搭建经营看板\n"
        ),
        force_fallback=True,
    )

    assert len(profile.work_experiences) == 2
    assert profile.work_experiences[0].company == "A公司"
    assert profile.work_experiences[0].title == "产品经理"
    assert profile.work_experiences[0].bullets[0].startswith("负责增长漏斗优化")
    assert len(profile.projects) == 2
    assert profile.projects[0].name == "用户增长实验项目"
    assert profile.projects[0].role == "产品经理"
    assert profile.projects[1].bullets[0].startswith("使用 SQL")


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


def test_jd_analyst_fallback_splits_requirements_and_filters_noise() -> None:
    agent = JDAnalystAgent()
    profile = agent.run(
        (
            "2026 校招数据分析师\n"
            "岗位职责\n"
            "- 负责搭建经营分析看板\n"
            "任职要求\n"
            "- 熟悉 SQL、A/B Testing，有数据分析能力和沟通能力\n"
            "加分项\n"
            "- 用户研究经验者优先\n"
        ),
        force_fallback=True,
    )

    assert profile.hiring_track == "campus"
    assert profile.job_title == "数据分析师"
    assert "SQL" in profile.must_have_skills
    assert "A/B Testing" in profile.must_have_skills
    assert "数据分析" in profile.must_have_skills
    assert "沟通能力" in profile.must_have_skills
    assert "用户研究" in profile.nice_to_have_skills
    assert "职责" not in profile.keywords
    assert "要求" not in profile.keywords
    assert "2026" not in profile.keywords


def test_review_cards_fallback_are_contextual_for_different_jds() -> None:
    agent = JDReviewCardAgent()
    product_profile = JDProfile(
        job_title="增长产品经理",
        department="product",
        hiring_track="experienced",
        must_have_skills=["SQL"],
        domain_signals=["growth"],
        responsibilities=["负责增长漏斗分析与实验复盘"],
        language="zh",
    )
    data_profile = JDProfile(
        job_title="数据分析师",
        department="data",
        hiring_track="experienced",
        must_have_skills=["SQL"],
        responsibilities=["负责独立取数、建口径并定位指标异常"],
        language="zh",
    )

    product_cards = agent.run(product_profile, "负责增长漏斗分析与实验复盘，要求熟悉 SQL", force_fallback=True)
    data_cards = agent.run(data_profile, "负责独立取数、建口径并定位指标异常，要求熟悉 SQL", force_fallback=True)

    assert product_cards
    assert data_cards
    assert product_cards[0].title == "SQL 与数据口径"
    assert "增长漏斗" in product_cards[0].why_it_matters or "增长" in product_cards[0].review_tip
    assert "建口径" in data_cards[0].why_it_matters or "取数" in data_cards[0].sample_question


def test_rewrite_agent_uses_fallback_when_llm_output_is_incomplete() -> None:
    llm_service = StructuredLLMService(
        provider=PartialRewriteProvider(),
        prompt_loader=PromptLoader(default_version="v1"),
        max_retries=1,
    )
    agent = ResumeRewriteAgent(llm_service=llm_service)
    candidate = CandidateProfile(
        basics=CandidateBasics(name="张三", language="zh"),
        work_experiences=[
            {
                "id": "exp_1",
                "company": "A公司",
                "title": "产品经理",
                "bullets": ["推动 A/B 测试与漏斗优化，提升转化率 12%", "搭建增长分析框架"],
                "achievements": ["推动 A/B 测试与漏斗优化，提升转化率 12%"],
            },
            {
                "id": "exp_2",
                "company": "B公司",
                "title": "增长运营",
                "bullets": ["负责渠道投放复盘", "搭建周报看板"],
                "achievements": [],
            },
        ],
        projects=[ProjectExperience(id="proj_1", name="增长实验项目", bullets=["使用 SQL 复盘实验结果"], skills_used=["SQL"])],
        education=[EducationEntry(id="edu_1", school="某大学", degree="本科", field_of_study="信息管理")],
        skills=SkillSet(hard_skills=["SQL", "A/B Testing"], tools=["Tableau"]),
    )
    fact_cards = [
        FactCard(id="fact_1", category="work_bullet", text="推动 A/B 测试与漏斗优化，提升转化率 12%", source_span="work_experiences.exp_1.bullets.1"),
        FactCard(id="fact_2", category="work_bullet", text="搭建增长分析框架", source_span="work_experiences.exp_1.bullets.2"),
        FactCard(id="fact_3", category="work_bullet", text="负责渠道投放复盘", source_span="work_experiences.exp_2.bullets.1"),
        FactCard(id="fact_4", category="work_bullet", text="搭建周报看板", source_span="work_experiences.exp_2.bullets.2"),
        FactCard(id="fact_5", category="project_bullet", text="使用 SQL 复盘实验结果", source_span="projects.proj_1.bullets.1"),
        FactCard(id="fact_6", category="skill", text="SQL", source_span="skills"),
        FactCard(id="fact_7", category="skill", text="A/B Testing", source_span="skills"),
    ]
    jd_profile = JDProfile(
        job_title="增长产品经理",
        department="product",
        hiring_track="experienced",
        must_have_skills=["SQL", "A/B Testing"],
        keywords=["SQL", "A/B Testing", "增长"],
        language="zh",
    )
    gap_analysis = GapAnalysis(
        fit_score_initial=78,
        strengths=["SQL", "A/B Testing", "增长"],
        missing_keywords=[],
        recommended_focus=["SQL", "A/B Testing", "增长"],
    )
    strategy = RewriteStrategy(
        audience_hint="experienced",
        section_priority=["summary", "skills", "experience", "projects", "education"],
        max_experiences=4,
        max_bullets_per_experience=4,
        max_skills=12,
        include_projects=True,
    )

    draft = agent.run(candidate, fact_cards, jd_profile, gap_analysis, strategy, "zh")

    assert len(draft.experience_section) == 2
    assert draft.project_section
    assert "增长实验项目" in draft.markdown
    assert "B公司" in draft.markdown


def test_rewrite_agent_strips_jd_requirement_tails_from_bullets() -> None:
    llm_service = StructuredLLMService(
        provider=JDTailRewriteProvider(),
        prompt_loader=PromptLoader(default_version="v1"),
        max_retries=1,
    )
    agent = ResumeRewriteAgent(llm_service=llm_service)
    candidate = CandidateProfile(
        basics=CandidateBasics(name="张三", language="zh"),
        work_experiences=[
            {
                "id": "exp_1",
                "company": "A公司",
                "title": "产品经理",
                "bullets": ["推动 A/B 测试与漏斗优化，提升转化率 12%"],
                "achievements": ["推动 A/B 测试与漏斗优化，提升转化率 12%"],
            }
        ],
        projects=[ProjectExperience(id="proj_1", name="增长实验项目", role="项目负责人", bullets=["使用 SQL 复盘实验结果"], skills_used=["SQL"])],
        education=[EducationEntry(id="edu_1", school="某大学", degree="本科", field_of_study="信息管理")],
        skills=SkillSet(hard_skills=["SQL", "A/B Testing"]),
    )
    fact_cards = [
        FactCard(id="fact_1", category="work_bullet", text="推动 A/B 测试与漏斗优化，提升转化率 12%", source_span="work_experiences.exp_1.bullets.1"),
        FactCard(id="fact_5", category="project_bullet", text="使用 SQL 复盘实验结果", source_span="projects.proj_1.bullets.1"),
        FactCard(id="fact_6", category="skill", text="SQL", source_span="skills"),
        FactCard(id="fact_7", category="skill", text="A/B Testing", source_span="skills"),
    ]
    jd_profile = JDProfile(
        job_title="增长产品经理",
        department="product",
        hiring_track="experienced",
        must_have_skills=["SQL", "A/B Testing"],
        keywords=["SQL", "A/B Testing", "增长"],
        language="zh",
    )
    gap_analysis = GapAnalysis(
        fit_score_initial=78,
        strengths=["SQL", "A/B Testing", "增长"],
        missing_keywords=[],
        recommended_focus=["SQL", "A/B Testing", "增长"],
    )
    strategy = RewriteStrategy(
        audience_hint="experienced",
        section_priority=["summary", "skills", "experience", "projects", "education"],
        max_experiences=4,
        max_bullets_per_experience=4,
        max_skills=12,
        include_projects=True,
    )

    draft = agent.run(candidate, fact_cards, jd_profile, gap_analysis, strategy, "zh")

    assert "JD" not in draft.experience_section[0].bullets[0]
    assert "岗位要求" not in draft.project_section[0].bullets[0]
    assert "对应" not in draft.markdown
    assert "符合岗位要求" not in draft.markdown


def test_rewrite_fallback_prefers_action_and_result_bullets_and_non_meta_summary() -> None:
    agent = ResumeRewriteAgent()
    candidate = CandidateProfile(
        basics=CandidateBasics(name="王五", language="zh"),
        work_experiences=[
            {
                "id": "exp_1",
                "company": "A公司",
                "title": "增长产品经理",
                "bullets": [
                    "支持团队日常协作",
                    "推动 A/B 测试与漏斗优化，提升转化率 12%",
                    "参与周会沟通",
                ],
                "achievements": ["推动 A/B 测试与漏斗优化，提升转化率 12%"],
            }
        ],
        skills=SkillSet(hard_skills=["SQL", "A/B Testing"]),
    )
    fact_cards = [
        FactCard(id="fact_1", category="work_bullet", text="支持团队日常协作", source_span="work_experiences.exp_1.bullets.1"),
        FactCard(id="fact_2", category="work_bullet", text="推动 A/B 测试与漏斗优化，提升转化率 12%", source_span="work_experiences.exp_1.bullets.2"),
        FactCard(id="fact_3", category="work_bullet", text="参与周会沟通", source_span="work_experiences.exp_1.bullets.3"),
        FactCard(id="fact_4", category="skill", text="SQL", source_span="skills"),
        FactCard(id="fact_5", category="skill", text="A/B Testing", source_span="skills"),
    ]
    jd_profile = JDProfile(
        job_title="增长产品经理",
        department="product",
        hiring_track="experienced",
        language="zh",
    )
    gap_analysis = GapAnalysis(
        fit_score_initial=80,
        strengths=["SQL", "A/B Testing", "增长"],
        recommended_focus=["A/B Testing", "增长", "转化率"],
    )
    strategy = RewriteStrategy(
        audience_hint="experienced",
        section_priority=["summary", "skills", "experience", "projects", "education"],
        max_experiences=3,
        max_bullets_per_experience=3,
        max_skills=8,
        include_projects=False,
        summary_style="impact_and_scope",
    )

    draft = agent._run_fallback(candidate, fact_cards, jd_profile, gap_analysis, strategy, "zh")

    assert "围绕" not in draft.summary
    assert "已按" not in draft.summary
    assert draft.experience_section[0].bullets[0] == "推动 A/B 测试与漏斗优化，提升转化率 12%"


def test_compliance_agent_reports_medium_risk_for_seniority_and_keyword_stuffing() -> None:
    agent = TruthfulnessComplianceAgent()
    draft = ResumeDraft(
        headline="张三 | 面向 高级产品经理 的定制简历",
        summary="资深产品经理，拥有5年经验，熟悉 SQL、A/B Testing、SQL。",
        skills_section=["SQL", "A/B Testing"],
        experience_section=[
            ResumeSectionItem(
                heading="产品经理",
                subheading="A公司",
                bullets=["推动 A/B 测试与漏斗优化，提升转化率 12%"],
            )
        ],
        markdown=(
            "# 张三 | 面向 高级产品经理 的定制简历\n\n"
            "## 简介\n资深产品经理，拥有5年经验，熟悉 SQL、A/B Testing、SQL。\n\n"
            "## 工作经历\n### 产品经理\nA公司\n- 推动 A/B 测试与漏斗优化，提升转化率 12%\n"
        ),
        traceability=[TraceabilityRecord(draft_span="experience_section.1.bullets.1", fact_ids=["fact_1"])],
    )
    fact_cards = [
        FactCard(id="fact_1", category="work_bullet", text="推动 A/B 测试与漏斗优化，提升转化率 12%", source_span="work_experiences.exp_1.bullets.1"),
        FactCard(id="fact_2", category="skill", text="SQL", source_span="skills"),
        FactCard(id="fact_3", category="skill", text="A/B Testing", source_span="skills"),
    ]

    report = agent.run(draft, fact_cards)

    assert report.risk_level == "medium"
    assert report.seniority_mismatches


def test_critic_agent_flags_jd_annotation_style_bullets() -> None:
    agent = CriticAgent()
    draft = ResumeDraft(
        headline="张三 | 面向 增长产品经理 的定制简历",
        summary="具备 SQL 和 A/B Testing 相关经验。",
        skills_section=["SQL", "A/B Testing"],
        experience_section=[
            ResumeSectionItem(
                heading="产品经理",
                subheading="A公司",
                bullets=["推动 A/B 测试与漏斗优化，提升转化率 12% - 对应 JD 的数据分析要求"],
            )
        ],
        markdown="# 张三 | 面向 增长产品经理 的定制简历",
    )
    jd_profile = JDProfile(job_title="增长产品经理", hiring_track="experienced", language="zh")
    strategy = RewriteStrategy(audience_hint="experienced")
    compliance_report = ComplianceReport(risk_level="low")
    ats_report = ATSReport(score=83)

    report = agent.run(draft, jd_profile, strategy, compliance_report, ats_report, force_fallback=True)

    assert report.major_issues >= 1
    assert any("JD" in issue or "注释" in issue for issue in report.minor_issues)


def test_interview_prep_agent_accepts_structured_llm_output() -> None:
    llm_service = StructuredLLMService(
        provider=FakeInterviewPrepProvider(),
        prompt_loader=PromptLoader(default_version="v1"),
        max_retries=1,
    )
    agent = InterviewPrepAgent(llm_service=llm_service)
    candidate = CandidateProfile(
        basics=CandidateBasics(name="张三", language="zh"),
        work_experiences=[
            {
                "id": "exp_1",
                "company": "A公司",
                "title": "产品经理",
                "bullets": ["推动 A/B 测试与漏斗优化，提升转化率 12%"],
                "achievements": ["推动 A/B 测试与漏斗优化，提升转化率 12%"],
            }
        ],
        projects=[ProjectExperience(id="proj_1", name="增长实验项目", bullets=["使用 SQL 复盘实验结果"], skills_used=["SQL"])],
        skills=SkillSet(hard_skills=["SQL", "A/B Testing"]),
    )
    fact_cards = [
        FactCard(id="fact_1", category="work_bullet", text="推动 A/B 测试与漏斗优化，提升转化率 12%", source_span="work_experiences.exp_1.bullets.1")
    ]
    jd_profile = JDProfile(
        job_title="增长产品经理",
        department="product",
        hiring_track="experienced",
        must_have_skills=["SQL", "A/B Testing"],
        keywords=["SQL", "A/B Testing", "增长"],
        language="zh",
    )
    gap_analysis = GapAnalysis(
        fit_score_initial=78,
        strengths=["SQL", "A/B Testing"],
        recommended_focus=["SQL", "增长实验项目"],
    )
    strategy = RewriteStrategy(
        audience_hint="experienced",
        section_priority=["summary", "skills", "experience", "projects", "education"],
        include_projects=True,
    )
    draft = ResumeDraft(
        headline="张三 | 增长产品经理",
        summary="具备 SQL 和实验设计相关经验。",
        skills_section=["SQL", "A/B Testing"],
        experience_section=[ResumeSectionItem(heading="产品经理", subheading="A公司", bullets=["推动 A/B 测试与漏斗优化，提升转化率 12%"])],
        project_section=[ResumeSectionItem(heading="增长实验项目", bullets=["使用 SQL 复盘实验结果"])],
        markdown="# 张三 | 增长产品经理",
    )
    latest_review = ReviewBundle(
        iteration=1,
        compliance_report=ComplianceReport(risk_level="low"),
        ats_report=ATSReport(score=84),
        critic_report=CriticReport(major_issues=0),
    )

    document = agent.run(candidate, fact_cards, jd_profile, gap_analysis, strategy, draft, latest_review, "zh")

    assert document.title == "增长产品经理 面试准备文档"
    assert "SQL" in document.likely_focus_areas
    assert document.markdown
