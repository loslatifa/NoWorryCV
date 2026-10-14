from backend.app.schemas.history import VersionDifference
from backend.app.schemas.strategy import ResumeDraft


def _fields(draft: ResumeDraft):
    fields = {
        "headline": ("标题", draft.headline),
        "summary": ("个人摘要", draft.summary),
        "skills_section": ("技能", "\n".join(draft.skills_section)),
        "education_section": ("教育背景", "\n".join(draft.education_section)),
    }
    for kind, label in (("experience_section", "工作经历"), ("project_section", "项目经历")):
        for index, section in enumerate(getattr(draft, kind)):
            fields[f"{kind}.{index}"] = (
                f"{label} · 第 {index + 1} 条",
                "\n".join([section.heading, section.subheading or ""] + section.bullets).strip(),
            )
    return fields


def compare_versions(before: ResumeDraft, after: ResumeDraft):
    before_fields, after_fields = _fields(before), _fields(after)
    differences = []
    for field in dict.fromkeys(list(before_fields) + list(after_fields)):
        before_field = before_fields.get(field)
        after_field = after_fields.get(field)
        label = before_field[0] if before_field else after_field[0]
        before_text = before_field[1] if before_field else ""
        after_text = after_field[1] if after_field else ""
        if before_text == after_text:
            continue
        differences.append(VersionDifference(
            field=field, label=label, before_text=before_text, after_text=after_text,
            change_type="modified" if before_text and after_text else "added" if after_text else "removed",
        ))
    return differences
