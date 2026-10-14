from io import BytesIO

from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader

from backend.app.main import create_app
from backend.app.schemas.candidate import CandidateBasics, CandidateProfile
from backend.app.schemas.strategy import ResumeDraft, ResumeSectionItem
from backend.app.services.resume_export import (
    build_docx,
    build_pdf,
    draft_to_plain_text,
    pdf_page_count,
    sanitize_filename,
)
from backend.tests.test_draft_editing import _completed_run


def _sample_resume():
    candidate = CandidateProfile(
        basics=CandidateBasics(
            name="张三",
            email="zhangsan@example.com",
            phone="13800000000",
            location="上海",
        )
    )
    draft = ResumeDraft(
        headline="张三 产品经理",
        summary="三年产品与数据分析经验，擅长把分析结论转化为产品动作。",
        skills_section=["SQL", "Python", "A/B Testing"],
        experience_section=[
            ResumeSectionItem(
                heading="产品经理",
                subheading="示例科技 2022 至今",
                bullets=[
                    "使用 SQL 分析增长漏斗并定位转化问题。",
                    "设计 A/B 测试并基于实验结果推动产品优化。",
                ],
            )
        ],
        education_section=["示例大学 信息管理 本科 2022"],
    )
    return candidate, draft


def test_export_builders_create_readable_machine_parseable_files() -> None:
    candidate, draft = _sample_resume()

    plain_text = draft_to_plain_text(draft, candidate)
    docx_bytes = build_docx(draft, candidate)
    pdf_bytes = build_pdf(draft, candidate)

    assert "zhangsan@example.com" in plain_text
    assert "使用 SQL 分析增长漏斗" in plain_text

    document = Document(BytesIO(docx_bytes))
    docx_text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert document.sections[0].page_width.inches == 8.5
    assert document.sections[0].page_height.inches == 11
    assert "张三 产品经理" in docx_text
    assert "zhangsan@example.com" in docx_text
    assert "使用 SQL 分析增长漏斗" in docx_text

    reader = PdfReader(BytesIO(pdf_bytes))
    pdf_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert pdf_page_count(pdf_bytes) == 1
    assert "张三 产品经理" in pdf_text
    assert "zhangsan@example.com" in pdf_text
    assert "使用 SQL 分析增长漏斗" in pdf_text


def test_export_api_supports_preview_docx_pdf_and_chinese_filename() -> None:
    completed = _completed_run()
    client = TestClient(create_app())
    draft = completed.result.final_package.draft.model_dump(mode="json")
    request = {"draft": draft, "filename": "张三/产品经理.pdf"}
    headers = {"X-Run-Token": completed.access_token}

    preview = client.post(
        "/api/v1/tailor-runs/{0}/export-preview".format(completed.run_id),
        headers=headers,
        json=request,
    )
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "application/pdf"
    assert int(preview.headers["x-page-count"]) >= 1
    assert preview.headers["x-overflow"] in {"true", "false"}
    assert preview.content.startswith(b"%PDF")

    docx = client.post(
        "/api/v1/tailor-runs/{0}/export/docx".format(completed.run_id),
        headers=headers,
        json=request,
    )
    assert docx.status_code == 200
    assert docx.content.startswith(b"PK")
    assert "filename*=UTF-8''" in docx.headers["content-disposition"]
    assert "%E5%BC%A0%E4%B8%89-%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86.docx" in docx.headers[
        "content-disposition"
    ]

    pdf = client.post(
        "/api/v1/tailor-runs/{0}/export/pdf".format(completed.run_id),
        headers=headers,
        json=request,
    )
    assert pdf.status_code == 200
    assert pdf.content.startswith(b"%PDF")
    assert "%E5%BC%A0%E4%B8%89-%E4%BA%A7%E5%93%81%E7%BB%8F%E7%90%86.pdf" in pdf.headers[
        "content-disposition"
    ]


def test_export_preview_reports_multi_page_overflow() -> None:
    completed = _completed_run()
    client = TestClient(create_app())
    draft = completed.result.final_package.draft.model_copy(deep=True)
    draft.experience_section = [
        ResumeSectionItem(
            heading="数据分析师",
            subheading="示例科技",
            bullets=["这是用于验证分页溢出提示的较长经历描述。" * 5 for _ in range(50)],
        )
    ]

    response = client.post(
        "/api/v1/tailor-runs/{0}/export-preview".format(completed.run_id),
        headers={"X-Run-Token": completed.access_token},
        json={"draft": draft.model_dump(mode="json"), "filename": "多页简历"},
    )

    assert response.status_code == 200
    assert int(response.headers["x-page-count"]) > 1
    assert response.headers["x-overflow"] == "true"


def test_export_filename_sanitization_and_invalid_format() -> None:
    assert sanitize_filename(" ../张三:产品经理?.docx ") == "张三-产品经理"
    assert sanitize_filename("...") == "tailored-resume"

    completed = _completed_run()
    response = TestClient(create_app()).post(
        "/api/v1/tailor-runs/{0}/export/txt".format(completed.run_id),
        headers={"X-Run-Token": completed.access_token},
        json={
            "draft": completed.result.final_package.draft.model_dump(mode="json"),
            "filename": "resume",
        },
    )
    assert response.status_code == 400
