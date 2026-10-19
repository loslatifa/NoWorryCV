"""Version-bound material packs with optimistic edits and run-scoped retention."""
from contextlib import contextmanager
from functools import lru_cache
from io import BytesIO
from pathlib import Path
import sqlite3
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from backend.app.agents.materials import MaterialsAgent, collect_evidence, compose_documents, review_document
from backend.app.core.config import get_settings
from backend.app.schemas.material import MaterialPack, MaterialSummary
from backend.app.services.interviews import utc_now
from backend.app.services.provenance import capture_provenance


class MaterialConflict(ValueError):
    pass


def generate_pack(job, version):
    result = job.result
    facts = [item.model_copy(deep=True) for item in result.fact_cards if item.confirmed]
    evidence = collect_evidence(version.draft, facts)
    language = result.resolved_language if result.resolved_language in {"en", "zh"} else result.jd_profile.language
    language = "en" if language == "en" else "zh"
    plan, method = MaterialsAgent().select(evidence, version.draft, result.jd_profile, language)
    now = utc_now()
    role = job.target_job_title or result.jd_profile.job_title
    notes = ["材料中的经历原句复用已确认事实；模型只选择证据与顺序。手工编辑不会加入事实库。",
             "自我介绍时长为目标；事实较少时会缩短。项目细节、到岗时间和沟通记录缺失时保留待补充提示。"]
    if not evidence:
        notes.append("当前版本没有可追溯的已确认经历；材料仅包含沟通框架，请先补充并确认事实。")
    if language == "en" and any(any("\u4e00" <= char <= "\u9fff" for char in item.text) for item in evidence):
        notes.append("事实原句保持来源语言；英文模板中的中文经历请核对翻译后编辑保存。")
    return MaterialPack(id=str(uuid4()), run_id=job.run_id, version_id=version.id, version_label=version.label,
        created_at=now, updated_at=now, expires_at=job.expires_at, company=job.target_company, role=role,
        language=language, jd_text=job.jd_text, jd_profile=result.jd_profile.model_copy(deep=True),
        draft=version.draft.model_copy(deep=True), fact_cards=facts, evidence=evidence,
        documents=compose_documents(plan, evidence, job.target_company, role, result.candidate_profile.basics.name or "", language),
        notes=notes, method=method, provenance=capture_provenance("materials"))


class MaterialStore:
    def __init__(self, path):
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        self.path = str(path)
        with self.connection() as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS materials (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, expires_at TEXT NOT NULL, pack_json TEXT NOT NULL)")
            connection.execute("CREATE INDEX IF NOT EXISTS materials_run ON materials(run_id)")

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

    def create(self, pack):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            count = connection.execute("SELECT COUNT(*) FROM materials WHERE run_id = ? AND expires_at > ?", (pack.run_id, utc_now())).fetchone()[0]
            if count >= 20:
                raise MaterialConflict("每个任务最多保存 20 套材料，请删除不再使用的材料包。")
            connection.execute("INSERT INTO materials VALUES (?, ?, ?, ?)", (pack.id, pack.run_id, pack.expires_at, pack.model_dump_json()))
        return pack

    def _get(self, connection, run_id, pack_id):
        row = connection.execute("SELECT pack_json FROM materials WHERE id = ? AND run_id = ? AND expires_at > ?", (pack_id, run_id, utc_now())).fetchone()
        return MaterialPack.model_validate_json(row[0]) if row else None

    def get(self, run_id, pack_id):
        with self.connection() as connection:
            return self._get(connection, run_id, pack_id)

    def list(self, run_id):
        with self.connection() as connection:
            rows = connection.execute("SELECT pack_json FROM materials WHERE run_id = ? AND expires_at > ? ORDER BY rowid DESC", (run_id, utc_now())).fetchall()
        packs = [MaterialPack.model_validate_json(row[0]) for row in rows]
        return [MaterialSummary(**pack.model_dump(include={"id", "version_id", "version_label", "created_at", "updated_at", "revision"}),
            reviewed_count=sum(item.reviewed for item in pack.documents), document_count=len(pack.documents)) for pack in packs]

    def edit(self, run_id, pack_id, document_id, payload):
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            pack = self._get(connection, run_id, pack_id)
            if pack is None:
                return None
            if pack.revision != payload.expected_revision:
                raise MaterialConflict("材料已在其他页面更新，请保留未保存文字，再重新载入。")
            doc = next((item for item in pack.documents if item.id == document_id), None)
            if doc is None:
                return None
            if doc.content == payload.content and doc.reviewed == payload.reviewed:
                return pack
            doc.content = payload.content
            doc.edited = doc.content != doc.original_content
            doc.reviewed = payload.reviewed
            doc.issues = review_document(doc, doc.content, pack)
            pack.revision += 1; pack.updated_at = utc_now()
            connection.execute("UPDATE materials SET pack_json = ? WHERE id = ?", (pack.model_dump_json(), pack.id))
            return pack

    def delete(self, run_id, pack_id):
        with self.connection() as connection:
            return bool(connection.execute("DELETE FROM materials WHERE run_id = ? AND id = ?", (run_id, pack_id)).rowcount)

    def delete_for_run(self, run_id):
        with self.connection() as connection:
            connection.execute("DELETE FROM materials WHERE run_id = ?", (run_id,))

    def cleanup_expired(self):
        with self.connection() as connection:
            return connection.execute("DELETE FROM materials WHERE expires_at <= ?", (utc_now(),)).rowcount


def material_markdown(pack, document):
    lines = [f"# {document.title}", f"目标公司：{pack.company or '未提供'}", f"目标岗位：{pack.role}",
             f"源任务：{pack.run_id}", f"简历版本：{pack.version_label} ({pack.version_id})",
             f"材料包：{pack.id} · 修订 {pack.revision}", "", document.content, "", "## 核对与来源",
             f"本人核对：{'已确认' if document.reviewed else '尚未确认'}；{'已手工编辑，原引用不证明新增表达' if document.edited else '事实原句复用'}。"]
    if document.length_hint:
        lines.append(document.length_hint)
    for issue in document.issues:
        lines.append(f"- {issue.quote + '：' if issue.quote else ''}{issue.reason}")
    for evidence in pack.evidence:
        if evidence.id in document.evidence_ids:
            lines += [f"- 事实 [{', '.join(evidence.fact_ids)}]：{evidence.text}",
                      f"  简历位置 {evidence.resume_span}：{evidence.resume_text}"]
    lines += ["", "## 目标 JD", pack.jd_text or pack.jd_profile.model_dump_json(indent=2)]
    return "\n".join(lines).strip()


def pack_zip(pack):
    output = BytesIO()
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for doc in pack.documents:
            archive.writestr(doc.id + ".md", material_markdown(pack, doc))
        archive.writestr("README.md", "# 岗位求职材料包\n\n" + "\n\n".join(pack.notes) + "\n\n每份材料附来源版本、事实引用和原 JD。\n")
    return output.getvalue()


@lru_cache
def get_material_store():
    return MaterialStore(get_settings().material_store_path)
