import json
import sqlite3
import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from backend.app.main import create_app
from backend.app.core.config import reset_settings_cache
from backend.app.services.profiles import CandidateArchiveStore
from backend.app.services.runs.store import get_run_store


def confirmed_material():
    return {
        "label": "张三的基础档案", "confirmed": True, "storage_consent": True,
        "candidate_profile": {
            "basics": {"name": "张三", "email": "candidate@example.com"},
            "projects": [{"id": "project-1", "name": "增长分析", "bullets": ["过时的描述"]}],
            "skills": {"hard_skills": ["SQL"]},
        },
        "fact_cards": [
            {"id": "fact-project", "category": "project_bullet", "text": "使用 SQL 分析增长实验",
             "source_span": "projects.project-1.bullets.0", "source_excerpt": "使用 SQL 分析增长实验", "confirmed": True},
            {"id": "fact-skill", "category": "skill", "text": "SQL", "confirmed": True},
        ],
    }


def save_archive(client):
    response = client.post("/api/v1/candidate-profiles", json=confirmed_material())
    assert response.status_code == 201, response.text
    archive = response.json()
    return archive, {"X-Profile-Token": archive["access_token"]}


def wait_for_run(client, job):
    headers = {"X-Run-Token": job["access_token"]}
    for _ in range(80):
        response = client.get(f'/api/v1/tailor-runs/{job["run_id"]}/status', headers=headers)
        assert response.status_code == 200
        result = response.json()
        if result["status"] == "completed":
            return result
        assert result["status"] in {"queued", "running"}, result
        time.sleep(0.025)
    raise AssertionError("Profile run did not finish")


def test_saved_archive_is_normalized_persistent_and_exports_without_credentials(tmp_path):
    client = TestClient(create_app())
    archive, headers = save_archive(client)
    assert archive["revision"] == 1
    assert archive["candidate_profile"]["projects"][0]["bullets"] == ["使用 SQL 分析增长实验"]
    path = tmp_path / "candidate_archives.sqlite3"
    reloaded = CandidateArchiveStore(str(path)).get_authorized(archive["id"], archive["access_token"])
    assert reloaded.candidate_profile.basics.name == "张三"
    assert reloaded.access_token is None
    with sqlite3.connect(path) as connection:
        stored = connection.execute("SELECT token_hash, archive_json FROM candidate_archives").fetchone()
    assert archive["access_token"] not in " ".join(stored)
    response = client.get(f'/api/v1/candidate-profiles/{archive["id"]}/export', headers=headers)
    assert response.status_code == 200
    assert "access_token" not in response.json()
    assert response.json()["fact_cards"][0]["source_excerpt"] == "使用 SQL 分析增长实验"


def test_unified_skills_preserve_categories_and_apply_removals():
    client = TestClient(create_app())
    material = confirmed_material()
    material["candidate_profile"]["skills"] = {
        "hard_skills": ["SQL", "A/B Testing"],
        "tools": ["Power BI", "CI/CD"],
        "soft_skills": ["跨团队协作"],
        "languages": ["英语", "日语"],
    }
    retained = ["SQL", "Power BI", "CI/CD", "跨团队协作", "英语", "Python", "sql"]
    material["fact_cards"] = material["fact_cards"][:1] + [
        {"id": f"skill-{index}", "category": "skill", "text": text,
         "source_span": "skills", "confirmed": True}
        for index, text in enumerate(retained)
    ]
    response = client.post("/api/v1/candidate-profiles", json=material)
    assert response.status_code == 201, response.text
    assert response.json()["candidate_profile"]["skills"] == {
        "hard_skills": ["SQL", "Python"],
        "tools": ["Power BI", "CI/CD"],
        "soft_skills": ["跨团队协作"],
        "languages": ["英语"],
    }


@pytest.mark.parametrize("invalid", ["unconfirmed", "no_consent", "empty_fact", "duplicate_id", "blank_label", "no_profile_confirmation"])
def test_archive_rejects_unconfirmed_or_invalid_material(invalid):
    client = TestClient(create_app())
    payload = confirmed_material()
    if invalid == "unconfirmed":
        payload["fact_cards"][0]["confirmed"] = False
    elif invalid == "no_consent":
        payload["storage_consent"] = False
    elif invalid == "empty_fact":
        payload["fact_cards"][0]["text"] = " "
    elif invalid == "duplicate_id":
        payload["fact_cards"][1]["id"] = payload["fact_cards"][0]["id"]
    elif invalid == "blank_label":
        payload["label"] = " "
    else:
        payload["confirmed"] = False
    assert client.post("/api/v1/candidate-profiles", json=payload).status_code == 422


def test_all_profile_endpoints_require_the_matching_owner_credential():
    client = TestClient(create_app())
    archive, _ = save_archive(client)
    other, _ = save_archive(client)
    path = f'/api/v1/candidate-profiles/{archive["id"]}'
    for headers in ({}, {"X-Profile-Token": other["access_token"]}):
        assert client.get(path, headers=headers).status_code == 404
        assert client.get(path + "/export", headers=headers).status_code == 404
        assert client.get(path + "/usage", headers=headers).status_code == 404
        payload = {**confirmed_material(), "expected_revision": 1}
        assert client.put(path, json=payload, headers=headers).status_code == 404
        job = {"jd_text": "产品经理 SQL", "expected_revision": 1}
        assert client.post(path + "/preview", json=job, headers=headers).status_code == 404
        assert client.post(path + "/jobs", json=job, headers=headers).status_code == 404
        assert client.delete(path, headers=headers).status_code == 404


def test_archive_reuse_skips_resume_parsing_and_preserves_old_facts_after_update_and_delete(monkeypatch):
    client = TestClient(create_app())
    archive, headers = save_archive(client)
    path = f'/api/v1/candidate-profiles/{archive["id"]}'

    def reject_reparse(*args, **kwargs):
        raise AssertionError("Reusing an archive must not parse a resume again")

    monkeypatch.setattr("backend.app.agents.resume_parser.ResumeParserAgent.run", reject_reparse)
    job_request = {"jd_text": "校招产品经理\n要求：SQL，数据分析", "expected_revision": 1, "max_iterations": 1}
    preview = client.post(path + "/preview", json=job_request, headers=headers)
    assert preview.status_code == 200
    assert preview.json()["fact_cards"][0]["confirmed"] is True
    assert preview.json()["follow_up_questions"]
    assert preview.json()["jd_profile"]["job_title"]
    first_response = client.post(path + "/jobs", json=job_request, headers=headers)
    assert first_response.status_code == 200, first_response.text
    first_job = first_response.json()
    first = wait_for_run(client, first_job)
    assert first["candidate_archive_id"] == archive["id"]
    assert first["candidate_archive_revision"] == 1

    updated = confirmed_material()
    updated["expected_revision"] = 1
    updated["fact_cards"][0]["text"] = "使用 SQL 分析增长实验，效率提升 20%"
    response = client.put(path, json=updated, headers=headers)
    assert response.status_code == 200
    assert response.json()["revision"] == 2
    usage = client.get(path + "/usage", headers=headers).json()
    assert usage["runs"][0]["affected"] is True
    assert "access_token" not in json.dumps(usage)
    assert client.post(path + "/jobs", json=job_request, headers=headers).status_code == 409
    job_request.update(jd_text="数据分析师\n要求：SQL，数据分析", expected_revision=2)
    second_response = client.post(path + "/jobs", json=job_request, headers=headers)
    assert second_response.status_code == 200
    second = wait_for_run(client, second_response.json())
    assert second["result"]["fact_cards"][0]["text"] == updated["fact_cards"][0]["text"]
    usage = client.get(path + "/usage", headers=headers).json()
    assert sorted(run["affected"] for run in usage["runs"]) == [False, True]
    assert client.delete(path, headers=headers).status_code == 204
    assert client.get(path, headers=headers).status_code == 404
    assert client.get(path + "/export", headers=headers).status_code == 404
    assert client.get(path + "/usage", headers=headers).status_code == 404
    old = client.get(f'/api/v1/tailor-runs/{first_job["run_id"]}/status', headers={"X-Run-Token": first_job["access_token"]}).json()
    assert old["result"] == first["result"]
    assert old["result"]["fact_cards"][0]["text"] == "使用 SQL 分析增长实验"


def test_revision_conflict_and_identical_save_do_not_invalidate_old_versions():
    client = TestClient(create_app())
    archive, headers = save_archive(client)
    path = f'/api/v1/candidate-profiles/{archive["id"]}'
    payload = {**confirmed_material(), "expected_revision": 1}
    payload["label"] = "重命名档案"
    assert client.put(path, json=payload, headers=headers).json()["revision"] == 1
    payload["candidate_profile"]["basics"]["name"] = "李四"
    assert client.put(path, json=payload, headers=headers).json()["revision"] == 2
    payload["candidate_profile"]["basics"]["name"] = "错误覆盖"
    assert client.put(path, json=payload, headers=headers).status_code == 409
    current = client.get(path, headers=headers).json()
    assert current["candidate_profile"]["basics"]["name"] == "李四"
    assert current["access_token"] is None


def test_deleted_runs_no_longer_appear_in_archive_usage():
    client = TestClient(create_app())
    archive, headers = save_archive(client)
    path = f'/api/v1/candidate-profiles/{archive["id"]}'
    response = client.post(path + "/jobs", json={"jd_text": "产品经理 SQL", "expected_revision": 1}, headers=headers)
    job = response.json()
    wait_for_run(client, job)
    assert len(client.get(path + "/usage", headers=headers).json()["runs"]) == 1
    assert client.delete(f'/api/v1/tailor-runs/{job["run_id"]}', headers={"X-Run-Token": job["access_token"]}).status_code == 204
    assert client.get(path + "/usage", headers=headers).json()["runs"] == []
    assert client.get(path, headers=headers).status_code == 200


def test_expiring_a_task_does_not_expire_its_explicitly_saved_archive():
    client = TestClient(create_app())
    archive, headers = save_archive(client)
    store = get_run_store()
    job = store.create("测试过期任务")
    store.update(job.run_id, candidate_archive_id=archive["id"], candidate_archive_revision=1,
                 expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    path = f'/api/v1/candidate-profiles/{archive["id"]}'
    assert client.get(path + "/usage", headers=headers).json()["runs"] == []
    assert client.get(path, headers=headers).status_code == 200
    assert store.get(job.run_id) is None


def test_profile_job_idempotency_is_scoped_to_each_private_archive():
    client = TestClient(create_app())
    first, first_headers = save_archive(client)
    second, second_headers = save_archive(client)
    first_headers["Idempotency-Key"] = "same-browser-key"
    second_headers["Idempotency-Key"] = "same-browser-key"
    payload = {"jd_text": "产品经理 SQL", "expected_revision": 1}
    path = f'/api/v1/candidate-profiles/{first["id"]}/jobs'
    first_job = client.post(path, json=payload, headers=first_headers)
    assert first_job.status_code == 200
    assert client.post(path, json=payload, headers=first_headers).status_code == 409
    second_job = client.post(f'/api/v1/candidate-profiles/{second["id"]}/jobs', json=payload, headers=second_headers)
    assert second_job.status_code == 200
    assert second_job.json()["run_id"] != first_job.json()["run_id"]
    wait_for_run(client, first_job.json())
    wait_for_run(client, second_job.json())


def test_profile_creation_and_jd_preview_share_the_expensive_request_limit(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1")
    reset_settings_cache()
    client = TestClient(create_app())
    archive, headers = save_archive(client)
    response = client.post(f'/api/v1/candidate-profiles/{archive["id"]}/preview',
                           json={"jd_text": "SQL 产品经理", "expected_revision": 1}, headers=headers)
    assert response.status_code == 429
    assert int(response.headers["retry-after"]) >= 1
