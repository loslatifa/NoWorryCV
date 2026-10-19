from typing import Optional

from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response

from backend.app.api.v1.routes import _get_authorized_run
from backend.app.schemas.material import MaterialEdit, MaterialPack, MaterialStart, MaterialSummary
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.materials import MaterialConflict, generate_pack, get_material_store, material_markdown, pack_zip
from backend.app.services.runs.store import get_run_store

router = APIRouter(prefix="/tailor-runs/{run_id}/materials", tags=["application-materials"])


def get_pack(run_id, pack_id, token):
    _get_authorized_run(run_id, token)
    pack = get_material_store().get(run_id, pack_id)
    if pack is None:
        raise HTTPException(404, "材料包不存在或已过期。")
    return pack


@router.post("", response_model=MaterialPack, status_code=201)
def create_materials(run_id: str, payload: MaterialStart, x_run_token: Optional[str] = Header(None)):
    job = _get_authorized_run(run_id, x_run_token)
    if job.result is None:
        raise HTTPException(409, "请先完成简历生成并保存版本。")
    version = next((item for item in job.result.draft_versions if item.id == payload.version_id), None)
    if version is None:
        raise HTTPException(404, "已保存的简历版本不存在。")
    if len(get_material_store().list(run_id)) >= 20:
        raise HTTPException(409, "每个任务最多保存 20 套材料，请删除不再使用的材料包。")
    try:
        pack = generate_pack(job, version)
        if get_run_store().get_authorized(run_id, x_run_token) is None:
            raise HTTPException(404, "任务已删除或过期。")
        get_material_store().create(pack)
    except StructuredLLMError as exc:
        raise HTTPException(503, "材料生成模型暂时不可用，请稍后重试；未保存新的材料包。") from exc
    except MaterialConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if get_run_store().get(run_id) is None:
        get_material_store().delete_for_run(run_id)
        raise HTTPException(404, "任务已删除或过期。")
    return pack


@router.get("", response_model=list[MaterialSummary])
def list_materials(run_id: str, x_run_token: Optional[str] = Header(None)):
    _get_authorized_run(run_id, x_run_token)
    return get_material_store().list(run_id)


@router.get("/{pack_id}", response_model=MaterialPack)
def read_materials(run_id: str, pack_id: str, x_run_token: Optional[str] = Header(None)):
    return get_pack(run_id, pack_id, x_run_token)


@router.put("/{pack_id}/documents/{document_id}", response_model=MaterialPack)
def edit_material(run_id: str, pack_id: str, document_id: str, payload: MaterialEdit, x_run_token: Optional[str] = Header(None)):
    get_pack(run_id, pack_id, x_run_token)
    try:
        pack = get_material_store().edit(run_id, pack_id, document_id, payload)
    except MaterialConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    if pack is None:
        raise HTTPException(404, "材料不存在或已过期。")
    return pack


@router.get("/{pack_id}/documents/{document_id}/export")
def export_document(run_id: str, pack_id: str, document_id: str, x_run_token: Optional[str] = Header(None)):
    pack = get_pack(run_id, pack_id, x_run_token)
    doc = next((item for item in pack.documents if item.id == document_id), None)
    if doc is None:
        raise HTTPException(404, "材料不存在。")
    if not doc.reviewed:
        raise HTTPException(409, "请先核对并保存这份材料，再导出。")
    return Response(material_markdown(pack, doc), media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{doc.id}.md"', "Cache-Control": "no-store"})


@router.get("/{pack_id}/export")
def export_pack(run_id: str, pack_id: str, x_run_token: Optional[str] = Header(None)):
    pack = get_pack(run_id, pack_id, x_run_token)
    if any(not doc.reviewed for doc in pack.documents):
        raise HTTPException(409, "请逐份核对并保存全部材料，再下载整包。")
    return Response(pack_zip(pack), media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="application-materials.zip"', "Cache-Control": "no-store"})


@router.delete("/{pack_id}", status_code=204)
def delete_materials(run_id: str, pack_id: str, x_run_token: Optional[str] = Header(None)):
    get_pack(run_id, pack_id, x_run_token)
    get_material_store().delete(run_id, pack_id)
    return Response(status_code=204)
