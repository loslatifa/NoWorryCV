from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
from hmac import compare_digest
import json
from pathlib import Path
import secrets
import sqlite3
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.schemas.profile import CandidateArchive, CandidateArchiveSave
from backend.app.services.confirmed_profile import align_confirmed_profile


class ProfileRevisionConflict(ValueError):
    pass


class CandidateArchiveStore:
    """Private, explicitly saved archives; the bearer credential identifies the owner."""

    def __init__(self, database_path: str):
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS candidate_archives (
                    id TEXT PRIMARY KEY,
                    token_hash TEXT NOT NULL,
                    archive_json TEXT NOT NULL
                )
            """)

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(str(self._path), timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA secure_delete=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @staticmethod
    def _hash_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def _authorized_archive(self, connection, archive_id: str, token: str):
        row = connection.execute(
            "SELECT token_hash, archive_json FROM candidate_archives WHERE id = ?", (archive_id,)
        ).fetchone()
        if row is None or not token or not compare_digest(row["token_hash"], self._hash_token(token)):
            return None
        return CandidateArchive.model_validate_json(row["archive_json"])

    def create(self, payload: CandidateArchiveSave) -> CandidateArchive:
        now = datetime.now(timezone.utc).isoformat()
        token = secrets.token_urlsafe(32)
        archive = CandidateArchive(
            id=str(uuid4()), label=payload.label.strip(), revision=1,
            created_at=now, updated_at=now,
            candidate_profile=payload.candidate_profile.model_copy(deep=True),
            fact_cards=[fact.model_copy(deep=True) for fact in payload.fact_cards],
        )
        align_confirmed_profile(archive.candidate_profile, archive.fact_cards)
        with self._connection() as connection:
            connection.execute(
                "INSERT INTO candidate_archives VALUES (?, ?, ?)",
                (archive.id, self._hash_token(token), archive.model_dump_json()),
            )
        return archive.model_copy(update={"access_token": token}, deep=True)

    def get_authorized(self, archive_id: str, token: str):
        with self._connection() as connection:
            return self._authorized_archive(connection, archive_id, token)

    def update_authorized(self, archive_id: str, token: str, payload: CandidateArchiveSave):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            archive = self._authorized_archive(connection, archive_id, token)
            if archive is None:
                return None
            if payload.expected_revision != archive.revision:
                raise ProfileRevisionConflict("基础档案已更新，请重新载入后再保存。")
            candidate = payload.candidate_profile.model_copy(deep=True)
            align_confirmed_profile(candidate, payload.fact_cards)
            # Re-saving identical confirmed material need not invalidate existing resumes.
            changed = (
                archive.candidate_profile != candidate
                or archive.fact_cards != payload.fact_cards
            )
            archive.label = payload.label.strip()
            archive.candidate_profile = candidate
            archive.fact_cards = [fact.model_copy(deep=True) for fact in payload.fact_cards]
            archive.revision += int(changed)
            archive.updated_at = datetime.now(timezone.utc).isoformat()
            connection.execute(
                "UPDATE candidate_archives SET archive_json = ? WHERE id = ?",
                (archive.model_dump_json(), archive_id),
            )
            return archive

    def save_preferences(self, archive_id, token, payload):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            archive = self._authorized_archive(connection, archive_id, token)
            if archive is None:
                return None
            if archive.preferences_revision != payload.expected_preferences_revision:
                raise ProfileRevisionConflict("常用偏好已更新，请重新载入后再保存。")
            if archive.preferences != payload.preferences:
                archive.preferences = payload.preferences.model_copy(deep=True)
                archive.preferences_revision += 1
                archive.updated_at = datetime.now(timezone.utc).isoformat()
                connection.execute("UPDATE candidate_archives SET archive_json = ? WHERE id = ?",
                                   (archive.model_dump_json(), archive_id))
            return archive

    def delete_authorized(self, archive_id: str, token: str) -> bool:
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            if self._authorized_archive(connection, archive_id, token) is None:
                return False
            connection.execute("DELETE FROM candidate_archives WHERE id = ?", (archive_id,))
            return True


def archive_resume_text(archive: CandidateArchive) -> str:
    """A readable input derived from saved material, without requiring the upload again."""
    return json.dumps({
        "candidate_profile": archive.candidate_profile.model_dump(mode="json"),
        "confirmed_facts": [fact.text for fact in archive.fact_cards],
    }, ensure_ascii=False)


@lru_cache
def get_candidate_archive_store() -> CandidateArchiveStore:
    return CandidateArchiveStore(get_settings().candidate_archive_path)


def reset_candidate_archive_store_cache() -> None:
    get_candidate_archive_store.cache_clear()
