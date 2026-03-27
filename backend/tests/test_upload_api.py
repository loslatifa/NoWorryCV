import time

from fastapi.testclient import TestClient

from backend.app.main import create_app


def test_upload_endpoint_accepts_markdown_resume(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/tailor-runs/upload",
        files={
            "resume_file": (
                "resume.md",
                "# Resume\n\n张三\n\n技能\nPython, SQL".encode("utf-8"),
                "text/markdown",
            )
        },
        data={
            "jd_text": "\u9ad8\u7ea7\u4ea7\u54c1\u7ecf\u7406\n\u8981\u6c42\uff1aSQL\uff0c\u6570\u636e\u5206\u6790",
            "candidate_notes": "\u5e0c\u671b\u5f3a\u8c03\u6570\u636e\u5206\u6790",
            "output_language": "zh",
            "max_iterations": "1",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "completed"
    assert payload["final_package"]["draft"]["markdown"]
    assert payload["final_package"]["jd_review_doc"]["markdown"]
    assert payload["final_package"]["interview_prep_doc"]["markdown"]


def test_async_upload_job_exposes_progress_and_result(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/tailor-runs/upload-jobs",
        files={
            "resume_file": (
                "resume.md",
                "# Resume\n\n张三\n\n项目经历\n增长实验项目\n- 负责 SQL 分析与实验复盘\n\n技能\nPython, SQL".encode("utf-8"),
                "text/markdown",
            )
        },
        data={
            "jd_text": "2026 校招产品经理\n要求：SQL，数据分析，用户研究",
            "candidate_notes": "希望强调项目与学习能力",
            "output_language": "zh",
            "max_iterations": "2",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["run_id"]
    assert payload["current_stage"] == "queued"

    final_payload = None
    saw_review_cards = False
    for _ in range(40):
        status_response = client.get("/api/v1/tailor-runs/{0}/status".format(payload["run_id"]))
        assert status_response.status_code == 200
        job = status_response.json()
        assert job["progress_percent"] >= 0
        if job["review_cards"]:
            saw_review_cards = True
        if job["status"] == "completed":
            final_payload = job
            break
        assert job["status"] in {"queued", "running"}
        time.sleep(0.05)

    assert final_payload is not None
    assert saw_review_cards
    assert final_payload["result"]["status"] == "completed"
    assert final_payload["result"]["jd_profile"]["hiring_track"] == "campus"
    assert final_payload["review_cards"]
    assert final_payload["result"]["jd_profile"]["review_cards"]
    assert final_payload["result"]["final_package"]["jd_review_doc"]["markdown"]
    assert final_payload["result"]["final_package"]["interview_prep_doc"]["markdown"]


def test_upload_endpoint_requires_live_llm_when_strict_mode_enabled(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    monkeypatch.setenv("LLM_STRICT_MODE", "true")
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/tailor-runs/upload",
        files={
            "resume_file": (
                "resume.md",
                "# Resume\n\n张三\n\n技能\nPython, SQL".encode("utf-8"),
                "text/markdown",
            )
        },
        data={
            "jd_text": "高级产品经理\n要求：SQL，数据分析",
            "candidate_notes": "希望强调数据分析",
            "output_language": "zh",
            "max_iterations": "1",
        },
    )

    assert response.status_code == 503
    assert "已关闭启发式 fallback" in response.json()["detail"]
