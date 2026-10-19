from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
from zipfile import ZipFile

from fastapi.testclient import TestClient
import pytest

from backend.app.agents.materials import MaterialsAgent, collect_evidence
from backend.app.core.config import reset_settings_cache
from backend.app.main import create_app
from backend.app.schemas.common import FactCard, TraceabilityRecord
from backend.app.schemas.material import MaterialPlan
from backend.app.schemas.strategy import ResumeSectionItem
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.materials import MaterialStore, get_material_store
from backend.app.services.runs.store import get_run_store
from backend.tests.test_draft_editing import _completed_run


def materials(client, language="zh"):
    job = _completed_run()
    result = job.result.model_copy(deep=True)
    result.resolved_language = language
    result.fact_cards = [
        FactCard(id="f1", category="project_bullet", text="参与 SQL 分析增长实验，转化率提升20%。" if language == "zh" else "Participated in SQL analysis; conversion improved by 20%.", confirmed=True),
        FactCard(id="f2", category="project_bullet", text="协助核对实验记录。" if language == "zh" else "Assisted in checking experiment records.", confirmed=True),
        FactCard(id="f3", category="project_bullet", text="使用 Python 整理报表。" if language == "zh" else "Used Python to organize reports.", confirmed=True),
        FactCard(id="unconfirmed", category="project_bullet", text="独立负责 Kafka 项目，收入提升90%。", confirmed=False),
    ]
    draft = result.draft_versions[0].draft
    draft.project_section = [ResumeSectionItem(heading="增长实验", bullets=[item.text for item in result.fact_cards[:2]]),
        ResumeSectionItem(heading="报表", bullets=[result.fact_cards[2].text, result.fact_cards[3].text])]
    draft.traceability = [TraceabilityRecord(draft_span="project_section.1.bullets.1", fact_ids=["f1"]),
        TraceabilityRecord(draft_span="project_section.1.bullets.2", fact_ids=["f2"]),
        TraceabilityRecord(draft_span="project_section.2.bullets.1", fact_ids=["f3"]),
        TraceabilityRecord(draft_span="project_section.2.bullets.2", fact_ids=["unconfirmed"])]
    result.final_package.draft = draft.model_copy(deep=True)
    get_run_store().update(job.run_id, result=result, target_company="示例公司", target_job_title="产品经理", jd_text="产品经理\n要求 SQL；Kafka 为加分项。")
    path = f"/api/v1/tailor-runs/{job.run_id}/materials"
    headers = {"X-Run-Token": job.access_token}
    response = client.post(path, headers=headers, json={"version_id": draft_id(result)})
    assert response.status_code == 201, response.text
    return path, headers, response.json(), job


def draft_id(result):
    return result.draft_versions[0].id


def save(client, path, headers, pack, document_id="cover_letter", content=None, reviewed=True):
    doc = next(item for item in pack["documents"] if item["id"] == document_id)
    return client.put(f'{path}/{pack["id"]}/documents/{document_id}', headers=headers,
        json={"expected_revision":pack["revision"], "content":doc["content"] if content is None else content, "reviewed":reviewed})


@pytest.mark.parametrize("language", ["zh", "en"])
def test_seven_materials_share_confirmed_facts_and_snapshot(language, tmp_path):
    with TestClient(create_app()) as client:
        path, headers, pack, job = materials(client, language)
        assert len(pack["documents"]) == 7 and pack["method"] == "rules"
        assert all(fact["confirmed"] for fact in pack["fact_cards"])
        assert len(pack["evidence"]) == 3
        assert {e["fact_ids"][0] for e in pack["evidence"]} == {"f1", "f2", "f3"}
        content = " ".join(item["content"] for item in pack["documents"])
        assert "90%" not in content and "Kafka" not in content
        introductions = [item for item in pack["documents"] if item["id"].startswith("intro_")]
        assert len(introductions[0]["content"]) < len(introductions[1]["content"]) < len(introductions[2]["content"])
        deep = next(item for item in pack["documents"] if item["id"] == "project_deep_dive")
        groups = {e["group"] for e in pack["evidence"] if e["id"] in deep["evidence_ids"]}
        assert len(groups) == 1 and "project_section.1" in groups
        assert deep["issues"]
        source = get_run_store().get(job.run_id)
        source.result.draft_versions[0].draft.summary = "后续修改"
        source.result.fact_cards[0].text = "后续修改的事实"
        get_run_store().update(job.run_id, result=source.result, jd_text="后续修改 JD")
        assert client.get(f'{path}/{pack["id"]}',headers=headers).json() == pack
        assert MaterialStore(tmp_path / "materials.sqlite3").get(job.run_id,pack["id"]).model_dump(mode="json") == pack


def test_private_access_cross_run_and_bad_version():
    with TestClient(create_app()) as client:
        path, headers, pack, job = materials(client)
        for suffix in ("", f'/{pack["id"]}', f'/{pack["id"]}/export', f'/{pack["id"]}/documents/cover_letter/export'):
            assert client.get(path + suffix).status_code == 404
        other = _completed_run()
        assert client.get(f'/api/v1/tailor-runs/{other.run_id}/materials/{pack["id"]}',headers={"X-Run-Token":other.access_token}).status_code == 404
        assert client.post(path,headers=headers,json={"version_id":"missing"}).status_code == 404
        assert client.delete(f'{path}/{pack["id"]}',headers={"X-Run-Token":"wrong"}).status_code == 404
        listing = client.get(path,headers=headers).json()
        assert listing[0]["id"] == pack["id"] and "draft" not in listing[0]
        assert "access_token" not in json.dumps(pack)


def test_manual_edit_risk_scope_export_review_and_no_fact_mutation():
    with TestClient(create_app()) as client:
        path, headers, pack, job = materials(client)
        before = get_run_store().get(job.run_id).result.model_dump()
        assert client.get(f'{path}/{pack["id"]}/documents/cover_letter/export',headers=headers).status_code == 409
        response = save(client,path,headers,pack,content="我独立完成 Kafka 项目，转化率提升40%。",reviewed=False)
        assert response.status_code == 200
        updated = response.json(); doc = updated["documents"][0]
        assert doc["edited"] and not doc["reviewed"] and doc["evidence_ids"] == pack["documents"][0]["evidence_ids"]
        quotes = {issue["quote"] for issue in doc["issues"]}
        assert {"40%", "Kafka", "独立完成"} <= quotes
        assert all(item == previous for item,previous in zip(updated["documents"][1:],pack["documents"][1:]))
        checked = save(client,path,headers,updated).json()
        export = client.get(f'{path}/{pack["id"]}/documents/cover_letter/export',headers=headers)
        assert export.status_code == 200 and "40%" in export.text and "原引用不证明新增表达" in export.text
        assert pack["version_id"] in export.text and pack["jd_text"] in export.text and "事实 [f1]" in export.text
        assert export.headers["cache-control"] == "no-store"
        assert get_run_store().get(job.run_id).result.model_dump() == before
        assert client.get(f'{path}/{pack["id"]}/export',headers=headers).status_code == 409
        for item in checked["documents"][1:]:
            checked = save(client,path,headers,checked,item["id"]).json()
        archive = client.get(f'{path}/{pack["id"]}/export',headers=headers)
        assert archive.status_code == 200
        with ZipFile(BytesIO(archive.content)) as exported:
            assert len(exported.namelist()) == 8
            for filename in exported.namelist():
                if filename != "README.md":
                    text = exported.read(filename).decode("utf-8")
                    assert pack["version_id"] in text and pack["jd_text"] in text


def test_edit_concurrency_and_repeat_save(tmp_path):
    with TestClient(create_app()) as client:
        path, headers, pack, _ = materials(client)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda text: save(client,path,headers,pack,content=text), ["编辑甲", "编辑乙"]))
        assert sorted(response.status_code for response in responses) == [200,409]
        accepted = next(response.json() for response in responses if response.status_code == 200)
        assert accepted["revision"] == 2
        assert save(client,path,headers,accepted).json() == accepted
        assert save(client,path,headers,pack,content="旧版本").status_code == 409


@pytest.mark.parametrize("invalid", [{"content":" "}, {"content":"x"*16001}, {"expected_revision":0}, {"unknown":"field"}])
def test_invalid_edit_does_not_change_pack(invalid):
    with TestClient(create_app()) as client:
        path, headers, pack, _ = materials(client)
        payload = {"content":"正常内容", "expected_revision":1, "reviewed":False}; payload.update(invalid)
        assert client.put(f'{path}/{pack["id"]}/documents/cover_letter',headers=headers,json=payload).status_code == 422
        assert client.get(f'{path}/{pack["id"]}',headers=headers).json() == pack


def test_deleted_and_expired_run_cascades():
    with TestClient(create_app()) as client:
        path, headers, pack, job = materials(client)
        assert get_run_store().delete_authorized(job.run_id,job.access_token)
        assert get_material_store().get(job.run_id,pack["id"]) is None
        assert client.get(f'{path}/{pack["id"]}',headers=headers).status_code == 404
        _, _, second, job2 = materials(client)
        get_run_store().update(job2.run_id,expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        assert get_run_store().cleanup_expired() == 1
        assert get_material_store().get(job2.run_id,second["id"]) is None


def test_delete_pack_preserves_source_and_other_packs():
    with TestClient(create_app()) as client:
        path, headers, pack, job = materials(client)
        other = client.post(path,headers=headers,json={"version_id":pack["version_id"]}).json()
        assert client.delete(f'{path}/{pack["id"]}',headers=headers).status_code == 204
        assert get_run_store().get(job.run_id)
        assert client.get(f'{path}/{other["id"]}',headers=headers).status_code == 200


def test_evidence_rejects_changed_metrics_and_unconfirmed_trace():
    with TestClient(create_app()) as client:
        _, _, pack, _ = materials(client)
        saved = get_material_store().get(pack["run_id"],pack["id"])
        saved.draft.project_section[0].bullets[0] = "独立完成 SQL 分析，转化率提升40%。"
        evidence = collect_evidence(saved.draft,saved.fact_cards)
        assert all("f1" not in item.fact_ids for item in evidence)
        saved.draft.traceability[1].fact_ids = ["invented"]
        assert all("f2" not in item.fact_ids for item in collect_evidence(saved.draft,saved.fact_cards))


def test_model_can_only_select_known_evidence_and_one_project():
    with TestClient(create_app()) as client:
        _, _, pack, _ = materials(client)
        saved = get_material_store().get(pack["run_id"],pack["id"])
        class FakeModel:
            is_available = True
            def generate(self, **kwargs):
                assert kwargs["agent_name"] == "materials"
                assert kwargs["context"]["saved_resume"] == saved.draft
                assert kwargs["context"]["jd_profile"] == saved.jd_profile
                assert len(kwargs["context"]["evidence"]) == 3
                return MaterialPlan(selections={"cover_letter":["invented"],"intro_short":["e3","e1"],
                    "project_deep_dive":["e1","e3","e2"], "hr_followup":["e1"]})
        plan, method = MaterialsAgent(FakeModel()).select(saved.evidence,saved.draft,saved.jd_profile,saved.language)
        assert method == "model_selection" and plan.selections["intro_short"] == ["e3"]
        assert "invented" not in plan.selections["cover_letter"]
        assert plan.selections["project_deep_dive"] == ["e1","e2"]
        assert plan.selections["hr_followup"] == []


def test_model_failure_and_delete_during_generation_never_save(monkeypatch):
    with TestClient(create_app()) as client:
        path, headers, pack, job = materials(client)
        def fail(*args):
            raise StructuredLLMError("private provider detail")
        monkeypatch.setattr(MaterialsAgent,"select",fail)
        assert client.post(path,headers=headers,json={"version_id":pack["version_id"]}).status_code == 503
        assert len(client.get(path,headers=headers).json()) == 1
        def deleted(self, evidence, draft, jd, language):
            get_run_store().delete_authorized(job.run_id,job.access_token)
            return MaterialPlan(selections={kind:[] for kind in [item["id"] for item in pack["documents"]]}), "rules"
        monkeypatch.setattr(MaterialsAgent,"select",deleted)
        assert client.post(path,headers=headers,json={"version_id":pack["version_id"]}).status_code == 404
        assert get_material_store().list(job.run_id) == []


def test_empty_fact_sources_keep_framework_without_inventing(monkeypatch):
    with TestClient(create_app()) as client:
        path, headers, pack, job = materials(client)
        source = get_run_store().get(job.run_id); source.result.fact_cards = []
        get_run_store().update(job.run_id,result=source.result)
        empty = client.post(path,headers=headers,json={"version_id":pack["version_id"]}).json()
        assert empty["evidence"] == []
        assert any("没有可追溯" in note for note in empty["notes"])
        assert all("20%" not in item["content"] for item in empty["documents"])
        assert "没有可追溯" in next(item for item in empty["documents"] if item["id"] == "project_deep_dive")["content"]


def test_strict_no_provider_does_not_generate_a_new_pack(monkeypatch):
    with TestClient(create_app()) as client:
        path, headers, pack, _ = materials(client)
        monkeypatch.setenv("LLM_STRICT_MODE", "true"); reset_settings_cache()
        response = client.post(path,headers=headers,json={"version_id":pack["version_id"]})
        assert response.status_code == 503 and "private" not in response.text
        assert len(client.get(path,headers=headers).json()) == 1


def test_pack_limit_before_model_call_and_generation_rate_limit(monkeypatch):
    with TestClient(create_app()) as client:
        path, headers, pack, job = materials(client)
        existing = get_material_store().get(job.run_id,pack["id"])
        for index in range(19):
            get_material_store().create(existing.model_copy(update={"id":f"copy-{index}"}))
        def forbidden(*args):
            raise AssertionError("Limit should be checked before the model")
        monkeypatch.setattr(MaterialsAgent,"select",forbidden)
        assert client.post(path,headers=headers,json={"version_id":pack["version_id"]}).status_code == 409
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1"); reset_settings_cache()
    with TestClient(create_app()) as client:
        payload = {"version_id":pack["version_id"]}
        assert client.post(path,headers=headers,json=payload).status_code == 409
        response = client.post(path,headers=headers,json=payload)
        assert response.status_code == 429 and response.headers.get("retry-after")




def test_confirmed_profile_pipeline_supplies_traceable_material_evidence():
    from backend.tests.test_candidate_profiles import save_archive, wait_for_run
    with TestClient(create_app()) as client:
        archive, profile_headers = save_archive(client)
        response = client.post(f'/api/v1/candidate-profiles/{archive["id"]}/jobs',headers=profile_headers,json={
            "expected_revision":archive["revision"],"jd_text":"2026 校招产品经理\nSQL 数据分析","max_iterations":1})
        job = response.json(); ready = wait_for_run(client,job)
        path = f'/api/v1/tailor-runs/{job["run_id"]}/materials'
        pack_response = client.post(path,headers={"X-Run-Token":archive["access_token"]},json={"version_id":ready["result"]["active_version_id"]})
        assert pack_response.status_code == 201, pack_response.text
        pack = pack_response.json()
        assert any(item["text"] == "使用 SQL 分析增长实验" for item in pack["evidence"])
        assert "使用 SQL 分析增长实验" in pack["documents"][0]["content"]
        assert client.get(path,headers={"X-Run-Token":archive["access_token"]}).status_code == 200
