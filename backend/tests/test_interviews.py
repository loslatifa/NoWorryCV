from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
import json
import sqlite3
from threading import Barrier

from fastapi.testclient import TestClient
import pytest

from backend.app.agents.mock_interview import MockInterviewAgent, deterministic_feedback
from backend.app.core.config import reset_settings_cache
from backend.app.main import create_app
from backend.app.schemas.common import FactCard, TraceabilityRecord
from backend.app.services.interviews import InterviewStore, get_interview_store
from backend.app.services.runs.store import get_run_store
from backend.tests.test_draft_editing import _completed_run


def practice(client, language="zh", rounds=3):
    job = _completed_run()
    result = job.result.model_copy(deep=True)
    result.resolved_language = language
    result.fact_cards = [FactCard(id="fmetric", category="project_bullet", text="参与 SQL 分析增长实验，转化率提升20%。", confirmed=True),
                         FactCard(id="fskill", category="skill", text="SQL", confirmed=True)]
    draft = result.draft_versions[0].draft
    draft.project_section[0].bullets = [result.fact_cards[0].text]
    draft.traceability = [TraceabilityRecord(draft_span="project_section.1.bullets.1", fact_ids=["fmetric"])]
    result.final_package.draft = draft.model_copy(deep=True)
    get_run_store().update(job.run_id, result=result)
    path = f'/api/v1/tailor-runs/{job.run_id}/interviews'
    headers = {"X-Run-Token": job.access_token}
    response = client.post(path, json={"version_id": result.draft_versions[0].id, "rounds": rounds}, headers=headers)
    assert response.status_code == 201, response.text
    return path, headers, response.json(), job


def answer(client, path, headers, view, text):
    return client.post(f'{path}/{view["session"]["id"]}/answers', headers=headers, json={
        "question_id": view["current_question"]["id"], "expected_revision": view["session"]["revision"], "answer": text})


def test_grounded_rounds_follow_up_feedback_and_review_do_not_mutate_facts(tmp_path):
    with TestClient(create_app()) as client:
        path, headers, view, job = practice(client)
        original = get_run_store().get(job.run_id).result.model_dump()
        question = view["current_question"]
        assert question["resume_reference"] in question["prompt"]
        assert question["jd_reference"] in question["prompt"]
        assert question["fact_ids"] == ["fmetric"]
        bad_answer = "我独立完成项目，使用 SQL，结果转化率提升40%。"
        response = answer(client, path, headers, view, bad_answer)
        assert response.status_code == 200, response.text
        next_view = response.json()
        feedback = next_view["session"]["turns"][0]["feedback"]
        assert any(issue["kind"] == "inconsistent" for issue in feedback["issues"])
        assert all(issue["answer_quote"] in bad_answer for issue in feedback["issues"])
        assert next_view["current_question"]["kind"] == "follow_up"
        assert "40%" in next_view["current_question"]["prompt"]
        assert next_view["current_question"]["parent_question_id"] == question["id"]
        while next_view["current_question"]:
            response = answer(client, path, headers, next_view, "当时目标是复盘增长实验。我参与分析，使用 SQL 核对数据口径，按已确认的记录说明结果和个人贡献；无法核实的信息会明确说明，不把团队成果全部归给个人。")
            assert response.status_code == 200, response.text
            previous = next_view["current_question"]
            next_view = response.json()
            if previous["kind"] == "follow_up" and next_view["current_question"]:
                assert next_view["current_question"]["round_number"] > previous["round_number"]
        assert next_view["session"]["status"] == "completed"
        assert len(next_view["session"]["turns"]) <= 6
        report = client.get(f'{path}/{view["session"]["id"]}/report', headers=headers)
        assert report.status_code == 200
        assert bad_answer in report.text and "改进建议" in report.text and "已确认事实" in report.text
        assert get_run_store().get(job.run_id).result.model_dump() == original
        assert InterviewStore(str(tmp_path / "interviews.sqlite3")).get(job.run_id, view["session"]["id"]).status == "completed"


def test_scope_privacy_and_version_validation():
    with TestClient(create_app()) as client:
        path, headers, view, job = practice(client)
        session_id = view["session"]["id"]
        for suffix in ("", f"/{session_id}", f"/{session_id}/report"):
            assert client.get(path + suffix).status_code == 404
        other = _completed_run()
        wrong_path = f'/api/v1/tailor-runs/{other.run_id}/interviews/{session_id}'
        assert client.get(wrong_path, headers={"X-Run-Token": other.access_token}).status_code == 404
        assert client.delete(f'{path}/{session_id}', headers={"X-Run-Token": "wrong"}).status_code == 404
        assert client.post(path, headers=headers, json={"version_id":"missing"}).status_code == 404
        assert "access_token" not in json.dumps(view)
        listed = client.get(path, headers=headers).json()
        assert listed[0]["id"] == session_id and "draft" not in listed[0]


@pytest.mark.parametrize("invalid", [{"answer":" "}, {"answer":"x" * 6001}, {"expected_revision":0}, {"question_id":""}])
def test_answer_validation_preserves_current_question(invalid):
    with TestClient(create_app()) as client:
        path, headers, view, _ = practice(client)
        payload = {"question_id":view["current_question"]["id"], "expected_revision":1, "answer":"有效回答"}
        payload.update(invalid)
        assert client.post(f'{path}/{view["session"]["id"]}/answers', headers=headers, json=payload).status_code == 422
        assert client.get(f'{path}/{view["session"]["id"]}', headers=headers).json()["session"]["revision"] == 1


def test_lost_response_retry_is_idempotent_changed_or_stale_answers_conflict(monkeypatch):
    with TestClient(create_app()) as client:
        path, headers, view, _ = practice(client)
        text = "我参与 SQL 分析，结果按已确认记录核对。"
        accepted = answer(client, path, headers, view, text)
        def forbidden(*args):
            raise AssertionError("A duplicate answer must not call the model again")
        monkeypatch.setattr(MockInterviewAgent, "evaluate", forbidden)
        retried = answer(client, path, headers, view, text)
        assert retried.status_code == 200 and retried.json() == accepted.json()
        assert answer(client, path, headers, view, "不同回答").status_code == 409
        changed = accepted.json()
        changed["session"]["revision"] = 1
        assert answer(client, path, headers, changed, "另一题的回答").status_code == 409


def test_concurrent_answers_cannot_overwrite_each_other(monkeypatch):
    with TestClient(create_app()) as client:
        path, headers, view, _ = practice(client)
        barrier = Barrier(2)
        def evaluate(self, session, text):
            barrier.wait(timeout=5)
            return deterministic_feedback(session, text)
        monkeypatch.setattr(MockInterviewAgent, "evaluate", evaluate)
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda text: answer(client, path, headers, view, text), ["我参与分析。", "我负责数据核对。"] ))
        assert sorted(response.status_code for response in responses) == [200, 409]
        saved = client.get(f'{path}/{view["session"]["id"]}', headers=headers).json()["session"]
        assert len(saved["turns"]) == 1 and saved["revision"] == 2


def test_snapshot_survives_draft_changes_repeat_practice_and_early_finish():
    with TestClient(create_app()) as client:
        path, headers, view, job = practice(client, rounds=6)
        result = get_run_store().get(job.run_id).result.model_copy(deep=True)
        result.draft_versions[0].draft.project_section[0].bullets = ["后续修改的简历内容"]
        get_run_store().update(job.run_id, result=result)
        restored = client.get(f'{path}/{view["session"]["id"]}', headers=headers).json()
        assert restored["session"]["draft"] == view["session"]["draft"]
        repeat = client.post(path, headers=headers, json={"version_id":view["session"]["version_id"]}).json()
        assert repeat["session"]["id"] != view["session"]["id"]
        finished = client.post(f'{path}/{view["session"]["id"]}/finish', headers=headers, json={"expected_revision":1}).json()
        assert finished["session"]["status"] == "stopped" and finished["current_question"] is None
        assert answer(client, path, headers, view, "不能继续回答").status_code == 409


@pytest.mark.parametrize("action", ["delete_session", "delete_run", "expire_run"])
def test_deletion_and_expiry_remove_practice_material(tmp_path, action):
    with TestClient(create_app()) as client:
        path, headers, view, job = practice(client)
        session_path = f'{path}/{view["session"]["id"]}'
        if action == "delete_session":
            assert client.delete(session_path, headers=headers).status_code == 204
        elif action == "delete_run":
            assert client.delete(f'/api/v1/tailor-runs/{job.run_id}', headers=headers).status_code == 204
        else:
            get_run_store().update(job.run_id, expires_at=(datetime.now(timezone.utc)-timedelta(seconds=1)).isoformat())
        assert client.get(session_path, headers=headers).status_code == 404
        with sqlite3.connect(tmp_path / "interviews.sqlite3") as connection:
            assert connection.execute("SELECT COUNT(*) FROM interviews").fetchone()[0] == 0


def test_strict_model_failure_keeps_answer_retryable(monkeypatch):
    with TestClient(create_app()) as client:
        path, headers, view, _ = practice(client)
        monkeypatch.setenv("LLM_STRICT_MODE", "true"); reset_settings_cache()
        response = answer(client, path, headers, view, "我参与 SQL 分析项目。")
        assert response.status_code == 503
        assert client.get(f'{path}/{view["session"]["id"]}', headers=headers).json()["session"]["revision"] == 1
        monkeypatch.setenv("LLM_STRICT_MODE", "false"); reset_settings_cache()
        assert answer(client, path, headers, view, "我参与 SQL 分析项目。").status_code == 200


def test_model_feedback_quotes_fact_ids_and_advice_are_checked():
    with TestClient(create_app()) as client:
        path, headers, view, job = practice(client)
        session = get_interview_store().get(job.run_id, view["session"]["id"])
        text = "我独立完成项目，使用 Redis，转化率提升40%。"
        output = deterministic_feedback(session, text).model_copy(deep=True)
        output.structure.answer_quote = "模型编造的回答片段"
        output.consistency.score = 4
        output.evidence.score = 4
        output.issues = [output.issues[0].model_copy(update={"fact_ids":["foreign-fact"]}),
                         output.issues[0].model_copy(update={"recommendation":"建议你编造转化率提升99%。"})]
        output.suggestions = ["建议你编造一个增长成果。", "可以说转化率提升99%。", "补充 Kafka 的实际使用经历。"]
        output.follow_up_quote = "不存在的引文"
        class FakeService:
            is_available = True
            def generate(self, **kwargs):
                assert kwargs["context"]["question"].id == view["current_question"]["id"]
                assert kwargs["context"]["confirmed_facts"]
                return output
        feedback = MockInterviewAgent(FakeService()).evaluate(session, text)
        assert feedback.method == "model"
        assert feedback.structure.answer_quote in text
        assert feedback.follow_up_quote in text
        assert all(set(issue.fact_ids) <= {"fmetric", "fskill"} for issue in feedback.issues)
        assert any(issue.kind == "inconsistent" for issue in feedback.issues)
        assert feedback.consistency.score == 1 and feedback.evidence.score == 1
        assert all("99%" not in issue.recommendation for issue in feedback.issues)
        assert all("99%" not in advice and "Kafka" not in advice and "建议你编造" not in advice for advice in feedback.suggestions)


def test_model_issue_limit_cannot_displace_deterministic_fact_risks():
    with TestClient(create_app()) as client:
        _, _, view, job = practice(client)
        session = get_interview_store().get(job.run_id, view["session"]["id"])
        answer_text = "我独立完成整个项目，使用 Redis，转化率提升40%。"
        rules = deterministic_feedback(session,answer_text)
        output = rules.model_copy(deep=True)
        output.issues = [rules.issues[0].model_copy(update={"kind":"expression","answer_quote":answer_text[:index+1],
            "fact_ids":[],"explanation":"请解释表达。","recommendation":"说明背景。"}) for index in range(12)]
        class Model:
            is_available = True
            def generate(self,**kwargs):return output
        feedback = MockInterviewAgent(Model()).evaluate(session,answer_text)
        assert len(feedback.issues)<=12
        assert all(any(item.kind==issue.kind and item.answer_quote==issue.answer_quote for item in feedback.issues) for issue in rules.issues)


def test_hypothetical_answer_does_not_become_a_candidate_claim_and_english_supported():
    with TestClient(create_app()) as client:
        path, headers, view, job = practice(client, language="en")
        session = get_interview_store().get(job.run_id, view["session"]["id"])
        assert "The JD asks for" in view["current_question"]["prompt"]
        feedback = deterministic_feedback(session, "If the team had used Redis, we could test a hypothetical 40% improvement. I would check the measurement first.")
        assert not feedback.issues
        assert feedback.structure.answer_quote in "If the team had used Redis, we could test a hypothetical 40% improvement. I would check the measurement first."


def test_corrections_negations_equivalent_numbers_and_mixed_hypotheses():
    with TestClient(create_app()) as client:
        path, headers, view, job = practice(client)
        session = get_interview_store().get(job.run_id, view["session"]["id"])
        correction = deterministic_feedback(session, "我参与 SQL 分析，结果提升20.0%。我没有独立完成项目，没有使用 Redis。")
        assert not correction.issues
        denied = deterministic_feedback(session, "结果不是40%，是已确认的20%。我没有主导项目。")
        assert not denied.issues
        mixed = deterministic_feedback(session, "我独立完成项目，转化率提升40%。下一步我会继续优化。")
        assert any(issue.kind == "inconsistent" for issue in mixed.issues)


def test_interview_answer_rate_limit_leaves_the_question_available(monkeypatch):
    monkeypatch.setenv("RATE_LIMIT_REQUESTS", "1"); reset_settings_cache()
    with TestClient(create_app()) as client:
        path, headers, view, _ = practice(client)
        response = answer(client, path, headers, view, "我参与 SQL 分析。")
        assert response.status_code == 429 and "Retry-After" in response.headers
        restored = client.get(f'{path}/{view["session"]["id"]}', headers=headers).json()
        assert restored["current_question"]["id"] == view["current_question"]["id"]
        assert not restored["session"]["turns"]
