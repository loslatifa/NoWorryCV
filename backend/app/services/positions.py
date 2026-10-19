"""Durable job records and explicitly linked material snapshots, scoped to a profile."""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
import sqlite3
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.schemas.position import PositionEvent, PositionRecord, PositionRun, PositionSummary, STATUS_LABELS


def utc_now():
    return datetime.now(timezone.utc).isoformat()


class PositionConflict(ValueError):
    pass


class PositionStore:
    def __init__(self, path):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS positions (id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, record_json TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS positions_profile ON positions(profile_id)")

    @contextmanager
    def connection(self):
        connection = sqlite3.connect(self.path, timeout=15); connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA secure_delete=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def create(self, profile_id, payload):
        now = utc_now()
        record = PositionRecord(id=str(uuid4()), profile_id=profile_id, company=payload.company, role=payload.role,
            jd_text=payload.jd_text, job_url=str(payload.job_url or ""), created_at=now, updated_at=now,
            timeline=[PositionEvent(at=now, kind="created", summary="保存职位，状态为待投递。")])
        with self.connection() as connection:
            connection.execute("INSERT INTO positions VALUES (?, ?, ?)", (record.id, profile_id, record.model_dump_json()))
        return record

    def _get(self, connection, profile_id, position_id):
        row = connection.execute("SELECT record_json FROM positions WHERE id=? AND profile_id=?", (position_id, profile_id)).fetchone()
        return PositionRecord.model_validate_json(row[0]) if row else None

    def get(self, profile_id, position_id):
        with self.connection() as connection:
            return self._get(connection, profile_id, position_id)

    def list(self, profile_id, search="", status="all", reminder="all"):
        with self.connection() as connection:
            rows = connection.execute("SELECT record_json FROM positions WHERE profile_id=?", (profile_id,)).fetchall()
        records = [PositionRecord.model_validate_json(row[0]) for row in rows]
        counts = {key: sum(record.status == key for record in records) for key in STATUS_LABELS}
        items = []
        now = utc_now()
        for record in records:
            due = "none" if not record.remind_at or record.status == "closed" else ("due" if record.remind_at <= now else "upcoming")
            if status != "all" and record.status != status or reminder != "all" and due != reminder:
                continue
            if search.strip().casefold() not in " ".join([record.company, record.role, record.jd_text, record.next_action]).casefold():
                continue
            current = next((resume for resume in record.resumes if resume.id == record.current_resume_id), None)
            items.append(PositionSummary(**record.model_dump(include={"id", "company", "role", "status", "next_action", "remind_at", "updated_at"}),
                current_resume_label=current.label if current else "", resume_count=len(record.resumes), interview_count=len(record.interviews), reminder=due))
        items.sort(key=lambda item: item.updated_at, reverse=True)
        items.sort(key=lambda item: 0 if item.reminder == "due" else 1)
        return {"items": items, "counts": counts}

    def mutate(self, profile_id, position_id, revision, callback):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            record = self._get(connection, profile_id, position_id)
            if record is None:
                return None
            if record.revision != revision:
                raise PositionConflict("职位已在其他页面更新，请刷新后再保存。")
            changed = callback(record)
            if changed:
                record.revision += 1; record.updated_at = utc_now()
                connection.execute("UPDATE positions SET record_json=? WHERE id=?", (record.model_dump_json(), record.id))
            return record

    def update(self, profile_id, position_id, payload):
        def apply(record):
            changes = {}
            for key in payload.model_fields_set - {"expected_revision", "note"}:
                value = getattr(payload, key)
                if key == "remind_at": value = value.isoformat() if value else None
                if key == "job_url": value = str(value or "")
                old = getattr(record, key)
                if old != value:
                    changes[key] = [old, value]; setattr(record, key, value)
            if not changes and not payload.note.strip(): return False
            summary = "更新职位信息和下一步行动。"
            if "status" in changes: summary = "{0} → {1}".format(*(STATUS_LABELS[value] for value in changes["status"]))
            record.timeline.append(PositionEvent(at=utc_now(), kind="updated", summary=summary, changes=changes, note=payload.note.strip()))
            return True
        return self.mutate(profile_id, position_id, payload.expected_revision, apply)

    def link_resume(self, profile_id, position_id, revision, snapshot):
        def apply(record):
            existing = next((item for item in record.resumes if item.source_kind == snapshot.source_kind and item.run_id == snapshot.run_id
                             and item.version_id == snapshot.version_id and item.application_id == snapshot.application_id and item.draft_digest == snapshot.draft_digest), None)
            if existing:
                return self._select_resume(record, existing.id)
            record.resumes.append(snapshot); record.current_resume_id = snapshot.id
            record.timeline.append(PositionEvent(at=utc_now(), kind="resume", summary="长期关联简历并设为当前投递版本：" + snapshot.label))
            return True
        return self.mutate(profile_id, position_id, revision, apply)

    def _select_resume(self, record, resume_id):
        snapshot = next((item for item in record.resumes if item.id == resume_id), None)
        if snapshot is None: raise PositionConflict("职位中没有该简历快照。")
        if record.current_resume_id == resume_id: return False
        record.current_resume_id = resume_id
        record.timeline.append(PositionEvent(at=utc_now(), kind="resume", summary="切换当前投递版本：" + snapshot.label))
        return True

    def select_resume(self, profile_id, position_id, revision, resume_id):
        return self.mutate(profile_id, position_id, revision, lambda record: self._select_resume(record, resume_id))

    def link_interview(self, profile_id, position_id, revision, snapshot):
        def apply(record):
            if not any(resume.id == snapshot.resume_id for resume in record.resumes): raise PositionConflict("请先关联面试使用的简历版本。")
            if any(item.source_session_id == snapshot.source_session_id and item.source_revision == snapshot.source_revision for item in record.interviews): return False
            record.interviews.append(snapshot)
            record.timeline.append(PositionEvent(at=utc_now(), kind="interview", summary="长期保存面试复习报告，已回答 {0} 题。".format(snapshot.answered_count)))
            return True
        return self.mutate(profile_id, position_id, revision, apply)

    def link_material(self, profile_id, position_id, revision, snapshot):
        def apply(record):
            if not any(resume.id == snapshot.resume_id for resume in record.resumes):
                raise PositionConflict("请先关联材料使用的简历版本。")
            if any(item.resume_id == snapshot.resume_id and item.pack.id == snapshot.pack.id and item.pack.revision == snapshot.pack.revision for item in record.materials):
                return False
            record.materials.append(snapshot)
            record.timeline.append(PositionEvent(at=utc_now(), kind="materials", summary="长期保存已核对的岗位求职材料包。"))
            return True
        return self.mutate(profile_id, position_id, revision, apply)

    def add_run(self, profile_id, position_id, revision, job, jd_text):
        def apply(record):
            if any(run.run_id == job.run_id for run in record.runs): return False
            record.runs.append(PositionRun(run_id=job.run_id, created_at=job.created_at, jd_text=jd_text))
            record.timeline.append(PositionEvent(at=utc_now(), kind="generated", summary="为此职位创建简历生成任务；完成后可选择并长期关联版本。"))
            return True
        return self.mutate(profile_id, position_id, revision, apply)

    def delete(self, profile_id, position_id):
        with self.connection() as connection:
            return bool(connection.execute("DELETE FROM positions WHERE id=? AND profile_id=?", (position_id, profile_id)).rowcount)

    def delete_for_profile(self, profile_id):
        with self.connection() as connection:
            connection.execute("DELETE FROM positions WHERE profile_id=?", (profile_id,))


@lru_cache
def get_position_store():
    return PositionStore(get_settings().position_store_path)
