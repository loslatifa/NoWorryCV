"""Content-free, versioned resume layouts. Never load source resumes at runtime."""
from functools import lru_cache
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "assets/resume_templates/catalog.json"
BASE = {
    "active": True, "source_filename": None, "adaptation": "builtin",
    "accent": "000000", "font": "Heiti SC", "body_size": 10.25,
    "title_size": 16, "heading_size": 11.5, "title_align": "left",
    "heading_bar": False, "section_gap": 6, "margin_x": 44.64, "margin_y": 39.6,
    "suggested_pages": 1,
    "section_order": ["summary", "skills", "experience", "projects", "education"],
}
_catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8")) if CATALOG_PATH.exists() else {"templates": [], "issues": []}
TEMPLATES = {
    "ats_standard": {**BASE, "id": "ats_standard", "name": "ATS 标准", "description": "黑白单栏，标准间距"},
    "ats_compact": {**BASE, "id": "ats_compact", "name": "ATS 紧凑", "description": "黑白单栏，更紧凑的间距", "section_gap": 4},
    **{item["id"]: item for item in _catalog["templates"]},
}
TEMPLATE_OPTIONS = {key: value["name"] for key, value in TEMPLATES.items()}


def template_style(template_id):
    return TEMPLATES[template_id]


def heading_background(layout):
    # Dark text remains readable in viewers that omit paragraph backgrounds.
    return "".join("{0:02X}".format(round(255 * .88 + int(layout["accent"][index:index + 2], 16) * .12))
                   for index in (0, 2, 4))


def public_templates():
    return [
        {key: item[key] for key in ("id", "name", "description", "source_filename", "active", "adaptation", "suggested_pages")}
        | {"thumbnail_url": "/app/templates/{0}.png".format(item["id"]),
           "preview_url": "/api/v1/resume-templates/{0}/preview".format(item["id"])}
        for item in TEMPLATES.values()
    ]


def import_issues():
    return _catalog.get("issues", [])


@lru_cache(maxsize=64)
def sample_pdf(template_id, region="CN"):
    # Local imports avoid a cycle with the preference schema.
    from backend.app.schemas.preferences import ResumePreferences
    from backend.app.schemas.candidate import CandidateBasics, CandidateProfile
    from backend.app.schemas.strategy import ResumeDraft, ResumeSectionItem
    from backend.app.services.resume_export import build_pdf
    candidate = CandidateProfile(basics=CandidateBasics(
        name="示例姓名", email="resume@example.com", phone="13800000000", location="上海",
    ))
    draft = ResumeDraft(
        headline="示例姓名 产品经理",
        summary="关注产品体验与数据分析，能够结合用户反馈梳理需求，并与团队协作推进产品迭代。参与需求调研、数据整理和方案复盘，重视清晰的沟通与完整的交付记录。",
        skills_section=["SQL", "Python", "Power BI", "A/B Testing", "用户研究", "跨团队协作"],
        experience_section=[ResumeSectionItem(
            heading="产品实习生", subheading="示例科技公司 2025.03 至 2025.08",
            bullets=["整理用户反馈并梳理需求优先级，与设计及研发团队协作跟进功能交付。",
                     "使用 SQL 分析产品使用情况，制作周报并支持团队讨论迭代方向。",
                     "参与实验方案设计与结果复盘，将分析结论整理为后续优化建议。"],
        ), ResumeSectionItem(
            heading="运营助理实习生", subheading="示例服务公司 2024.07 至 2024.10",
            bullets=["参与用户访谈资料整理，归纳常见使用问题并维护问题清单。",
                     "协助整理活动流程与执行记录，跟进跨团队协作事项并汇总反馈。",
                     "编写操作说明和常见问题文档，支持团队交接与后续维护。"],
        )],
        project_section=[ResumeSectionItem(
            heading="数据分析看板", subheading="课程项目 2024.09 至 2024.12",
            bullets=["整理公开数据并完成清洗，搭建可视化看板展示关键指标。",
                     "记录指标口径和分析过程，协作完成项目报告与演示。"],
        ), ResumeSectionItem(
            heading="校园服务需求研究", subheading="小组项目 2024.03 至 2024.06",
            bullets=["整理问卷与访谈记录，归纳校园服务的使用场景和常见需求。",
                     "协作绘制服务流程并提出改进方案，完成研究报告和小组展示。"],
        )],
        education_section=["示例大学 信息管理与信息系统 本科 2022.09 至 2026.06"],
    )
    return build_pdf(draft, candidate, ResumePreferences(template=template_id, region=region, language="zh"))
