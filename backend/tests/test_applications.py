from datetime import datetime, timedelta, timezone
import json
import sqlite3
import time

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard, TraceabilityRecord
from backend.app.schemas.strategy import ResumeDraft, ResumeSectionItem
from backend.app.services.applications import ApplicationStore, build_form_resume
from backend.app.services.applications import get_application_store
from backend.app.services.runs.store import get_run_store


def owner(client):
    response = client.post("/api/v1/candidate-profiles", json={
        "label": "测试档案", "confirmed": True, "storage_consent": True,
        "candidate_profile": {
            "basics": {"name": "李明", "email": "liming@example.com", "phone": "13800000000"},
            "projects": [{"id": "p1", "name": "数据看板", "role": "开发者", "skills_used": ["SQL"]}],
        },
        "fact_cards": [
            {"id": "f1", "category": "project_bullet", "text": "使用 SQL 开发数据看板",
             "source_span": "projects.p1.bullets.0", "confirmed": True},
            {"id": "f2", "category": "skill", "text": "SQL", "confirmed": True},
        ],
    })
    assert response.status_code == 201, response.text
    archive = response.json()
    return archive, {"X-Profile-Token": archive["access_token"]}


def create(client, archive, headers):
    path = f'/api/v1/candidate-profiles/{archive["id"]}/applications'
    payload = {"page_url": "https://jobs.example.com/apply/123", "job_url": "https://jobs.example.com/jobs/123",
               "jd_text": "数据开发实习生\n岗位职责：使用 SQL 开发数据看板，负责数据分析与报表。",
               "expected_revision": 1, "target_company": "测试公司", "target_role": "数据开发实习生"}
    response = client.post(path, json=payload, headers=headers)
    assert response.status_code == 201, response.text
    return path, response.json(), payload


def ready(client, path, record, headers):
    for _ in range(100):
        response = client.get(f'{path}/{record["id"]}', headers=headers)
        assert response.status_code == 200, response.text
        current = response.json()
        if current["status"] == "awaiting_confirmation":
            return current
        assert current["status"] == "generating", current
        time.sleep(0.02)
    raise AssertionError("Application did not finish")


def approve(client, path, record, headers):
    response = client.post(f'{path}/{record["id"]}/confirm', headers=headers, json={
        "draft_digest": record["draft_digest"], "confirmed": True, "storage_consent": True,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_application_flow_is_confirmed_durable_and_independent_of_expired_run(tmp_path, monkeypatch):
    def unwanted(*args, **kwargs):
        raise AssertionError("Application mode must not generate study documents")
    monkeypatch.setattr("backend.app.agents.jd_review_card.JDReviewCardAgent.run", unwanted)
    monkeypatch.setattr("backend.app.agents.jd_review_doc.JDReviewDocAgent.run", unwanted)
    monkeypatch.setattr("backend.app.agents.interview_prep.InterviewPrepAgent.run", unwanted)
    client = TestClient(create_app())
    archive, headers = owner(client)
    path, record, _ = create(client, archive, headers)
    assert client.post(f'{path}/{record["id"]}/fill-report', headers=headers,
                       json={"page_url": record["page_url"], "results": []}).status_code == 409
    record = ready(client, path, record, headers)
    assert record["draft"] and record["draft_digest"] and record["form_resume"]["personal_info"]["name"] == "李明"
    assert get_run_store().get(record["run_id"]).result.jd_profile.job_title.startswith("数据开发")
    assert record["target_role"] == "数据开发实习生"
    assert "access_token" not in json.dumps(record)
    assert client.get(f'{path}/{record["id"]}/resume/pdf', headers=headers).status_code == 409
    assert client.post(f'{path}/{record["id"]}/confirm', headers=headers,
                       json={"draft_digest": record["draft_digest"], "confirmed": True}).status_code == 422
    record = approve(client, path, record, headers)
    first_confirmation = record["confirmed_at"]
    assert approve(client, path, record, headers)["confirmed_at"] == first_confirmation
    report = {"page_url": record["page_url"], "results": [
        {"selector": "#name", "field_label": "姓名", "status": "filled"},
        {"selector": "#salary", "field_label": "期望薪资", "status": "skipped", "reason": "用户未提供"},
    ]}
    response = client.post(f'{path}/{record["id"]}/fill-report', headers=headers, json=report)
    assert response.json()["status"] == "partial"
    report["results"] = report["results"][:1]
    assert client.post(f'{path}/{record["id"]}/fill-report', headers=headers, json=report).json()["status"] == "filled"
    report["page_url"] = "https://jobs.example.com/apply/other"
    assert client.post(f'{path}/{record["id"]}/fill-report', headers=headers, json=report).status_code == 409

    get_run_store().update(record["run_id"], expires_at=(datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat())
    assert get_run_store().get(record["run_id"]) is None
    saved = client.get(f'{path}/{record["id"]}', headers=headers).json()
    assert saved["draft"] == record["draft"] and saved["status"] == "filled"
    reloaded = ApplicationStore(str(tmp_path / "applications.sqlite3")).get(archive["id"], record["id"])
    assert reloaded.confirmed_at == first_confirmation
    assert client.get(f'{path}/{record["id"]}/resume/pdf', headers=headers).content.startswith(b"%PDF")
    assert client.get(f'{path}/{record["id"]}/resume/docx', headers=headers).content.startswith(b"PK")
    with sqlite3.connect(tmp_path / "applications.sqlite3") as connection:
        stored = connection.execute("SELECT record_json FROM applications").fetchone()[0]
    assert archive["access_token"] not in stored
    assert len(client.get(path, headers=headers).json()) == 1
    assert client.delete(f'{path}/{record["id"]}', headers=headers).status_code == 204
    assert client.get(f'{path}/{record["id"]}', headers=headers).status_code == 404


def test_preview_edits_require_fresh_confirmation_and_confirmed_snapshot_is_immutable():
    client = TestClient(create_app())
    archive, headers = owner(client)
    path, record, _ = create(client, archive, headers)
    record = ready(client, path, record, headers)
    edited = {**record["draft"], "summary": "已修改的摘要"}
    response = client.put(f'/api/v1/tailor-runs/{record["run_id"]}/draft',
                          headers={"X-Run-Token": archive["access_token"]}, json={"draft": edited})
    assert response.status_code == 200, response.text
    stale = client.post(f'{path}/{record["id"]}/confirm', headers=headers, json={
        "draft_digest": record["draft_digest"], "confirmed": True, "storage_consent": True})
    assert stale.status_code == 409
    record = client.get(f'{path}/{record["id"]}', headers=headers).json()
    assert "个人摘要" in " ".join(record["risk_notes"])
    record = approve(client, path, record, headers)
    edited["summary"] = "确认后修改生成任务"
    assert client.put(f'/api/v1/tailor-runs/{record["run_id"]}/draft',
                      headers={"X-Run-Token": archive["access_token"]}, json={"draft": edited}).status_code == 200
    assert client.get(f'{path}/{record["id"]}', headers=headers).json()["draft"]["summary"] == "已修改的摘要"


def test_records_are_owner_scoped_and_profile_deletion_cleans_snapshots():
    client = TestClient(create_app())
    archive, headers = owner(client)
    other, other_headers = owner(client)
    path, record, payload = create(client, archive, headers)
    other_path = f'/api/v1/candidate-profiles/{other["id"]}/applications/{record["id"]}'
    for credentials in ({}, other_headers):
        assert client.get(path, headers=credentials).status_code == 404
        assert client.get(f'{path}/{record["id"]}', headers=credentials).status_code == 404
        assert client.post(path, headers=credentials, json=payload).status_code == 404
    assert client.get(other_path, headers=other_headers).status_code == 404
    record = ready(client, path, record, headers)
    approve(client, path, record, headers)
    assert client.delete(f'/api/v1/candidate-profiles/{archive["id"]}', headers=headers).status_code == 204
    assert ApplicationStore(__import__("os").environ["APPLICATION_STORE_PATH"]).list(archive["id"]) == []


def test_mapping_uses_fact_identity_when_rewriting_reorders_experiences():
    candidate = CandidateProfile.model_validate({"work_experiences": [
        {"id": "old", "company": "旧公司", "title": "工程师", "start_date": "2022-01"},
        {"id": "new", "company": "新公司", "title": "工程师", "start_date": "2025-06"},
    ]})
    facts = [FactCard(id="old-f", category="work_bullet", text="开发旧系统", source_span="work_experiences.old.bullets.0"),
             FactCard(id="new-f", category="work_bullet", text="开发新系统", source_span="work_experiences.new.bullets.0")]
    draft = ResumeDraft(experience_section=[ResumeSectionItem(heading="工程师", bullets=["改写后的新系统描述"])],
                        traceability=[TraceabilityRecord(draft_span="experience_section.1.bullets.1", fact_ids=["new-f"])])
    resume, warnings = build_form_resume(candidate, draft, facts)
    assert resume["work_experience"][0]["company"] == "新公司"
    assert resume["work_experience"][0]["start_date"] == "2025-06"
    assert not warnings
    draft.traceability[0].fact_ids.append("old-f")
    resume, warnings = build_form_resume(candidate, draft, facts)
    assert not resume["work_experience"][0]["company"]
    assert warnings


def test_application_rejects_stale_profile_and_short_jd():
    client = TestClient(create_app())
    archive, headers = owner(client)
    path, record, payload = create(client, archive, headers)
    assert client.post(path, json={**payload, "expected_revision": 2}, headers=headers).status_code == 409
    assert client.post(path, json={**payload, "jd_text": " " * 30}, headers=headers).status_code == 422
    ready(client, path, record, headers)


def test_unconfirmed_application_preview_expires_with_its_task():
    client = TestClient(create_app())
    archive, headers = owner(client)
    path, record, _ = create(client, archive, headers)
    record = ready(client, path, record, headers)
    def expire(current):
        current.expires_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    get_application_store().update(archive["id"], record["id"], expire)
    assert client.get(f'{path}/{record["id"]}', headers=headers).status_code == 404
    assert client.get(path, headers=headers).json() == []
