from typing import List, Union

from backend.app.schemas.agent_outputs import PartialRewriteOutput
from backend.app.schemas.common import TraceabilityRecord
from backend.app.schemas.run_state import PartialRewriteRequest
from backend.app.schemas.strategy import ResumeDraft


VALID_PARTIAL_TARGETS = {"summary", "skills", "experience_bullet", "project_bullet"}


def normalize_manual_draft(previous: ResumeDraft, edited: ResumeDraft) -> ResumeDraft:
    draft = edited.model_copy(deep=True)
    changed_spans = set()
    for section_name in ("experience_section", "project_section"):
        previous_sections = getattr(previous, section_name)
        edited_sections = getattr(draft, section_name)
        max_sections = max(len(previous_sections), len(edited_sections))
        for section_index in range(max_sections):
            previous_bullets = previous_sections[section_index].bullets if section_index < len(previous_sections) else []
            edited_bullets = edited_sections[section_index].bullets if section_index < len(edited_sections) else []
            max_bullets = max(len(previous_bullets), len(edited_bullets))
            for bullet_index in range(max_bullets):
                old_value = previous_bullets[bullet_index] if bullet_index < len(previous_bullets) else None
                new_value = edited_bullets[bullet_index] if bullet_index < len(edited_bullets) else None
                if old_value != new_value:
                    changed_spans.add(_trace_span(section_name, section_index, bullet_index))
    draft.traceability = [
        record for record in draft.traceability if record.draft_span not in changed_spans
    ]
    draft.markdown = render_draft_markdown(draft)
    return draft


def get_partial_target_value(request: PartialRewriteRequest) -> Union[str, List[str]]:
    if request.target_type == "headline":
        return request.draft.headline
    if request.target_type == "summary":
        return request.draft.summary
    if request.target_type == "skills":
        return request.draft.skills_section
    if request.target_type == "experience_bullet":
        return _get_bullet(request.draft.experience_section, request.section_index, request.item_index)
    if request.target_type == "project_bullet":
        return _get_bullet(request.draft.project_section, request.section_index, request.item_index)
    raise ValueError("Unsupported partial rewrite target.")


def apply_partial_rewrite(
    request: PartialRewriteRequest,
    output: PartialRewriteOutput,
) -> ResumeDraft:
    draft = request.draft.model_copy(deep=True)
    if request.target_type == "headline":
        draft.headline = output.replacement_text.strip()
    elif request.target_type == "summary":
        draft.summary = output.replacement_text.strip()
    elif request.target_type == "skills":
        draft.skills_section = [item.strip() for item in output.replacement_items if item.strip()]
    elif request.target_type == "experience_bullet":
        _set_bullet(draft.experience_section, request.section_index, request.item_index, output.replacement_text)
        _replace_traceability(draft, request, output.fact_ids)
    elif request.target_type == "project_bullet":
        _set_bullet(draft.project_section, request.section_index, request.item_index, output.replacement_text)
        _replace_traceability(draft, request, output.fact_ids)
    else:
        raise ValueError("Unsupported partial rewrite target.")
    draft.markdown = render_draft_markdown(draft)
    return draft


def render_draft_markdown(draft: ResumeDraft) -> str:
    all_text = " ".join(
        [draft.headline, draft.summary]
        + draft.skills_section
        + [item.heading for item in draft.experience_section + draft.project_section]
    )
    is_zh = any("\u4e00" <= character <= "\u9fff" for character in all_text)
    labels = {
        "summary": "个人摘要" if is_zh else "Summary",
        "skills": "技能" if is_zh else "Skills",
        "experience": "工作经历" if is_zh else "Experience",
        "projects": "项目经历" if is_zh else "Projects",
        "education": "教育背景" if is_zh else "Education",
    }
    lines = ["# {0}".format(draft.headline.strip())] if draft.headline.strip() else []
    if draft.summary.strip():
        lines.extend(["", "## {0}".format(labels["summary"]), draft.summary.strip()])
    if draft.skills_section:
        lines.extend(["", "## {0}".format(labels["skills"]), ", ".join(draft.skills_section)])
    _append_sections(lines, labels["experience"], draft.experience_section)
    _append_sections(lines, labels["projects"], draft.project_section)
    if draft.education_section:
        lines.extend(["", "## {0}".format(labels["education"])])
        lines.extend("- {0}".format(item.strip()) for item in draft.education_section if item.strip())
    return "\n".join(lines).strip()


def trace_span_for_request(request: PartialRewriteRequest) -> str:
    section_name = "experience_section" if request.target_type == "experience_bullet" else "project_section"
    return _trace_span(section_name, request.section_index or 0, request.item_index or 0)


def _trace_span(section_name: str, section_index: int, bullet_index: int) -> str:
    return "{0}.{1}.bullets.{2}".format(section_name, section_index + 1, bullet_index + 1)


def _get_bullet(sections, section_index, item_index) -> str:
    if section_index is None or item_index is None:
        raise ValueError("Section and item indexes are required for bullet rewrites.")
    try:
        return sections[section_index].bullets[item_index]
    except IndexError as exc:
        raise ValueError("Partial rewrite target is out of range.") from exc


def _set_bullet(sections, section_index, item_index, value: str) -> None:
    if section_index is None or item_index is None:
        raise ValueError("Section and item indexes are required for bullet rewrites.")
    try:
        sections[section_index].bullets[item_index] = value.strip()
    except IndexError as exc:
        raise ValueError("Partial rewrite target is out of range.") from exc


def _replace_traceability(
    draft: ResumeDraft,
    request: PartialRewriteRequest,
    fact_ids: List[str],
) -> None:
    span = trace_span_for_request(request)
    draft.traceability = [record for record in draft.traceability if record.draft_span != span]
    draft.traceability.append(TraceabilityRecord(draft_span=span, fact_ids=fact_ids))


def _append_sections(lines: List[str], label: str, sections) -> None:
    if not sections:
        return
    lines.extend(["", "## {0}".format(label)])
    for section in sections:
        lines.append("### {0}".format(section.heading.strip()))
        if section.subheading and section.subheading.strip():
            lines.append(section.subheading.strip())
        lines.extend("- {0}".format(bullet.strip()) for bullet in section.bullets if bullet.strip())
        lines.append("")
