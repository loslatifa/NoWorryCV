from fastapi import APIRouter
from fastapi.responses import Response

from backend.app.schemas.preferences import ResumeTemplateId
from backend.app.services.template_catalog import import_issues, public_templates, sample_pdf

router = APIRouter(prefix="/resume-templates", tags=["resume-templates"])


@router.get("")
def list_templates():
    return {"templates": public_templates(), "issues": import_issues()}


@router.get("/{template_id}/preview")
def preview_template(template_id: ResumeTemplateId):
    return Response(
        content=sample_pdf(template_id), media_type="application/pdf",
        headers={"Content-Disposition": "inline; filename=template-example.pdf",
                 "Cache-Control": "public, max-age=86400", "X-Resume-Template": template_id},
    )
