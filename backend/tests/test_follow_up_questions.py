from backend.app.schemas.candidate import CandidateBasics, CandidateProfile, ProjectExperience, SkillSet
from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.strategy import GapAnalysis
from backend.app.services.follow_up_questions import build_follow_up_questions


def test_build_follow_up_questions_targets_missing_evidence_and_project_role() -> None:
    candidate = CandidateProfile(
        basics=CandidateBasics(name="张三", language="zh"),
        projects=[
            ProjectExperience(
                id="proj_1",
                name="增长实验",
                bullets=["负责实验复盘"],
            )
        ],
        skills=SkillSet(hard_skills=["SQL"]),
    )
    fact_cards = [
        FactCard(
            id="fact_1",
            category="project_bullet",
            text="负责实验复盘",
            source_span="projects.proj_1.bullets.1",
        ),
        FactCard(id="fact_2", category="skill", text="SQL", source_span="skills"),
    ]
    jd_profile = JDProfile(
        job_title="产品经理",
        hiring_track="campus",
        must_have_skills=["SQL", "用户研究"],
        keywords=["SQL", "用户研究", "A/B Testing"],
        language="zh",
    )
    gap_analysis = GapAnalysis(
        missing_keywords=["用户研究", "A/B Testing"],
        gaps=["缺少用户研究证据"],
    )

    questions = build_follow_up_questions(candidate, fact_cards, jd_profile, gap_analysis)

    assert 1 <= len(questions) <= 5
    assert any("用户研究" in question.prompt for question in questions)
    assert any(question.id == "quantified_impact" for question in questions)
    assert any(question.id == "project_role" for question in questions)
    assert all(question.priority in {"recommended", "optional"} for question in questions)
