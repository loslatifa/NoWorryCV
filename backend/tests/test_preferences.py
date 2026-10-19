from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest

from backend.app.agents.strategy import StrategyAgent
from backend.app.main import create_app
from backend.app.schemas.preferences import PREFERENCE_OPTIONS, ResumePreferences
from backend.app.schemas.review import CriticReport
from backend.app.services.profiles import CandidateArchiveStore
from backend.app.services.resume_export import build_docx, build_pdf
from backend.app.services.runs.store import get_run_store
from backend.tests.test_applications import create, ready, approve
from backend.tests.test_candidate_profiles import confirmed_material, save_archive, wait_for_run
from backend.tests.test_resume_export import _sample_resume
from backend.tests.test_draft_editing import _completed_run


CHOICES = dict(region="CN", job_family="data", hiring_track="experienced", seniority="mid",
               language="en", tone="concise", page_count="2", template="ats_compact")


def save_preferences(client, archive, headers, preferences=CHOICES, revision=1):
    return client.patch(f'/api/v1/candidate-profiles/{archive["id"]}/preferences', headers=headers,
                        json={"preferences": preferences, "expected_preferences_revision": revision})


def test_preferences_are_private_versioned_and_independent_of_fact_revision(tmp_path):
    with TestClient(create_app()) as client:
        archive, headers = save_archive(client)
        assert save_preferences(client, archive, {}).status_code == 404
        updated = save_preferences(client, archive, headers)
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 1
        assert updated.json()["preferences_revision"] == 2
        assert save_preferences(client, archive, headers).status_code == 409
        same = save_preferences(client, archive, headers, revision=2)
        assert same.json()["preferences_revision"] == 2
        # Editing facts through an older client must preserve saved preferences.
        payload = {**confirmed_material(), "expected_revision": 1}
        response = client.put(f'/api/v1/candidate-profiles/{archive["id"]}', headers=headers, json=payload)
        assert response.json()["preferences"] == CHOICES
        reloaded = CandidateArchiveStore(str(tmp_path / "candidate_archives.sqlite3"))
        assert reloaded.get_authorized(archive["id"], archive["access_token"]).preferences.language == "en"


@pytest.mark.parametrize("invalid", [{"region": "XX"}, {"page_count": "3"}, {"seniority": "invented"}, {"unexpected": True}])
def test_invalid_preferences_rejected(invalid):
    with TestClient(create_app()) as client:
        archive, headers = save_archive(client)
        assert save_preferences(client, archive, headers, invalid).status_code == 422


def test_catalog_matches_schema_and_preserves_legacy_defaults():
    with TestClient(create_app()) as client:
        catalog = client.get("/api/v1/resume-preferences").json()
        assert catalog["defaults"] == ResumePreferences().model_dump()
        for key, options in PREFERENCE_OPTIONS.items():
            assert set(options) == set(ResumePreferences.model_fields[key].annotation.__args__)


def test_saved_preferences_inherited_explicit_choices_override_detection_and_stay_frozen():
    with TestClient(create_app()) as client:
        archive, headers = save_archive(client)
        save_preferences(client, archive, headers)
        path = f'/api/v1/candidate-profiles/{archive["id"]}/jobs'
        request = {"jd_text": "数据开发实习生，要求 SQL，数据分析与报表开发。", "expected_revision": 1, "max_iterations": 1}
        job = client.post(path, headers=headers, json=request).json()
        result = wait_for_run(client, job)["result"]
        assert result["preferences"] == CHOICES
        assert result["detected_jd_profile"]["hiring_track"] == "intern"
        assert result["jd_profile"]["hiring_track"] == "experienced"
        assert result["jd_profile"]["seniority"] == "mid"
        assert result["resolved_language"] == "en"
        assert result["rewrite_strategy"]["max_bullets_per_experience"] <= 2
        assert result["rewrite_strategy"]["preferences"] == CHOICES
        assert result["candidate_profile"]["projects"][0]["bullets"] == ["使用 SQL 分析增长实验"]
        overrides = {**CHOICES, "hiring_track": "campus", "language": "zh", "region": "US"}
        second = client.post(path, headers=headers, json={**request, "preferences": overrides}).json()
        result2 = wait_for_run(client, second)["result"]
        assert result2["jd_profile"]["hiring_track"] == "campus"
        assert result2["resolved_language"] == "zh"
        save_preferences(client, archive, headers, overrides, revision=2)
        frozen = client.get(f'/api/v1/tailor-runs/{job["run_id"]}/status', headers={"X-Run-Token": job["access_token"]}).json()
        assert frozen["result"]["preferences"] == CHOICES


def test_real_model_context_and_refinement_retain_explicit_preferences():
    from backend.app.agents.orchestrator import ResumeTailorOrchestrator
    from backend.app.schemas.run_state import TailorRunInput

    material = confirmed_material()
    result = ResumeTailorOrchestrator().run(TailorRunInput(
        jd_text="数据实习，SQL 数据分析。", preferences=ResumePreferences(**CHOICES),
        confirmed_candidate_profile=material["candidate_profile"], confirmed_fact_cards=material["fact_cards"],
        max_iterations=1,
    ))
    agent = StrategyAgent()
    for compact in (False, True):
        context = agent._build_llm_context(result.candidate_profile, result.gap_analysis, result.fact_cards,
                                          result.jd_profile, result.resolved_language, compact,
                                          result.preferences)
        assert context["preferences"] == CHOICES
    refined = agent.refine(result.rewrite_strategy, CriticReport(major_issues=2), force_fallback=True)
    assert refined.preferences == result.preferences
    assert refined.max_bullets_per_experience == 2
    from backend.app.agents.rewrite import ResumeRewriteAgent
    context = ResumeRewriteAgent()._build_llm_context(
        result.candidate_profile, result.fact_cards, result.jd_profile, result.gap_analysis,
        result.rewrite_strategy, result.resolved_language, compact_mode=True)
    assert context["rewrite_strategy"]["preferences"] == CHOICES
    assert context["rewrite_strategy"]["tone_rules"]


def test_partial_job_override_inherits_other_saved_choices():
    from backend.app.services.preferences import merge_preferences
    saved = ResumePreferences(**CHOICES)
    effective = merge_preferences(saved, ResumePreferences(region="US", hiring_track="auto"))
    assert effective.language == "en"
    assert effective.region == "US"
    assert effective.hiring_track == "auto"
    assert saved.region == "CN"


def test_export_preview_warns_against_selected_page_budget_without_truncation():
    completed = _completed_run()
    result = completed.result.model_copy(deep=True)
    result.preferences = ResumePreferences(page_count="2", region="CN")
    candidate, draft = _sample_resume()
    draft.experience_section[0].bullets *= 30
    # This deliberately long draft exercises the actual renderer, not an estimated page count.
    while len(PdfReader(BytesIO(build_pdf(draft, candidate, result.preferences))).pages) < 2:
        draft.experience_section[0].bullets *= 2
    assert len(PdfReader(BytesIO(build_pdf(draft, candidate, result.preferences))).pages) == 2
    get_run_store().update(completed.run_id, result=result)
    with TestClient(create_app()) as client:
        endpoint = f'/api/v1/tailor-runs/{completed.run_id}/export-preview'
        headers = {"X-Run-Token": completed.access_token}
        response = client.post(endpoint, headers=headers, json={"draft": draft.model_dump()})
        assert response.headers["x-page-count"] == "2"
        assert response.headers["x-overflow"] == "false"
        assert response.headers["x-target-pages"] == "2"
        draft.experience_section[0].bullets *= 2
        response = client.post(endpoint, headers=headers, json={"draft": draft.model_dump()})
        assert int(response.headers["x-page-count"]) > 2
        assert response.headers["x-overflow"] == "true"
        reader = PdfReader(BytesIO(response.content))
        assert sum((page.extract_text() or "").count("设计 A/B 测试") for page in reader.pages) == 60


@pytest.mark.parametrize("region,width,height", [("CN", 595.28, 841.89), ("UK", 595.28, 841.89), ("US", 612, 792), ("CA", 612, 792)])
def test_regional_templates_keep_readable_contents_and_correct_paper(region, width, height):
    candidate, draft = _sample_resume()
    preferences = ResumePreferences(region=region, template="ats_compact", language="en")
    reader = PdfReader(BytesIO(build_pdf(draft, candidate, preferences)))
    assert float(reader.pages[0].mediabox.width) == pytest.approx(width, abs=0.1)
    assert float(reader.pages[0].mediabox.height) == pytest.approx(height, abs=0.1)
    assert "Summary" in reader.pages[0].extract_text()
    assert "使用 SQL 分析增长漏斗" in reader.pages[0].extract_text()
    doc = Document(BytesIO(build_docx(draft, candidate, preferences)))
    assert doc.sections[0].page_width.pt == pytest.approx(width, abs=0.1)
    assert doc.sections[0].page_height.pt == pytest.approx(height, abs=0.1)
    assert any(p.text == "Summary" for p in doc.paragraphs)


def test_confirmed_application_keeps_preferences_and_export_after_source_run_deleted():
    with TestClient(create_app()) as client:
        archive, headers = save_archive(client)
        save_preferences(client, archive, headers)
        path, record, _ = create(client, archive, headers)
        record = ready(client, path, record, headers)
        assert record["preferences"] == CHOICES
        approved = approve(client, path, record, headers)
        save_preferences(client, archive, headers, {"region": "US"}, revision=2)
        assert get_run_store().delete_authorized(approved["run_id"], archive["access_token"])
        snapshot = client.get(f'{path}/{record["id"]}', headers=headers).json()
        assert snapshot["preferences"] == CHOICES
        response = client.get(f'{path}/{record["id"]}/resume/pdf', headers=headers)
        assert response.status_code == 200
        assert float(PdfReader(BytesIO(response.content)).pages[0].mediabox.width) == pytest.approx(595.28, abs=0.1)
