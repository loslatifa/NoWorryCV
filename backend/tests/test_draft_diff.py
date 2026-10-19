from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.schemas.candidate import (
    CandidateBasics,
    CandidateProfile,
    WorkExperience,
)
from backend.app.schemas.common import FactCard, TraceabilityRecord
from backend.app.schemas.strategy import ResumeDraft, ResumeSectionItem
from backend.app.services.draft_diff import build_draft_diff

from backend.tests.test_draft_editing import _completed_run


def test_build_draft_diff_marks_modified_added_removed_and_sources() -> None:
    candidate = CandidateProfile(
        basics=CandidateBasics(name="张三"),
        summary="三年数据分析经验",
        work_experiences=[
            WorkExperience(
                id="work-1",
                company="示例科技",
                title="数据分析师",
                bullets=["使用 SQL 完成经营分析"],
            )
        ],
    )
    facts = [
        FactCard(
            id="fact-work",
            category="work_bullet",
            text="使用 SQL 完成经营分析",
            source_span="work_experiences.work-1.bullets.1",
            source_excerpt="使用 SQL 完成经营分析",
            confirmed=True,
        ),
        FactCard(
            id="fact-skill",
            category="skill",
            text="Python",
            source_span="skills.hard_skills.1",
            source_excerpt="Python",
            confirmed=True,
        ),
    ]
    draft = ResumeDraft(
        headline="张三｜增长数据分析师",
        summary="擅长以数据驱动增长决策",
        skills_section=["SQL", "Tableau"],
        experience_section=[
            ResumeSectionItem(
                heading="数据分析师",
                subheading="示例科技",
                bullets=["运用 SQL 支持经营分析", "将转化率提升 30%"],
            )
        ],
        traceability=[
            TraceabilityRecord(
                draft_span="experience_section.1.bullets.1",
                fact_ids=["fact-work"],
            )
        ],
    )

    result = build_draft_diff(candidate, facts, draft)

    modified = next(item for item in result.items if item.id == "draft:experience_section.1.bullets.1")
    assert modified.change_type == "modified"
    assert modified.original_text == "使用 SQL 完成经营分析"
    assert modified.fact_ids == ["fact-work"]
    assert modified.source_excerpts == ["使用 SQL 完成经营分析"]

    added = next(item for item in result.items if item.id == "draft:experience_section.1.bullets.2")
    assert added.change_type == "added"
    assert added.risk_level == "high"
    assert added.fact_ids == []

    removed = next(item for item in result.items if item.id == "removed:fact-skill")
    assert removed.change_type == "removed"
    assert removed.target_type == "skill_removed"
    assert result.ungrounded_count >= 2


def test_completed_run_exposes_draft_diff_api() -> None:
    completed = _completed_run()
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/tailor-runs/{0}/draft-diff".format(completed.run_id),
        headers={"X-Run-Token": completed.access_token},
        json={"draft": completed.result.final_package.draft.model_dump(mode="json")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "items",
        "added_count",
        "modified_count",
        "removed_count",
        "ungrounded_count",
        "version_id",
    }
    assert all(item["original_text"] or item["change_type"] == "added" for item in payload["items"])
