"""Durable, owner-scoped snapshots of the resume explicitly approved for a job."""
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import sqlite3
from uuid import uuid4

from backend.app.core.config import get_settings
from backend.app.schemas.application import ApplicationRecord
from backend.app.services.draft_editing import render_draft_markdown


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def draft_digest(draft):
    return hashlib.sha256(json.dumps(draft.model_dump(mode="json"), ensure_ascii=False,
                                    sort_keys=True).encode("utf-8")).hexdigest()


def build_form_resume(candidate, draft, facts):
    """Join rewritten sections to source facts, never to their reordered position."""
    fact_lookup = {fact.id: fact for fact in facts}
    warnings = []

    def resolve(section, index, section_name, originals, source_name):
        prefix = "{0}.{1}.bullets.".format(section_name, index + 1)
        source_ids = set()
        for trace in draft.traceability:
            if trace.draft_span.startswith(prefix):
                for fact_id in trace.fact_ids:
                    fact = fact_lookup.get(fact_id)
                    if fact and fact.source_span.startswith(source_name + "."):
                        # IDs may contain dots; match against full source prefixes.
                        for original in originals:
                            if fact.source_span.startswith("{0}.{1}.".format(source_name, original.id)):
                                source_ids.add(original.id)
        matches = [item for item in originals if item.id in source_ids]
        if len(matches) == 1:
            return matches[0]
        if not source_ids:
            matches = [item for item in originals if (
                source_name == "projects" and item.name == section.heading
            ) or (source_name == "work_experiences" and (
                (item.title == section.heading and item.company == section.subheading)
                or (not item.title and item.company == section.heading)
            ))]
            if len(matches) == 1:
                return matches[0]
        warnings.append("无法唯一关联经历「{0}」，该经历的公司、角色和日期需人工补充。".format(section.heading))
        return None

    work = []
    for index, section in enumerate(draft.experience_section):
        original = resolve(section, index, "experience_section", candidate.work_experiences, "work_experiences")
        work.append({
            "company": original.company if original else "",
            "title": original.title if original else "",
            "start_date": original.start_date if original else "",
            "end_date": original.end_date if original else "",
            "description": "\n".join(section.bullets), "highlights": section.bullets,
        })
    projects = []
    for index, section in enumerate(draft.project_section):
        original = resolve(section, index, "project_section", candidate.projects, "projects")
        projects.append({
            "name": original.name if original else "", "role": original.role if original else "",
            "description": "\n".join(section.bullets), "highlights": section.bullets,
            "tech_stack": original.skills_used if original else [],
        })
    basics = candidate.basics
    education = [{"school": item.school, "degree": item.degree,
                  "major": item.field_of_study, "end_date": item.graduation_date}
                 for item in candidate.education]
    personal = {"name": basics.name, "email": basics.email, "phone": basics.phone,
                "location": basics.location, "city": basics.location}
    if education:
        personal.update({"school": education[0]["school"], "university": education[0]["school"],
                         "degree": education[0]["degree"], "graduation_date": education[0]["end_date"]})
    return {"personal_info": personal, "summary": draft.summary, "skills": draft.skills_section,
            "work_experience": work, "projects": projects, "education": education,
            "certifications": candidate.certifications,
            "resume_text": render_draft_markdown(draft)}, warnings


class ApplicationConflict(ValueError):
    pass


class ApplicationStore:
    def __init__(self, database_path):
        self._path = Path(database_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute("""CREATE TABLE IF NOT EXISTS applications (
                id TEXT PRIMARY KEY, profile_id TEXT NOT NULL, record_json TEXT NOT NULL)""")
            connection.execute("CREATE INDEX IF NOT EXISTS applications_owner ON applications(profile_id)")

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

    def create(self, profile_id, revision, run_id, payload, expires_at):
        now = utc_now()
        record = ApplicationRecord(
            id=str(uuid4()), profile_id=profile_id, profile_revision=revision, run_id=run_id,
            created_at=now, updated_at=now, page_url=str(payload.page_url),
            expires_at=expires_at, preferences=payload.preferences or {},
            job_url=str(payload.job_url or payload.page_url), jd_text=payload.jd_text.strip(),
            target_company=payload.target_company.strip(), target_role=payload.target_role.strip(),
        )
        with self._connection() as connection:
            connection.execute("INSERT INTO applications VALUES (?, ?, ?)",
                               (record.id, profile_id, record.model_dump_json()))
        return record

    def get(self, profile_id, application_id):
        with self._connection() as connection:
            row = connection.execute("SELECT record_json FROM applications WHERE id=? AND profile_id=?",
                                     (application_id, profile_id)).fetchone()
        return ApplicationRecord.model_validate_json(row[0]) if row else None

    def list(self, profile_id):
        with self._connection() as connection:
            rows = connection.execute("SELECT record_json FROM applications WHERE profile_id=? ORDER BY rowid DESC",
                                      (profile_id,)).fetchall()
        return [ApplicationRecord.model_validate_json(row[0]) for row in rows]

    def update(self, profile_id, application_id, mutate):
        with self._connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute("SELECT record_json FROM applications WHERE id=? AND profile_id=?",
                                     (application_id, profile_id)).fetchone()
            if not row:
                return None
            record = ApplicationRecord.model_validate_json(row[0])
            mutate(record)
            record.updated_at = utc_now()
            connection.execute("UPDATE applications SET record_json=? WHERE id=?",
                               (record.model_dump_json(), record.id))
        return record

    def delete(self, profile_id, application_id):
        with self._connection() as connection:
            return connection.execute("DELETE FROM applications WHERE id=? AND profile_id=?",
                                      (application_id, profile_id)).rowcount > 0

    def delete_for_profile(self, profile_id):
        with self._connection() as connection:
            connection.execute("DELETE FROM applications WHERE profile_id=?", (profile_id,))

    def cleanup_expired(self):
        now = utc_now()
        with self._connection() as connection:
            rows = connection.execute("SELECT id, record_json FROM applications").fetchall()
            for row in rows:
                record = ApplicationRecord.model_validate_json(row["record_json"])
                if not record.confirmed_at and record.expires_at and record.expires_at <= now:
                    connection.execute("DELETE FROM applications WHERE id=?", (record.id,))


@lru_cache
def get_application_store():
    return ApplicationStore(get_settings().application_store_path)
