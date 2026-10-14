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


def test_parse_upload_returns_editable_unconfirmed_facts(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    app = create_app()
    client = TestClient(app)

    response = client.post(
        "/api/v1/resume/parse-upload",
        files={
            "resume_file": (
                "resume.md",
                "# Resume\n\n张三\n\n项目经历\n增长实验项目\n- 使用 SQL 复盘实验结果\n\n技能\nSQL".encode("utf-8"),
                "text/markdown",
            )
        },
        data={
            "candidate_notes": "希望强调数据分析",
            "jd_text": "产品经理\n要求：SQL、用户研究、A/B Testing",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["resume_text"]
    assert payload["candidate_profile"]["basics"]["name"] == "张三"
    assert payload["fact_cards"]
    assert all(card["confirmed"] is False for card in payload["fact_cards"])
    assert all(card["source_excerpt"] for card in payload["fact_cards"])
    assert payload["jd_profile"] is not None
    assert payload["gap_analysis"] is not None
    assert 1 <= len(payload["follow_up_questions"]) <= 5
    assert all(question["prompt"] for question in payload["follow_up_questions"])


def test_confirmed_job_rejects_unconfirmed_facts(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    app = create_app()
    client = TestClient(app)
    parsed = client.post(
        "/api/v1/resume/parse-upload",
        files={
            "resume_file": (
                "resume.md",
                "张三\n\n项目经历\n增长实验项目\n- 使用 SQL 复盘实验结果\n\n技能\nSQL".encode("utf-8"),
                "text/markdown",
            )
        },
    ).json()

    response = client.post(
        "/api/v1/tailor-runs/confirmed-jobs",
        json={
            "resume_text": parsed["resume_text"],
            "jd_text": "产品经理\n要求：SQL，数据分析",
            "output_language": "zh",
            "max_iterations": 1,
            "confirmed_candidate_profile": parsed["candidate_profile"],
            "confirmed_fact_cards": parsed["fact_cards"],
        },
    )

    assert response.status_code == 400
    assert "must be confirmed" in response.json()["detail"]


def test_confirmed_job_uses_user_corrected_profile_and_facts(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "stub")
    app = create_app()
    client = TestClient(app)
    parsed = client.post(
        "/api/v1/resume/parse-upload",
        files={
            "resume_file": (
                "resume.md",
                "张三\n\n项目经历\n增长实验项目\n- 使用 SQL 复盘实验结果\n\n技能\nSQL".encode("utf-8"),
                "text/markdown",
            )
        },
    ).json()

    parsed["candidate_profile"]["basics"]["name"] = "李四"
    project_fact = next(card for card in parsed["fact_cards"] if card["category"] == "project_bullet")
    project_fact["text"] = "使用 SQL 复盘增长实验，并沉淀分析结论"
    for fact in parsed["fact_cards"]:
        fact["confirmed"] = True
    parsed["fact_cards"].append(
        {
            "id": "fact_follow_up_project_role",
            "category": "project_bullet",
            "text": "独立负责实验数据清洗、分析与结论汇报",
            "source_type": "user",
            "source_span": "follow_up.project_role",
            "source_excerpt": "你在项目中具体负责哪一部分？",
            "evidence_level": "user_confirmed",
            "confidence": 1,
            "confirmed": True,
            "allowed_operations": ["rewrite", "reorder", "highlight"],
        }
    )

    response = client.post(
        "/api/v1/tailor-runs/confirmed-jobs",
        json={
            "resume_text": parsed["resume_text"],
            "jd_text": "2026 校招产品经理\n要求：SQL，数据分析",
            "output_language": "zh",
            "max_iterations": 1,
            "confirmed_candidate_profile": parsed["candidate_profile"],
            "confirmed_fact_cards": parsed["fact_cards"],
        },
    )

    assert response.status_code == 200
    created = response.json()
    run_id = created["run_id"]
    headers = {"X-Run-Token": created["access_token"]}
    final_payload = None
    for _ in range(40):
        job = client.get("/api/v1/tailor-runs/{0}/status".format(run_id), headers=headers).json()
        if job["status"] == "completed":
            final_payload = job
            break
        time.sleep(0.05)

    assert final_payload is not None
    result = final_payload["result"]
    assert result["candidate_profile"]["basics"]["name"] == "李四"
    assert result["candidate_profile"]["projects"][0]["bullets"] == [
        "使用 SQL 复盘增长实验，并沉淀分析结论",
        "独立负责实验数据清洗、分析与结论汇报",
    ]
    assert "李四" in result["final_package"]["draft"]["headline"]


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
    assert payload["access_token"]
    headers = {"X-Run-Token": payload["access_token"]}
    assert payload["current_stage"] == "queued"

    final_payload = None
    saw_review_cards = False
    for _ in range(40):
        status_response = client.get(
            "/api/v1/tailor-runs/{0}/status".format(payload["run_id"]),
            headers=headers,
        )
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
    assert response.json()["detail"] == "模型服务暂时不可用，请检查服务配置或稍后重试。"
    assert "jd_analyst" not in response.json()["detail"]
