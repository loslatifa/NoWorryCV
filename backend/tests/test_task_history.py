from datetime import datetime, timedelta, timezone
import json

from fastapi.testclient import TestClient
import pytest

from backend.app.graph.resume_tailor_graph import run_tailor_pipeline
from backend.app.main import create_app
from backend.app.schemas.profile import CandidateArchiveSave
from backend.app.schemas.run_state import TailorRunInput
from backend.app.services.profiles import get_candidate_archive_store
from backend.app.services.runs.queue import get_task_queue
from backend.app.services.runs.store import get_run_store, reset_run_store_cache


def completed_run(company="测试公司", role="产品经理", archive_id=""):
    store = get_run_store()
    job = store.create("任务已创建")
    payload = TailorRunInput(
        resume_text="张三\n\n项目经历\n增长实验项目\n- 使用 SQL 复盘实验结果\n\n技能\nSQL",
        jd_text=f"{company}\n{role}\n要求：SQL，数据分析", max_iterations=1, processing_mode="fast",
    )
    store.update(job.run_id, target_company=company, target_job_title=role,
                 jd_text=payload.jd_text, candidate_archive_id=archive_id)
    result = run_tailor_pipeline(payload, run_id=job.run_id)
    store.mark_completed(job.run_id, result, "完成")
    return store.get(job.run_id).model_copy(update={"access_token": job.access_token}), payload


def credentials(*jobs):
    return {"runs": [{"id": job.run_id, "token": job.access_token} for job in jobs]}


def headers(job):
    return {"X-Run-Token": job.access_token}


def archive():
    return get_candidate_archive_store().create(CandidateArchiveSave(
        candidate_profile={"basics": {"name": "张三"}},
        fact_cards=[{"id": "skill", "category": "skill", "text": "SQL", "confirmed": True}],
        confirmed=True, storage_consent=True,
    ))


def test_history_search_filters_sorting_and_metadata_persist_without_exposing_tokens():
    client = TestClient(create_app())
    first, _ = completed_run(company="Alpha", role="数据分析师")
    second, _ = completed_run(company="Beta", role="产品经理")
    store = get_run_store()
    store.update(first.run_id, created_at="2026-10-10T00:00:00+00:00")
    store.update(second.run_id, created_at="2026-10-11T00:00:00+00:00")
    payload = credentials(first, second)
    listed = client.post("/api/v1/tailor-runs/history", json=payload)
    assert listed.status_code == 200
    assert [item["company"] for item in listed.json()["items"]] == ["Beta", "Alpha"]
    assert first.access_token not in listed.text
    assert "access_token" not in listed.text
    assert [item["company"] for item in client.post("/api/v1/tailor-runs/history", json={**payload, "sort": "oldest"}).json()["items"]] == ["Alpha", "Beta"]
    assert len(client.post("/api/v1/tailor-runs/history", json={**payload, "search": "alpha"}).json()["items"]) == 1
    assert len(client.post("/api/v1/tailor-runs/history", json={**payload, "search": "SQL"}).json()["items"]) == 2
    assert client.post("/api/v1/tailor-runs/history", json={**payload, "status": "failed"}).json()["items"] == []
    response = client.patch(f"/api/v1/tailor-runs/{first.run_id}/metadata", headers=headers(first),
                            json={"company": "新公司", "job_title": "岗位投递版", "archived": True})
    assert response.status_code == 200
    reset_run_store_cache()
    active = client.post("/api/v1/tailor-runs/history", json=payload).json()["items"]
    assert len(active) == 1
    archived = client.post("/api/v1/tailor-runs/history", json={**payload, "archive_filter": "archived"}).json()["items"]
    assert archived[0]["job_title"] == "岗位投递版"
    assert archived[0]["company"] == "新公司"
    assert archived[0]["jd_text"] == first.jd_text
    assert get_run_store().get(first.run_id).result == first.result


def test_profile_credential_recovers_its_history_and_authorizes_existing_edit_and_delete_routes():
    client = TestClient(create_app())
    owner = archive()
    other = archive()
    job, _ = completed_run(archive_id=owner.id)
    foreign, _ = completed_run(archive_id=other.id)
    payload = {"archives": [{"id": owner.id, "token": owner.access_token}]}
    history = client.post("/api/v1/tailor-runs/history", json=payload).json()
    assert [item["run_id"] for item in history["items"]] == [job.run_id]
    owner_headers = {"X-Run-Token": owner.access_token}
    assert client.get(f"/api/v1/tailor-runs/{job.run_id}/status", headers=owner_headers).status_code == 200
    assert client.get(f"/api/v1/tailor-runs/{foreign.run_id}/status", headers=owner_headers).status_code == 404
    saved = client.put(f"/api/v1/tailor-runs/{job.run_id}/draft", headers=owner_headers,
                       json={"draft": job.result.final_package.draft.model_dump(mode="json"), "label": "档案恢复后保存"})
    assert saved.status_code == 200
    assert client.delete(f"/api/v1/tailor-runs/{foreign.run_id}", headers=owner_headers).status_code == 404
    assert client.delete(f"/api/v1/tailor-runs/{job.run_id}", headers=owner_headers).status_code == 204
    assert client.post("/api/v1/tailor-runs/history", json=payload).json()["items"] == []


def test_deleted_profile_revokes_profile_access_but_original_task_token_still_works():
    client = TestClient(create_app())
    owner = archive()
    job, _ = completed_run(archive_id=owner.id)
    assert get_candidate_archive_store().delete_authorized(owner.id, owner.access_token)
    path = f"/api/v1/tailor-runs/{job.run_id}/status"
    assert client.get(path, headers={"X-Run-Token": owner.access_token}).status_code == 404
    assert client.get(path, headers=headers(job)).status_code == 200


def test_foreign_or_expired_tasks_are_not_returned_and_archiving_does_not_extend_retention():
    client = TestClient(create_app())
    owner = archive()
    job, _ = completed_run(archive_id=owner.id)
    payload = {"runs": [{"id": job.run_id, "token": "wrong-token"}]}
    response = client.post("/api/v1/tailor-runs/history", json=payload).json()
    assert response["items"] == []
    assert response["unavailable_run_ids"] == [job.run_id]
    assert client.post("/api/v1/tailor-runs/history", json={}).json()["items"] == []
    assert client.patch(f"/api/v1/tailor-runs/{job.run_id}/metadata", headers=headers(job), json={"archived": True}).status_code == 200
    assert get_run_store().get(job.run_id).expires_at == job.expires_at
    get_run_store().update(job.run_id, expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    payload = {**credentials(job), "archives": [{"id": owner.id, "token": owner.access_token}], "archive_filter": "all"}
    assert client.post("/api/v1/tailor-runs/history", json=payload).json()["items"] == []


def test_version_copy_rename_archive_restore_and_delete_preserve_the_correct_active_draft():
    client = TestClient(create_app())
    job, _ = completed_run()
    original = job.result.draft_versions[0]
    path = f"/api/v1/tailor-runs/{job.run_id}/draft-versions/{original.id}"
    assert client.delete(path, headers=headers(job)).status_code == 409
    assert client.patch(path, headers=headers(job), json={"archived": True}).status_code == 409
    assert client.patch(path, headers=headers(job), json={"label": " "}).status_code == 422
    copied = client.post(path + "/copy", headers=headers(job)).json()
    copy = copied["versions"][-1]
    assert copy["id"] != original.id
    assert copy["source"] == "copied"
    assert copy["draft"] == original.draft.model_dump(mode="json")
    assert copied["active_version_id"] == original.id
    copy_path = f"/api/v1/tailor-runs/{job.run_id}/draft-versions/{copy['id']}"
    renamed = client.patch(copy_path, headers=headers(job), json={"label": "备用投递版", "archived": True})
    assert renamed.status_code == 200
    assert renamed.json()["versions"][-1]["archived"] is True
    restored = client.post(copy_path + "/restore", headers=headers(job))
    assert restored.status_code == 200
    assert restored.json()["version"]["archived"] is False
    reset_run_store_cache()
    current = get_run_store().get(job.run_id)
    assert current.result.active_version_id == copy["id"]
    assert current.result.final_package.draft == original.draft
    assert client.delete(path, headers=headers(job)).status_code == 204
    assert client.post(path + "/restore", headers=headers(job)).status_code == 404
    assert len(get_run_store().get(job.run_id).result.draft_versions) == 1


def test_restoring_older_version_persists_its_draft_and_keeps_later_versions():
    client = TestClient(create_app())
    job, _ = completed_run()
    original = job.result.draft_versions[0]
    draft = job.result.final_package.draft.model_copy(deep=True)
    draft.summary = "修改后的摘要"
    response = client.put(f"/api/v1/tailor-runs/{job.run_id}/draft", headers=headers(job),
                          json={"draft": draft.model_dump(mode="json"), "label": "改进版"})
    newer_id = response.json()["version"]["id"]
    assert get_run_store().get(job.run_id).result.active_version_id == newer_id
    response = client.post(f"/api/v1/tailor-runs/{job.run_id}/draft-versions/{original.id}/restore", headers=headers(job))
    assert response.status_code == 200
    reset_run_store_cache()
    current = get_run_store().get(job.run_id).result
    assert current.final_package.draft == original.draft
    assert current.active_version_id == original.id
    assert any(version.id == newer_id for version in current.draft_versions)


@pytest.mark.parametrize("operation", ["rename", "copy", "archive", "restore", "delete"])
def test_every_version_mutation_requires_the_correct_task_credential(operation):
    client = TestClient(create_app())
    job, _ = completed_run()
    version = job.result.draft_versions[0]
    path = f"/api/v1/tailor-runs/{job.run_id}/draft-versions/{version.id}"
    if operation == "rename":
        response = client.patch(path, json={"label": "无权修改"})
    elif operation == "archive":
        response = client.patch(path, json={"archived": True})
    elif operation == "delete":
        response = client.delete(path)
    else:
        response = client.post(path + "/" + operation)
    assert response.status_code == 404
    assert get_run_store().get(job.run_id).result == job.result


def test_comparison_reads_canonical_versions_and_checks_both_tasks():
    client = TestClient(create_app())
    first, _ = completed_run(role="产品经理")
    second, _ = completed_run(role="数据分析师")
    draft = second.result.final_package.draft.model_copy(deep=True)
    draft.summary = "针对新岗位的摘要"
    draft.project_section = []
    saved = client.put(f"/api/v1/tailor-runs/{second.run_id}/draft", headers=headers(second), json={"draft": draft.model_dump(mode="json")}).json()
    before = {"run_id": first.run_id, "version_id": first.result.active_version_id, "access_token": first.access_token}
    after = {"run_id": second.run_id, "version_id": saved["version"]["id"], "access_token": second.access_token}
    response = client.post("/api/v1/tailor-runs/version-comparison", json={"before": before, "after": after})
    assert response.status_code == 200
    diffs = response.json()["differences"]
    assert any(item["field"] == "summary" and item["after_text"] == "针对新岗位的摘要" for item in diffs)
    assert any(item["field"] == "project_section.0" and item["change_type"] == "removed" for item in diffs)
    assert first.access_token not in response.text
    assert client.post("/api/v1/tailor-runs/version-comparison", json={"before": before, "after": {**after, "access_token": first.access_token}}).status_code == 404
    assert client.post("/api/v1/tailor-runs/version-comparison", json={"before": before, "after": before}).json()["differences"] == []


def test_completed_runs_keep_each_generated_iteration_and_migrate_legacy_active_version():
    store = get_run_store()
    job, payload = completed_run()
    result = run_tailor_pipeline(payload, run_id=job.run_id)
    second = result.drafts[-1].model_copy(deep=True)
    second.summary = "第二轮摘要"
    result.drafts.append(second)
    result.reviews.append(result.reviews[-1].model_copy(deep=True))
    result.final_package.draft = second
    completed = store.mark_completed(job.run_id, result, "完成")
    assert [version.label for version in completed.result.draft_versions] == ["AI 第 1 轮", "AI 第 2 轮"]
    assert completed.result.active_version_id == completed.result.draft_versions[-1].id
    persisted = json.loads(store._path.read_text())
    persisted["jobs"][job.run_id]["result"].pop("active_version_id")
    store._path.write_text(json.dumps(persisted))
    reset_run_store_cache()
    assert get_run_store().get(job.run_id).result.active_version_id == completed.result.draft_versions[-1].id


def test_history_recovers_the_original_jd_from_legacy_queue_payload():
    client = TestClient(create_app())
    job, payload = completed_run()
    get_task_queue().enqueue(job.run_id, payload, "legacy-job", job.expires_at)
    get_run_store().update(job.run_id, jd_text="")
    listed = client.post("/api/v1/tailor-runs/history", json=credentials(job)).json()
    assert listed["items"][0]["jd_text"] == payload.jd_text
    assert client.get(f"/api/v1/tailor-runs/{job.run_id}/status", headers=headers(job)).json()["jd_text"] == payload.jd_text
