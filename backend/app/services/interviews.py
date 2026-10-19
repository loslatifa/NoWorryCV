"""Owner-scoped interview snapshots, retained only for the parent run's lifetime."""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import sqlite3
from uuid import uuid4

from backend.app.agents.mock_interview import build_follow_up, build_questions
from backend.app.core.config import get_settings
from backend.app.schemas.interview import InterviewSession, InterviewSummary, InterviewTurn
from backend.app.services.provenance import capture_provenance


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class InterviewConflict(ValueError):
    pass


class InterviewStore:
    def __init__(self, path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS interviews (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, expires_at TEXT NOT NULL, session_json TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS interviews_run ON interviews(run_id)")

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA secure_delete=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, job, version, rounds):
        now = utc_now()
        facts = [fact.model_copy(deep=True) for fact in job.result.fact_cards if fact.confirmed]
        language = job.result.resolved_language
        if language not in {"en", "zh"}:
            language = "en" if job.result.jd_profile.language == "en" else "zh"
        session = InterviewSession(
            id=str(uuid4()), run_id=job.run_id, version_id=version.id, version_label=version.label,
            language=language, rounds=rounds, created_at=now, updated_at=now, expires_at=job.expires_at,
            draft=version.draft.model_copy(deep=True), jd_profile=job.result.jd_profile.model_copy(deep=True), fact_cards=facts,
            questions=build_questions(version.draft, job.result.jd_profile, facts, rounds, language),
            provenance=capture_provenance("mock_interview"),
        )
        with self.connection() as connection:
            connection.execute("INSERT INTO interviews VALUES (?, ?, ?, ?)",
                               (session.id, session.run_id, session.expires_at, session.model_dump_json()))
        return session

    def _get(self, connection, run_id, session_id):
        row = connection.execute("SELECT session_json FROM interviews WHERE id = ? AND run_id = ? AND expires_at > ?",
                                 (session_id, run_id, utc_now())).fetchone()
        return InterviewSession.model_validate_json(row[0]) if row else None

    def get(self, run_id, session_id):
        with self.connection() as connection:
            return self._get(connection, run_id, session_id)

    def list(self, run_id):
        with self.connection() as connection:
            rows = connection.execute("SELECT session_json FROM interviews WHERE run_id = ? AND expires_at > ? ORDER BY rowid DESC", (run_id, utc_now())).fetchall()
        summaries = []
        for row in rows:
            session = InterviewSession.model_validate_json(row[0])
            summaries.append(InterviewSummary(**session.model_dump(include={"id", "version_id", "version_label", "status", "rounds", "created_at", "updated_at", "expires_at"}),
                answered_count=len(session.turns), question_count=len(session.questions)))
        return summaries

    @staticmethod
    def check_answer(session, payload):
        submitted = next((turn for turn in session.turns if turn.question.id == payload.question_id), None)
        if submitted:
            if submitted.answer == payload.answer:
                return False  # A lost response may be safely retried without another model call.
            raise InterviewConflict("这道题已有回答。若需改写，请创建新的练习。")
        if session.revision != payload.expected_revision:
            raise InterviewConflict("练习已在其他页面更新，请重新载入当前问题。")
        if not session.current_question or session.current_question.id != payload.question_id:
            raise InterviewConflict("当前问题已变化或练习已结束，请重新载入。")
        return True

    def submit(self, run_id, session_id, payload, feedback, provenance):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            session = self._get(connection, run_id, session_id)
            if session is None:
                return None
            if not self.check_answer(session, payload):
                return session
            question = session.current_question.model_copy(deep=True)
            session.turns.append(InterviewTurn(question=question, answer=payload.answer, answered_at=utc_now(), feedback=feedback, provenance=provenance))
            follow_up = build_follow_up(question, feedback, payload.answer, session.language)
            if follow_up:
                session.questions.insert(len(session.turns), follow_up)
            if len(session.turns) == len(session.questions):
                session.status = "completed"
            session.updated_at = utc_now()
            session.revision += 1
            connection.execute("UPDATE interviews SET session_json = ? WHERE id = ?", (session.model_dump_json(), session.id))
            return session

    def finish(self, run_id, session_id, revision):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            session = self._get(connection, run_id, session_id)
            if session is None:
                return None
            if session.status != "active":
                return session
            if session.revision != revision:
                raise InterviewConflict("练习已更新，请重新载入后结束。")
            session.status = "stopped"
            session.revision += 1
            session.updated_at = utc_now()
            connection.execute("UPDATE interviews SET session_json = ? WHERE id = ?", (session.model_dump_json(), session.id))
            return session

    def delete(self, run_id, session_id):
        with self.connection() as connection:
            return bool(connection.execute("DELETE FROM interviews WHERE id = ? AND run_id = ?", (session_id, run_id)).rowcount)

    def delete_for_run(self, run_id):
        with self.connection() as connection:
            connection.execute("DELETE FROM interviews WHERE run_id = ?", (run_id,))

    def cleanup_expired(self):
        with self.connection() as connection:
            return connection.execute("DELETE FROM interviews WHERE expires_at <= ?", (utc_now(),)).rowcount


def interview_report(session):
    en = session.language == "en"
    status = {"active": "In progress" if en else "进行中", "completed": "Completed" if en else "已完成", "stopped": "Stopped early" if en else "提前结束"}[session.status]
    lines = ["# Mock interview review" if en else "# 模拟面试复习报告",
             f"{'Role' if en else '岗位'}：{session.jd_profile.job_title}",
             f"{'Resume version' if en else '简历版本'}：{session.version_label} ({session.version_id})",
             f"{'Status' if en else '状态'}：{status}",
             f"{'Expires at' if en else '保存至'}：{session.expires_at}", "",
             "Feedback is practice guidance, not a hiring prediction or proof of truth. Answers are not added to confirmed facts." if en else "反馈用于练习，不代表面试通过率或事实认证。回答不会自动加入已确认事实；未提示风险也不代表已核实。", ""]
    lookup = {fact.id: fact.text for fact in session.fact_cards}
    for index, turn in enumerate(session.turns, 1):
        lines += [f"## {index} · {turn.question.prompt}", f"JD：{turn.question.jd_reference}",
                  f"{'Resume' if en else '简历'}：{turn.question.resume_reference}", "",
                  "### Answer" if en else "### 回答", *["> " + line for line in turn.answer.splitlines()], ""]
        for key, label in (("structure", "Structure" if en else "结构"), ("evidence", "Evidence" if en else "证据"),
                           ("clarity", "Clarity" if en else "清晰度"), ("consistency", "Consistency" if en else "一致性")):
            assessment = getattr(turn.feedback, key)
            lines.append(f"- {label}：{assessment.score}/4 · {assessment.reason}")
            if assessment.answer_quote:
                lines.append(f"  {'Quote' if en else '回答片段'}：「{assessment.answer_quote}」")
        for issue in turn.feedback.issues:
            lines += [f"- {'Check' if en else '待核实'}：「{issue.answer_quote}」 · {issue.explanation}", f"  {issue.recommendation}"]
            for fact_id in issue.fact_ids:
                if fact_id in lookup:
                    lines.append(f"  {'Confirmed fact' if en else '已确认事实'} [{fact_id}]：{lookup[fact_id]}")
        lines += ["", "### Improvements" if en else "### 改进建议", *["- " + suggestion for suggestion in turn.feedback.suggestions], "",
                  f"{'Feedback method' if en else '反馈方式'}：{('Model' if en else '模型评估') if turn.feedback.method == 'model' else ('Rules with limited fact checks' if en else '规则评估，有限事实检查')}", ""]
    return "\n".join(lines).strip()


@lru_cache
def get_interview_store():
    return InterviewStore(get_settings().interview_store_path)
