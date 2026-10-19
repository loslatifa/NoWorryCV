from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import sqlite3

from fastapi.testclient import TestClient
from pypdf import PdfReader
import pytest

from backend.app.main import create_app
from backend.app.services.positions import PositionStore, get_position_store
from backend.app.services.runs.store import get_run_store
from backend.tests.test_applications import create, ready, approve
from backend.tests.test_candidate_profiles import save_archive, wait_for_run
from backend.tests.test_draft_editing import _completed_run


def setup(client):
    archive, headers = save_archive(client)
    path = f'/api/v1/candidate-profiles/{archive["id"]}/positions'
    response = client.post(path, headers=headers, json={"company":"示例公司", "role":"数据分析实习生",
        "jd_text":"使用 SQL 分析增长实验，开发数据看板，复盘转化率。", "storage_consent":True})
    assert response.status_code == 201, response.text
    return path, headers, archive, response.json()


def generate(client, path, headers, archive, position):
    response = client.post(f'{path}/{position["id"]}/jobs', headers=headers, json={
        "expected_revision":position["revision"], "expected_profile_revision":archive["revision"], "max_iterations":1})
    assert response.status_code == 200, response.text
    data = response.json(); job = data["job"]
    result = wait_for_run(client, job)["result"]
    return data["position"], job, result


def link(client, path, headers, position, job, result):
    response = client.post(f'{path}/{position["id"]}/resumes', headers=headers, json={
        "expected_revision":position["revision"], "run_id":job["run_id"], "version_id":result["active_version_id"], "storage_consent":True})
    assert response.status_code == 200, response.text
    return response.json()


def test_position_status_action_reminders_and_timeline_are_persistent(tmp_path):
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        endpoint = f'{path}/{position["id"]}'
        for status in ["applied", "assessment", "interview", "offer", "closed", "pending"]:
            response = client.patch(endpoint, headers=headers, json={"expected_revision":position["revision"], "status":status,
                "next_action":"核对笔试安排", "remind_at":"2020-01-01T10:00:00+08:00", "note":"本人已检查并更新进度。"})
            assert response.status_code == 200, response.text
            position = response.json()
            assert position["status"] == status
            assert position["timeline"][-1]["changes"]["status"][1] == status
            filtered = client.get(path, headers=headers, params={"reminder":"due"}).json()
            assert len(filtered["items"]) == (0 if status == "closed" else 1)
        assert position["remind_at"] == "2020-01-01T02:00:00+00:00"
        reloaded = PositionStore(str(tmp_path / "positions.sqlite3")).get(archive["id"], position["id"])
        assert reloaded.next_action == "核对笔试安排" and len(reloaded.timeline) == 7
        unchanged = client.patch(endpoint, headers=headers, json={"expected_revision":position["revision"], "status":"pending"}).json()
        assert unchanged["revision"] == position["revision"]
        cleared = client.patch(endpoint, headers=headers, json={"expected_revision":position["revision"], "remind_at":None, "next_action":""}).json()
        assert cleared["remind_at"] is None and cleared["next_action"] == ""


@pytest.mark.parametrize("invalid", [{"company":" "}, {"jd_text":""}, {"job_url":"javascript:alert(1)"}, {"storage_consent":False}, {"unknown":"field"}])
def test_position_create_validation(invalid):
    with TestClient(create_app()) as client:
        path, headers, _, _ = setup(client)
        payload = {"company":"公司", "role":"岗位", "jd_text":"岗位要求", "storage_consent":True, **invalid}
        assert client.post(path, headers=headers, json=payload).status_code == 422


@pytest.mark.parametrize("invalid", [{"remind_at":"2030-01-01T10:00"}, {"status":"filled"}, {"status":None}, {"company":None}, {"next_action":None}])
def test_position_update_requires_valid_status_and_timezone(invalid):
    with TestClient(create_app()) as client:
        path, headers, _, position = setup(client)
        assert client.patch(f'{path}/{position["id"]}', headers=headers, json={"expected_revision":1, **invalid}).status_code == 422


def test_position_ownership_and_concurrent_revision_checks():
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        endpoint = f'{path}/{position["id"]}'
        assert client.get(path).status_code == 404
        other, other_headers = save_archive(client)
        assert client.get(endpoint, headers=other_headers).status_code == 404
        assert client.get(f'/api/v1/candidate-profiles/{other["id"]}/positions/{position["id"]}', headers=other_headers).status_code == 404
        def update(status):
            return client.patch(endpoint, headers=headers, json={"expected_revision":1, "status":status})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(update,["applied","interview"]))
        assert sorted(response.status_code for response in responses) == [200,409]
        assert len(client.get(endpoint,headers=headers).json()["timeline"]) == 2


def test_saved_resume_is_unique_current_and_survives_close_and_source_deletion():
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        position, job, result = generate(client,path,headers,archive,position)
        position = link(client,path,headers,position,job,result)
        first = position["current_resume_id"]
        assert position["status"] == "pending" and len(position["resumes"]) == 1
        assert position["resumes"][0]["jd_text"] == position["jd_text"]
        assert position["resumes"][0]["source_company"] == position["company"]
        repeated = link(client,path,headers,position,job,result)
        assert repeated["revision"] == position["revision"] and len(repeated["resumes"]) == 1
        position = client.patch(f'{path}/{position["id"]}',headers=headers,json={"expected_revision":position["revision"],"jd_text":position["jd_text"]+"\n加分项：Python"}).json()
        position, job2, result2 = generate(client,path,headers,archive,position)
        position = link(client,path,headers,position,job2,result2)
        assert len(position["resumes"]) == 2 and position["current_resume_id"] != first
        selected = client.post(f'{path}/{position["id"]}/resumes/{first}/current', headers=headers,json={"expected_revision":position["revision"]}).json()
        assert selected["current_resume_id"] == first
        position = client.patch(f'{path}/{position["id"]}',headers=headers,json={"expected_revision":selected["revision"],"status":"closed","jd_text":"更新后的岗位要求"}).json()
        assert len(position["resumes"]) == 2
        assert position["resumes"][0]["jd_text"] != position["jd_text"]
        assert get_run_store().delete_authorized(job["run_id"],archive["access_token"])
        pdf = client.get(f'{path}/{position["id"]}/resumes/{first}/pdf',headers=headers)
        assert pdf.status_code == 200 and len(PdfReader(BytesIO(pdf.content)).pages) >= 1
        source = client.get(path+"/sources",headers=headers).json()
        assert all(item["run_id"] != job["run_id"] for item in source["runs"])
        assert "access_token" not in json.dumps(position) and archive["access_token"] not in json.dumps(position)


def test_unconfirmed_or_foreign_material_cannot_be_linked():
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        app_path, application, _ = create(client,archive,headers)
        response = client.post(f'{path}/{position["id"]}/resumes',headers=headers,json={"expected_revision":1,"application_id":application["id"],"storage_consent":True})
        assert response.status_code == 409
        other_path, other_headers, other_archive, other_position = setup(client)
        other_position, job, result = generate(client,other_path,other_headers,other_archive,other_position)
        response = client.post(f'{path}/{position["id"]}/resumes',headers=headers,json={"expected_revision":1,"run_id":job["run_id"],"version_id":result["active_version_id"],"run_token":job["access_token"],"storage_consent":True})
        assert response.status_code == 404
        assert client.post(f'{path}/{position["id"]}/resumes',headers=headers,json={"expected_revision":1,"application_id":application["id"]}).status_code == 422


def test_confirmed_application_snapshot_links_after_run_expiry_without_marking_applied():
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        app_path, application, _ = create(client,archive,headers)
        application = approve(client,app_path,ready(client,app_path,application,headers),headers)
        get_run_store().update(application["run_id"],expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        response = client.post(f'{path}/{position["id"]}/resumes',headers=headers,json={"expected_revision":1,"application_id":application["id"],"storage_consent":True})
        assert response.status_code == 200,response.text
        saved = response.json()
        assert saved["status"] == "pending" and saved["resumes"][0]["version_id"] == application["version_id"]
        assert client.delete(f'{app_path}/{application["id"]}',headers=headers).status_code == 204
        assert client.get(f'{path}/{position["id"]}/resumes/{saved["current_resume_id"]}/pdf',headers=headers).status_code == 200


def test_interview_report_requires_same_version_and_consent_then_survives_expiry():
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        position, job, result = generate(client,path,headers,archive,position)
        position = link(client,path,headers,position,job,result)
        base = f'/api/v1/tailor-runs/{job["run_id"]}/interviews'
        practice = client.post(base,headers={"X-Run-Token":archive["access_token"]},json={"version_id":result["active_version_id"]}).json()
        answer = client.post(f'{base}/{practice["session"]["id"]}/answers',headers={"X-Run-Token":archive["access_token"]},json={"question_id":practice["current_question"]["id"],"expected_revision":1,"answer":"我参与 SQL 分析，并明确解释个人行动和数据口径。"})
        assert answer.status_code == 200,answer.text
        endpoint = f'{path}/{position["id"]}/interviews'
        payload = {"expected_revision":position["revision"],"resume_id":position["current_resume_id"],"session_id":practice["session"]["id"]}
        assert client.post(endpoint,headers=headers,json=payload).status_code == 422
        saved = client.post(endpoint,headers=headers,json={**payload,"storage_consent":True})
        assert saved.status_code == 200,saved.text
        position = saved.json(); report = position["interviews"][0]
        assert "我参与 SQL 分析" in report["report"]
        assert client.post(endpoint,headers=headers,json={**payload,"expected_revision":position["revision"],"storage_consent":True}).json()["revision"] == position["revision"]
        get_run_store().delete_authorized(job["run_id"],archive["access_token"])
        downloaded = client.get(f'{endpoint}/{report["id"]}/report',headers=headers)
        assert downloaded.status_code == 200 and downloaded.text == report["report"]
        assert client.get(f'{path}/{position["id"]}/practice-sources',headers=headers).json() == []


def test_anonymous_owned_version_can_be_linked_with_explicit_run_credential():
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        job = _completed_run()
        payload = {"expected_revision":1,"run_id":job.run_id,"version_id":job.result.active_version_id,"storage_consent":True}
        assert client.post(f'{path}/{position["id"]}/resumes',headers=headers,json=payload).status_code == 404
        saved = client.post(f'{path}/{position["id"]}/resumes',headers=headers,json={**payload,"run_token":job.access_token})
        assert saved.status_code == 200,saved.text
        assert job.access_token not in saved.text


def test_deleting_position_preserves_source_material_and_profile_deletion_cleans_board(tmp_path):
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        position, job, result = generate(client,path,headers,archive,position)
        position = link(client,path,headers,position,job,result)
        assert client.delete(f'{path}/{position["id"]}',headers=headers).status_code == 204
        assert get_run_store().get(job["run_id"]) is not None
        client.post(path,headers=headers,json={"company":"公司","role":"职位","jd_text":"JD","storage_consent":True})
        assert client.delete(f'/api/v1/candidate-profiles/{archive["id"]}',headers=headers).status_code == 204
        with sqlite3.connect(tmp_path/"positions.sqlite3") as connection:
            assert connection.execute("SELECT COUNT(*) FROM positions").fetchone()[0] == 0


def test_generation_conflict_rolls_back_new_task(monkeypatch):
    from backend.app.api.v1 import positions as api
    from backend.app.schemas.position import PositionUpdate
    from backend.app.services.runs.queue import get_task_queue
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        original = api._start_tailor_job
        created = []
        def concurrent_change(*args, **kwargs):
            job = original(*args, **kwargs); created.append(job.run_id)
            get_position_store().update(archive["id"], position["id"], PositionUpdate(expected_revision=1,status="interview"))
            return job
        monkeypatch.setattr(api,"_start_tailor_job",concurrent_change)
        response = client.post(f'{path}/{position["id"]}/jobs',headers=headers,json={"expected_revision":1,"expected_profile_revision":1})
        assert response.status_code == 409
        assert get_run_store().get(created[0]) is None and get_task_queue().metadata(created[0]) is None
        assert client.get(f'{path}/{position["id"]}',headers=headers).json()["status"] == "interview"


def test_anonymous_practice_requires_source_credential_and_matching_version():
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        job = _completed_run()
        response = client.post(f'{path}/{position["id"]}/resumes',headers=headers,json={"expected_revision":1,"run_id":job.run_id,"version_id":job.result.active_version_id,"run_token":job.access_token,"storage_consent":True})
        position=response.json()
        base=f'/api/v1/tailor-runs/{job.run_id}/interviews'
        practice=client.post(base,headers={"X-Run-Token":job.access_token},json={"version_id":job.result.active_version_id}).json()
        client.post(f'{base}/{practice["session"]["id"]}/answers',headers={"X-Run-Token":job.access_token},json={"question_id":practice["current_question"]["id"],"expected_revision":1,"answer":"我使用 SQL 复盘实验，并说清个人行动与结果口径。"})
        source=f'{path}/{position["id"]}/practice-sources'
        assert client.get(source,headers=headers).json() == []
        candidates=client.post(source,headers=headers,json={"runs":[{"id":job.run_id,"token":job.access_token}]}).json()
        assert candidates[0]["session"]["id"] == practice["session"]["id"]
        payload={"expected_revision":position["revision"],"resume_id":position["current_resume_id"],"session_id":practice["session"]["id"],"storage_consent":True}
        assert client.post(f'{path}/{position["id"]}/interviews',headers=headers,json=payload).status_code == 404
        assert client.post(f'{path}/{position["id"]}/interviews',headers=headers,json={**payload,"run_token":job.access_token}).status_code == 200


def test_preparation_documents_are_only_associated_with_the_original_final_version():
    from uuid import uuid4
    with TestClient(create_app()) as client:
        path, headers, archive, position = setup(client)
        position, job, result = generate(client,path,headers,archive,position)
        stored = get_run_store().get(job["run_id"]).result.model_copy(deep=True)
        final_version = stored.draft_versions[-1].model_copy(deep=True)
        final_version.id = str(uuid4()); final_version.label = "末轮版本"
        stored.draft_versions.append(final_version)
        # Restoring an earlier generated version does not regenerate study documents.
        stored.active_version_id = stored.draft_versions[0].id
        get_run_store().update(job["run_id"],result=stored)
        linked = link(client,path,headers,position,job,{"active_version_id":stored.active_version_id})
        assert linked["resumes"][0]["interview_prep"] == ""
        linked = link(client,path,headers,linked,job,{"active_version_id":final_version.id})
        assert linked["resumes"][-1]["interview_prep"] == stored.final_package.interview_prep_doc.markdown
