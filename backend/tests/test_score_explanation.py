from fastapi.testclient import TestClient

from backend.app.agents.ats import ATSScoringAgent
from backend.app.main import create_app
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.review import ComplianceReport
from backend.app.schemas.strategy import ResumeDraft, ResumeSectionItem
from backend.tests.test_draft_editing import _completed_run


def _draft() -> ResumeDraft:
    return ResumeDraft(
        headline="张三 | 产品经理",
        summary="能够使用 SQL 分析增长数据。",
        skills_section=["SQL"],
        experience_section=[
            ResumeSectionItem(
                heading="产品经理",
                subheading="示例公司",
                bullets=["使用 SQL 复盘转化漏斗并推动迭代。"],
            )
        ],
        project_section=[
            ResumeSectionItem(
                heading="增长分析项目",
                bullets=["整理业务指标并输出分析结论。"],
            )
        ],
        education_section=["示例大学 | 本科"],
    )


def _jd_profile() -> JDProfile:
    return JDProfile(
        job_title="产品经理",
        hiring_track="experienced",
        must_have_skills=["SQL", "用户研究"],
        nice_to_have_skills=["Tableau"],
        language="zh",
    )


def test_jd_match_report_explains_dimensions_keywords_and_locations() -> None:
    report = ATSScoringAgent().run(
        _draft(),
        _jd_profile(),
        ComplianceReport(risk_level="low"),
    )

    assert report.core_keyword_score == 50
    assert report.optional_keyword_score == 0
    assert report.structure_score == 100
    assert report.truthfulness_score == 100
    assert report.matched_core_keywords == ["SQL"]
    assert report.missing_core_keywords == ["用户研究"]
    assert report.missing_optional_keywords == ["Tableau"]
    sql_detail = next(item for item in report.keyword_details if item.keyword == "SQL")
    assert sql_detail.matched is True
    assert "技能 · SQL" in sql_detail.locations
    assert any("工作经历" in location for location in sql_detail.locations)
    assert {reason.category for reason in report.score_reasons} == {
        "core_keywords",
        "optional_keywords",
        "structure",
        "truthfulness",
    }
    assert "不代表 ATS 通过概率" in report.disclaimer


def test_truthfulness_risk_is_a_visible_scoring_dimension() -> None:
    agent = ATSScoringAgent()
    low_risk = agent.run(_draft(), _jd_profile(), ComplianceReport(risk_level="low"))
    high_risk = agent.run(
        _draft(),
        _jd_profile(),
        ComplianceReport(
            risk_level="high",
            unsupported_claims=["使用 SQL 复盘转化漏斗并推动迭代。"],
        ),
    )

    assert high_risk.truthfulness_score == 30
    assert high_risk.score < low_risk.score
    assert any("缺少事实溯源" in item for item in high_risk.deductions)
    truth_reason = next(reason for reason in high_risk.score_reasons if reason.category == "truthfulness")
    assert "风险为高" in truth_reason.message


def test_score_api_compares_original_and_current_draft() -> None:
    completed = _completed_run()
    draft = completed.result.final_package.draft.model_copy(deep=True)
    draft.project_section[0].bullets[0] = "新增了无法从原始事实中验证的成果"

    response = TestClient(create_app()).post(
        "/api/v1/tailor-runs/{0}/score".format(completed.run_id),
        headers={"X-Run-Token": completed.access_token},
        json={"draft": draft.model_dump(mode="json")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["score_delta"] == payload["tailored"]["score"] - payload["baseline"]["score"]
    assert payload["compliance_report"]["risk_level"] == "high"
    assert payload["tailored"]["truthfulness_score"] == 30
    assert payload["baseline"]["truthfulness_score"] == 100
    assert payload["tailored"]["keyword_details"]
    assert payload["tailored"]["score_reasons"]
