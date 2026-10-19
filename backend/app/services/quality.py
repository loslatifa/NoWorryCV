"""Owner-scoped feedback and minimal behaviour events. No resume or feedback prose is stored."""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import json
import hashlib
import logging
from pathlib import Path
import sqlite3
from uuid import uuid4
from zoneinfo import ZoneInfo

from backend.app.core.config import get_settings
from backend.app.schemas.quality import FeedbackRecord, QualityBreakdown, QualityDashboard, QualityMetrics

logger = logging.getLogger(__name__)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def saved_version_id(result, draft):
    version = next((item for item in result.draft_versions if item.id == result.active_version_id), None)
    return version.id if version and version.draft == draft else ""


class QualityStore:
    def __init__(self, path):
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS quality_runs (
                    run_id TEXT PRIMARY KEY, created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
                    hiring_track TEXT NOT NULL, language TEXT NOT NULL, provenance_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS quality_events (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES quality_runs(run_id) ON DELETE CASCADE,
                    kind TEXT NOT NULL, version_id TEXT NOT NULL, target_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS quality_events_run ON quality_events(run_id);
                CREATE TABLE IF NOT EXISTS quality_feedback (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES quality_runs(run_id) ON DELETE CASCADE,
                    target_hash TEXT NOT NULL, record_json TEXT NOT NULL,
                    UNIQUE(run_id, target_hash)
                );
            """)

    @contextmanager
    def _connection(self):
        db = sqlite3.connect(str(self._path), timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def ensure_run(self, job):
        result = job.result
        provenance = result.provenance if result else job.provenance
        if result and len(result.provenance_history) > 1:
            signature = hashlib.sha256("|".join(item.fingerprint for item in result.provenance_history).encode()).hexdigest()
            provenance = provenance.model_copy(update={"provider": "mixed", "model": "multiple", "prompt_version": "mixed", "fingerprint": "mixed:" + signature})
        with self._connection() as db:
            db.execute("""INSERT INTO quality_runs VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(run_id) DO UPDATE SET expires_at=excluded.expires_at,
                hiring_track=excluded.hiring_track, language=excluded.language,
                provenance_json=excluded.provenance_json""", (
                job.run_id, job.created_at, job.expires_at,
                result.jd_profile.hiring_track if result else "unknown",
                result.resolved_language if result else "unknown", provenance.model_dump_json(),
            ))

    def event(self, run_id, kind, version_id="", target_hash="", event_id=None):
        with self._connection() as db:
            db.execute("INSERT OR IGNORE INTO quality_events VALUES (?, ?, ?, ?, ?, ?)", (
                event_id or str(uuid4()), run_id, kind, version_id, target_hash, now_iso(),
            ))

    def feedback(self, run_id, payload, target_hash, version):
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT record_json FROM quality_feedback WHERE run_id=? AND target_hash=?",
                             (run_id, target_hash)).fetchone()
            previous = FeedbackRecord.model_validate_json(row[0]) if row else None
            current = FeedbackRecord(**payload.model_dump(), id=previous.id if previous else str(uuid4()),
                                     created_at=previous.created_at if previous else now_iso(), updated_at=now_iso(),
                                     source=version.source, provenance=version.provenance)
            db.execute("""INSERT INTO quality_feedback VALUES (?, ?, ?, ?)
                ON CONFLICT(run_id, target_hash) DO UPDATE SET record_json=excluded.record_json""",
                       (current.id, run_id, target_hash, current.model_dump_json()))
        return current

    def feedback_for_run(self, run_id):
        with self._connection() as db:
            rows = db.execute("SELECT record_json FROM quality_feedback WHERE run_id=? ORDER BY rowid", (run_id,)).fetchall()
        return [FeedbackRecord.model_validate_json(row[0]) for row in rows]

    def delete_run(self, run_id):
        with self._connection() as db:
            db.execute("DELETE FROM quality_runs WHERE run_id=?", (run_id,))

    def delete_version(self, run_id, version_id):
        with self._connection() as db:
            db.execute("DELETE FROM quality_events WHERE run_id=? AND version_id=?", (run_id, version_id))
            rows = db.execute("SELECT id, record_json FROM quality_feedback WHERE run_id=?", (run_id,)).fetchall()
            for row in rows:
                if json.loads(row["record_json"])["version_id"] == version_id:
                    db.execute("DELETE FROM quality_feedback WHERE id=?", (row["id"],))

    def cleanup_expired(self):
        with self._connection() as db:
            db.execute("DELETE FROM quality_runs WHERE expires_at <= ?", (now_iso(),))

    def dashboard(self, run_ids=None, hiring_track="all", language="all"):
        self.cleanup_expired()
        with self._connection() as db:
            rows = db.execute("SELECT * FROM quality_runs ORDER BY created_at, run_id").fetchall()
            selected = [dict(row) for row in rows if (run_ids is None or row["run_id"] in run_ids)
                        and (hiring_track == "all" or row["hiring_track"] == hiring_track)
                        and (language == "all" or row["language"] == language)]
            ids = {row["run_id"] for row in selected}
            events = [dict(row) for row in db.execute("SELECT rowid AS ordinal, * FROM quality_events ORDER BY rowid").fetchall()
                      if row["run_id"] in ids]
            feedback = [(row["run_id"], FeedbackRecord.model_validate_json(row["record_json"]))
                        for row in db.execute("SELECT * FROM quality_feedback").fetchall() if row["run_id"] in ids]

        def metrics(group):
            group_ids = {row["run_id"] for row in group}
            group_events = [event for event in events if event["run_id"] in group_ids]
            counts = {kind: len({event["run_id"] for event in group_events if event["kind"] == kind})
                      for kind in ("completed", "reviewed", "edit", "export", "confirmed")}
            ratings = [record.rating for run_id, record in feedback if run_id in group_ids and record.scope == "result"]
            change_ratings = [record.rating for run_id, record in feedback if run_id in group_ids and record.scope == "change"]
            reviewed = {event["run_id"] for event in group_events if event["kind"] in {"edit", "accepted", "rejected"}}
            reviewed.update(run_id for run_id, _ in feedback if run_id in group_ids)
            latest_decisions = {}
            for event in group_events:
                if event["kind"] in {"accepted", "rejected"}:
                    latest_decisions[(event["run_id"], event["version_id"], event["target_hash"])] = event["kind"]
            accepted = sum(kind == "accepted" for kind in latest_decisions.values())
            rejected = len(latest_decisions) - accepted
            return QualityMetrics(
                started_runs=len(group), completed_runs=counts["completed"], reviewed_runs=len(reviewed),
                edited_runs=counts["edit"], exported_runs=counts["export"], confirmed_runs=counts["confirmed"],
                feedback_count=len(ratings), average_rating=round(sum(ratings) / len(ratings), 2) if ratings else None,
                change_feedback_count=len(change_ratings), average_change_rating=round(sum(change_ratings) / len(change_ratings), 2) if change_ratings else None,
                satisfaction_rate=round(sum(rating >= 4 for rating in ratings) / len(ratings), 4) if ratings else None,
                accepted_changes=accepted, rejected_changes=rejected,
                change_acceptance_rate=round(accepted / (accepted + rejected), 4) if accepted + rejected else None,
                export_rate=round(counts["export"] / counts["completed"], 4) if counts["completed"] else None,
            )

        def groups(key):
            grouped = {}
            for row in selected:
                grouped.setdefault(key(row), []).append(row)
            return [QualityBreakdown(key=name, metrics=metrics(group)) for name, group in sorted(grouped.items())]

        from backend.app.schemas.quality import GenerationProvenance
        provenance = {json.loads(row["provenance_json"])["fingerprint"]:
                      GenerationProvenance.model_validate_json(row["provenance_json"]) for row in selected}
        return QualityDashboard(
            metrics=metrics(selected), by_hiring_track=groups(lambda row: row["hiring_track"]),
            by_language=groups(lambda row: row["language"]),
            by_generation_version=groups(lambda row: json.loads(row["provenance_json"])["fingerprint"]),
            daily_trend=groups(lambda row: datetime.fromisoformat(row["created_at"]).astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()), provenance=list(provenance.values()),
        )


@lru_cache
def get_quality_store():
    return QualityStore(get_settings().quality_store_path)


def record_event(job, kind, version_id="", target_hash="", event_id=None):
    """A telemetry outage must not break an otherwise successful resume operation."""
    try:
        store = get_quality_store()
        store.ensure_run(job)
        store.event(job.run_id, kind, version_id, target_hash, event_id)
    except Exception:
        logger.exception("Could not record quality event")
