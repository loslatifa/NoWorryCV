from fastapi.testclient import TestClient

from backend.app.graph.resume_tailor_graph import run_tailor_pipeline
from backend.app.main import create_app
from backend.app.schemas.run_state import TailorRunInput
from backend.app.services.draft_editing import normalize_manual_draft
from backend.app.services.runs.store import get_run_store


def _completed_run():
    store = get_run_store()
    job = store.create("任务已创建。")
    result = run_tailor_pipeline(
        TailorRunInput(
            resume_text=(
                "张三\n\n项目经历\n增长实验项目\n- 使用 SQL 复盘实验结果\n\n技能\nPython, SQL"
            ),
            jd_text="2026 校招产品经理\n要求：SQL，数据分析",
            output_language="zh",
            max_iterations=1,
            processing_mode="fast",
        ),
        run_id=job.run_id,
    )
    completed = store.mark_completed(job.run_id, result, "简历定制完成。")
    return completed.model_copy(update={"access_token": job.access_token}, deep=True)


def test_manual_edit_invalidates_changed_bullet_traceability() -> None:
    completed = _completed_run()
    previous = completed.result.final_package.draft
    edited = previous.model_copy(deep=True)
    edited.project_section[0].bullets[0] = "新增了没有事实依据的项目成果"

    normalized = normalize_manual_draft(previous, edited)

    target_span = "project_section.1.bullets.1"
    assert all(record.draft_span != target_span for record in normalized.traceability)
    assert "新增了没有事实依据的项目成果" in normalized.markdown


def test_draft_save_and_partial_rewrite_create_persistent_versions() -> None:
    completed = _completed_run()
    client = TestClient(create_app())
    run_id = completed.run_id
    headers = {"X-Run-Token": completed.access_token}

    versions_response = client.get("/api/v1/tailor-runs/{0}/draft-versions".format(run_id), headers=headers)
    assert versions_response.status_code == 200
    assert len(versions_response.json()) == 1
    assert versions_response.json()[0]["source"] == "generated"

    draft = completed.result.final_package.draft.model_copy(deep=True)
    draft.project_section[0].bullets[0] = "新增了没有事实依据的项目成果"
    save_response = client.put(
        "/api/v1/tailor-runs/{0}/draft".format(run_id),
        headers=headers,
        json={"draft": draft.model_dump(mode="json"), "label": "我的修改"},
    )

    assert save_response.status_code == 200
    saved = save_response.json()
    assert saved["version"]["source"] == "manual"
    assert saved["version"]["label"] == "我的修改"
    assert saved["version"]["compliance_report"]["risk_level"] == "high"
    assert len(saved["versions"]) == 2

    rewrite_response = client.post(
        "/api/v1/tailor-runs/{0}/rewrite-part".format(run_id),
        headers=headers,
        json={
            "draft": saved["version"]["draft"],
            "target_type": "skills",
            "instruction": "优先展示与 JD 相关的技能",
        },
    )

    assert rewrite_response.status_code == 200
    rewritten = rewrite_response.json()
    assert rewritten["version"]["source"] == "ai_partial"
    assert len(rewritten["versions"]) == 3
    assert rewritten["version"]["draft"]["skills_section"]

    persisted = client.get("/api/v1/tailor-runs/{0}/status".format(run_id), headers=headers).json()
    assert len(persisted["result"]["draft_versions"]) == 3
    assert persisted["result"]["final_package"]["draft"] == rewritten["version"]["draft"]
