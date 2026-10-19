from datetime import datetime, timedelta, timezone
import json
import sqlite3

from fastapi.testclient import TestClient
import pytest

from backend.app.main import create_app
from backend.app.graph.resume_tailor_graph import run_tailor_pipeline
from backend.app.schemas.run_state import TailorRunInput
from backend.app.services.provenance import capture_provenance
from backend.app.services.quality import QualityStore, get_quality_store
from backend.app.services.runs.store import get_run_store
from backend.app.agents.orchestrator import ResumeTailorOrchestrator


def completed(language="zh"):
    store = get_run_store()
    job = store.create("质量测试")
    result = run_tailor_pipeline(TailorRunInput(
        resume_text="候选人甲\n\n项目经历\n数据看板\n- 使用 SQL 开发数据看板\n技能\nSQL, Python",
        jd_text="校招数据分析师\n要求：SQL、Python 和数据分析。", output_language=language,
        max_iterations=1, processing_mode="application",
    ), run_id=job.run_id)
    store.mark_completed(job.run_id, result, "完成")
    return store.get_authorized(job.run_id, job.access_token), {"X-Run-Token": job.access_token}, job.access_token


def dashboard(client, job, token, **filters):
    response = client.post("/api/v1/quality/dashboard", json={"runs": [{"id": job.run_id, "token": token}], **filters})
    assert response.status_code == 200, response.text
    return response.json()


def test_feedback_is_version_bound_updatable_and_persistent(tmp_path):
    client = TestClient(create_app())
    job, headers, token = completed()
    path = f"/api/v1/tailor-runs/{job.run_id}/feedback"
    payload = {"version_id": job.result.active_version_id, "rating": 2, "reason": "clarity"}
    first = client.post(path, headers=headers, json=payload)
    assert first.status_code == 200, first.text
    second = client.post(path, headers=headers, json={**payload, "rating": 5})
    assert second.json()["id"] == first.json()["id"]
    assert second.json()["created_at"] == first.json()["created_at"]
    assert len(client.get(path, headers=headers).json()) == 1
    assert second.json()["source"] == "generated"
    assert second.json()["provenance"]["model"] == "stub"
    assert len(QualityStore(str(tmp_path / "quality.sqlite3")).feedback_for_run(job.run_id)) == 1
    metrics = dashboard(client, job, token)["metrics"]
    assert metrics["feedback_count"] == 1 and metrics["average_rating"] == 5
    assert metrics["satisfaction_rate"] == 1 and metrics["reviewed_runs"] == 1
    assert metrics["export_rate"] == 0


def test_change_decisions_count_explicit_latest_decision_not_default_or_retries():
    client = TestClient(create_app())
    job, headers, token = completed()
    version_id = job.result.active_version_id
    path = f"/api/v1/tailor-runs/{job.run_id}"
    diff = client.post(path + "/draft-diff", headers=headers, json={"draft": job.result.final_package.draft.model_dump()}).json()
    assert diff["version_id"] == version_id
    assert dashboard(client, job, token)["metrics"]["change_acceptance_rate"] is None
    target = diff["items"][0]["id"]
    payload = {"version_id": version_id, "target_id": target, "decision": "accepted", "event_id": "retry-safe"}
    assert client.post(path + "/change-decisions", headers=headers, json=payload).status_code == 200
    assert client.post(path + "/change-decisions", headers=headers, json=payload).status_code == 200
    assert dashboard(client, job, token)["metrics"]["accepted_changes"] == 1
    assert client.post(path + "/change-decisions", headers=headers, json={**payload, "event_id": "reject", "decision": "rejected"}).status_code == 200
    metrics = dashboard(client, job, token)["metrics"]
    assert metrics["accepted_changes"] == 0 and metrics["rejected_changes"] == 1
    assert metrics["change_acceptance_rate"] == 0
    feedback = {"version_id": version_id, "scope": "change", "target_id": target, "rating": 3, "reason": "relevance"}
    assert client.post(path + "/feedback", headers=headers, json=feedback).status_code == 200
    # Single-change scores must not masquerade as whole-resume satisfaction.
    assert dashboard(client, job, token)["metrics"]["feedback_count"] == 0
    assert dashboard(client, job, token)["metrics"]["change_feedback_count"] == 1


def test_private_feedback_routes_and_dashboard_cannot_read_another_owner():
    client = TestClient(create_app())
    job, headers, token = completed()
    other, other_headers, other_token = completed("en")
    path = f"/api/v1/tailor-runs/{job.run_id}"
    payload = {"version_id": job.result.active_version_id, "rating": 5}
    for credential in ({}, other_headers):
        assert client.get(path + "/feedback", headers=credential).status_code == 404
        assert client.post(path + "/feedback", headers=credential, json=payload).status_code == 404
        assert client.post(path + "/change-decisions", headers=credential,
                           json={"version_id": job.result.active_version_id, "target_id": "draft:summary", "decision": "accepted"}).status_code == 404
    assert client.post("/api/v1/quality/dashboard", json={}).json()["metrics"]["started_runs"] == 0
    assert dashboard(client, job, other_token)["metrics"]["started_runs"] == 0
    own = dashboard(client, other, other_token)
    assert own["metrics"]["started_runs"] == 1
    assert len(own["by_language"]) == 1 and own["by_language"][0]["key"] == "en"
    assert dashboard(client, other, other_token, language="zh")["metrics"]["started_runs"] == 0
    assert "access_token" not in json.dumps(own)
    assert "候选人甲" not in json.dumps(own, ensure_ascii=False)


@pytest.mark.parametrize("change", ["wrong_version", "wrong_target", "missing_target", "prose", "rating"])
def test_feedback_rejects_wrong_version_target_or_unstructured_personal_text(change):
    client = TestClient(create_app())
    job, headers, _ = completed()
    payload = {"version_id": job.result.active_version_id, "rating": 5}
    if change == "wrong_version": payload["version_id"] = "not-a-version"
    elif change == "wrong_target": payload.update(scope="change", target_id="not-a-change")
    elif change == "missing_target": payload["scope"] = "change"
    elif change == "prose": payload["comment"] = "private email@example.com"
    else: payload["rating"] = 9
    response = client.post(f"/api/v1/tailor-runs/{job.run_id}/feedback", headers=headers, json=payload)
    assert response.status_code in {404, 422}


def test_export_and_actual_saved_edits_are_recorded_but_preview_and_failed_export_are_not():
    client = TestClient(create_app())
    job, headers, token = completed()
    path = f"/api/v1/tailor-runs/{job.run_id}"
    draft = job.result.final_package.draft.model_dump()
    assert client.post(path + "/export-preview", headers=headers, json={"draft": draft}).status_code == 200
    assert client.post(path + "/export/bad", headers=headers, json={"draft": draft}).status_code == 400
    assert dashboard(client, job, token)["metrics"]["exported_runs"] == 0
    assert client.post(path + "/export/pdf", headers=headers, json={"draft": draft}).status_code == 200
    assert client.post(path + "/export/pdf", headers=headers, json={"draft": draft}).status_code == 200
    assert dashboard(client, job, token)["metrics"]["exported_runs"] == 1
    assert client.put(path + "/draft", headers=headers, json={"draft": draft}).status_code == 200
    assert dashboard(client, job, token)["metrics"]["edited_runs"] == 0
    draft["summary"] = "修改后的摘要"
    saved = client.put(path + "/draft", headers=headers, json={"draft": draft})
    assert saved.status_code == 200
    metrics = dashboard(client, job, token)["metrics"]
    assert metrics["edited_runs"] == 1 and metrics["export_rate"] == 1


def test_quality_data_is_erased_on_task_expiry_and_explicit_delete(tmp_path):
    client = TestClient(create_app())
    job, headers, token = completed()
    client.post(f"/api/v1/tailor-runs/{job.run_id}/feedback", headers=headers,
                json={"version_id": job.result.active_version_id, "rating": 5})
    get_run_store().update(job.run_id, expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    assert dashboard(client, job, token)["metrics"]["started_runs"] == 0
    assert not get_quality_store().feedback_for_run(job.run_id)
    second, headers, token = completed()
    assert client.delete(f"/api/v1/tailor-runs/{second.run_id}", headers=headers).status_code == 204
    with sqlite3.connect(tmp_path / "quality.sqlite3") as db:
        assert db.execute("SELECT COUNT(*) FROM quality_runs").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM quality_events").fetchone()[0] == 0


def test_generation_metadata_is_server_captured_reproducible_and_contains_no_credentials():
    first = capture_provenance("application")
    assert first == capture_provenance("application")
    assert first.model == "stub" and first.prompt_version == "v1"
    assert len(first.prompt_digest) == 64 and len(first.scoring_digest) == 64
    assert first.scoring_version == "jd-match-v1"
    result = run_tailor_pipeline(TailorRunInput(
        resume_text="候选人\n技能\nPython", jd_text="后端开发\n要求：Python", processing_mode="application",
        provenance=first.model_copy(update={"model": "client-forged-model"}), max_iterations=1,
    ))
    assert result.provenance.model == "stub"
    assert result.resolved_language in {"zh", "en"}
    assert "api_key" not in result.provenance.model_dump_json()


def test_feedback_is_deleted_with_its_version_and_new_version_keeps_own_context():
    client = TestClient(create_app())
    job, headers, token = completed()
    path = f"/api/v1/tailor-runs/{job.run_id}"
    old_id = job.result.active_version_id
    assert client.post(path + "/feedback", headers=headers, json={"version_id": old_id, "rating": 5}).status_code == 200
    draft = job.result.final_package.draft.model_dump()
    draft["summary"] = "更新后的摘要"
    saved = client.put(path + "/draft", headers=headers, json={"draft": draft}).json()["version"]
    assert saved["provenance"]["processing_mode"] == "manual_edit"
    assert client.delete(path + f"/draft-versions/{old_id}", headers=headers).status_code == 204
    assert client.get(path + "/feedback", headers=headers).json() == []
    assert dashboard(client, job, token)["metrics"]["feedback_count"] == 0
    assert dashboard(client, job, token)["metrics"]["completed_runs"] == 1


def test_identical_copied_draft_feedback_targets_active_copy_not_original():
    client = TestClient(create_app())
    job, headers, _ = completed()
    path = f"/api/v1/tailor-runs/{job.run_id}"
    original = job.result.active_version_id
    copied = client.post(path + f"/draft-versions/{original}/copy", headers=headers).json()
    copy_id = copied["versions"][-1]["id"]
    assert copy_id != original
    assert client.post(path + f"/draft-versions/{copy_id}/restore", headers=headers).status_code == 200
    diff = client.post(path + "/draft-diff", headers=headers, json={"draft": job.result.final_package.draft.model_dump()}).json()
    assert diff["version_id"] == copy_id
    response = client.post(path + "/feedback", headers=headers,
                           json={"version_id": copy_id, "scope": "change", "target_id": diff["items"][0]["id"], "rating": 5})
    assert response.json()["version_id"] == copy_id and response.json()["source"] == "copied"


def test_resuming_under_changed_runtime_records_both_versions_and_separate_metrics_group():
    job, _, _ = completed()
    payload = TailorRunInput(
        resume_text="候选人\n技能\nPython", jd_text="后端开发\n要求：Python", processing_mode="application", max_iterations=1,
    )
    checkpoints = []
    orchestrator = ResumeTailorOrchestrator()
    orchestrator.run_resumable(payload, run_id=job.run_id,
                              checkpoint_callback=lambda stage, following, state, _duration: checkpoints.append((stage, following, state)))
    _stage, _following, state = next(item for item in checkpoints if item[0] == "review")
    state["input"]["provenance"]["fingerprint"] = "older-environment"
    state["provenance_history"][0]["fingerprint"] = "older-environment"
    resumed = orchestrator.run_resumable(payload, run_id=job.run_id, checkpoint_state=state, next_stage="finalize")
    assert resumed.provenance.fingerprint == "older-environment"
    assert len(resumed.provenance_history) == 2
    get_run_store().mark_completed(job.run_id, resumed, "恢复完成")
    report = get_quality_store().dashboard({job.run_id})
    assert report.by_generation_version[0].key.startswith("mixed:")
    assert report.provenance[0].model == "multiple"
