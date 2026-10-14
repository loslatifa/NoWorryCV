import time
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from backend.app.agents.orchestrator import ResumeTailorOrchestrator
from backend.app.main import create_app
from backend.app.schemas.run_state import TailorRunInput
from backend.app.services.runs.queue import DurableTaskQueue


def _wait_for_status(client: TestClient, run_id: str, token: str, expected: str) -> dict:
    response_payload = {}
    for _ in range(100):
        response = client.get(
            "/api/v1/tailor-runs/{0}/status".format(run_id),
            headers={"X-Run-Token": token},
        )
        assert response.status_code == 200
        response_payload = response.json()
        if response_payload["status"] == expected:
            if expected != "failed" or response_payload["retryable"]:
                return response_payload
        time.sleep(0.02)
    raise AssertionError("Run did not reach {0}: {1}".format(expected, response_payload))


def _submit_job(client: TestClient, idempotency_key: str = "queue-test") -> dict:
    response = client.post(
        "/api/v1/tailor-runs/upload-jobs",
        headers={"Idempotency-Key": idempotency_key},
        files={
            "resume_file": (
                "resume.md",
                "张三\n\n项目经历\n增长项目\n- 使用 SQL 分析漏斗\n\n技能\nSQL".encode("utf-8"),
                "text/markdown",
            )
        },
        data={
            "jd_text": "产品经理\n要求：SQL、数据分析",
            "output_language": "zh",
            "max_iterations": "1",
        },
    )
    assert response.status_code == 200
    return response.json()


def test_durable_queue_recovers_claimed_task_after_restart(tmp_path) -> None:
    database_path = str(tmp_path / "queue.sqlite3")
    payload = TailorRunInput(resume_text="resume", jd_text="jd", processing_mode="fast")
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    queue = DurableTaskQueue(database_path)
    assert queue.enqueue("run-1", payload, "request-1", expires_at) is None

    claimed = queue._claim_next()
    assert claimed is not None
    assert queue.metadata("run-1")["status"] == "running"

    reloaded = DurableTaskQueue(database_path)
    assert reloaded.recover_interrupted() == ["run-1"]
    assert reloaded.metadata("run-1")["status"] == "queued"
    resumed = reloaded._claim_next()
    assert resumed is not None
    assert resumed.run_id == "run-1"
    assert resumed.attempt == 2


def test_duplicate_idempotency_key_does_not_create_second_task() -> None:
    client = TestClient(create_app())
    first = _submit_job(client, "same-browser-request")
    second = client.post(
        "/api/v1/tailor-runs/upload-jobs",
        headers={"Idempotency-Key": "same-browser-request"},
        files={"resume_file": ("resume.md", b"resume", "text/markdown")},
        data={"jd_text": "SQL product manager"},
    )

    assert first["run_id"]
    assert second.status_code == 409
    assert "已提交" in second.json()["detail"]


def test_failed_stage_can_resume_from_last_checkpoint(monkeypatch) -> None:
    original_strategy_node = ResumeTailorOrchestrator._strategy_node
    calls = {"count": 0}

    def flaky_strategy(self, raw_state):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("simulated stage failure")
        return original_strategy_node(self, raw_state)

    monkeypatch.setattr(ResumeTailorOrchestrator, "_strategy_node", flaky_strategy)
    client = TestClient(create_app())
    created = _submit_job(client, "retry-from-checkpoint")
    run_id = created["run_id"]
    token = created["access_token"]

    failed = _wait_for_status(client, run_id, token, "failed")
    assert failed["failed_stage"] == "strategy"
    assert failed["error_type"] == "RuntimeError"
    completed_before_failure = [
        item["stage"] for item in failed["stage_history"] if item["status"] == "completed"
    ]
    assert completed_before_failure[-1] == "gap_analysis"

    retry = client.post(
        "/api/v1/tailor-runs/{0}/retry".format(run_id),
        headers={"X-Run-Token": token},
    )
    assert retry.status_code == 200
    completed = _wait_for_status(client, run_id, token, "completed")

    assert completed["result"]["status"] == "completed"
    assert completed["attempt_count"] == 2
    assert sum(item["stage"] == "analyze_jd" for item in completed["stage_history"]) == 1
    assert any(item["stage"] == "strategy" and item["status"] == "failed" for item in completed["stage_history"])
    assert any(item["stage"] == "strategy" and item["status"] == "completed" for item in completed["stage_history"])
    assert all(item["duration_ms"] >= 0 for item in completed["stage_history"])


def test_cancelled_queued_task_can_be_retried(tmp_path) -> None:
    queue = DurableTaskQueue(str(tmp_path / "cancel.sqlite3"), max_attempts=2)
    payload = TailorRunInput(resume_text="resume", jd_text="jd", processing_mode="fast")
    expires_at = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    queue.enqueue("run-cancel", payload, "cancel-request", expires_at)

    assert queue.request_cancel("run-cancel") is True
    assert queue.metadata("run-cancel")["status"] == "cancelled"
    assert queue.retry("run-cancel") is True
    assert queue.metadata("run-cancel")["status"] == "queued"
