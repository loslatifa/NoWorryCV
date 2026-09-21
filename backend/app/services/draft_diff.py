from typing import Dict, List, Optional

from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from backend.app.schemas.diff import DraftDiffItem, DraftDiffResponse
from backend.app.schemas.strategy import ResumeDraft
from backend.app.services.scoring.heuristics import normalize_token


def build_draft_diff(
    candidate: CandidateProfile,
    fact_cards: List[FactCard],
    draft: ResumeDraft,
) -> DraftDiffResponse:
    items: List[DraftDiffItem] = []
    fact_lookup = {card.id: card for card in fact_cards}
    trace_lookup = {record.draft_span: record.fact_ids for record in draft.traceability}
    used_fact_ids = set()

    items.extend(_summary_diff(candidate, draft))
    items.extend(_headline_diff(candidate, draft))

    for section_name, target_type, label in (
        ("experience_section", "experience_bullet", "工作经历"),
        ("project_section", "project_bullet", "项目经历"),
    ):
        sections = getattr(draft, section_name)
        for section_index, section in enumerate(sections):
            for item_index, revised_text in enumerate(section.bullets):
                if not revised_text.strip():
                    continue
                span = "{0}.{1}.bullets.{2}".format(section_name, section_index + 1, item_index + 1)
                fact_ids = [fact_id for fact_id in trace_lookup.get(span, []) if fact_id in fact_lookup]
                used_fact_ids.update(fact_ids)
                source_excerpts = _source_excerpts(fact_ids, fact_lookup)
                original_text = source_excerpts[0] if source_excerpts else ""
                if original_text and normalize_token(original_text) == normalize_token(revised_text):
                    continue
                grounded = bool(fact_ids)
                items.append(
                    DraftDiffItem(
                        id="draft:{0}".format(span),
                        change_type="modified" if grounded else "added",
                        target_type=target_type,
                        label="{0} · {1}".format(label, section.heading),
                        original_text=original_text,
                        revised_text=revised_text,
                        draft_span=span,
                        section_index=section_index,
                        item_index=item_index,
                        fact_ids=fact_ids,
                        source_excerpts=source_excerpts,
                        risk_level="low" if grounded else "high",
                        risk_message=(
                            "已映射到用户确认的事实。"
                            if grounded
                            else "该内容没有事实卡溯源，保存前需要人工确认或删除。"
                        ),
                    )
                )

    skill_facts = {normalize_token(card.text): card for card in fact_cards if card.category == "skill"}
    for item_index, skill in enumerate(draft.skills_section):
        key = normalize_token(skill)
        card = skill_facts.get(key)
        if card:
            used_fact_ids.add(card.id)
            continue
        items.append(
            DraftDiffItem(
                id="draft:skills:{0}".format(item_index),
                change_type="added",
                target_type="skill",
                label="技能",
                revised_text=skill,
                item_index=item_index,
                risk_level="high",
                risk_message="该技能没有已确认的事实卡支撑。",
            )
        )

    education_facts = {
        normalize_token(card.text): card for card in fact_cards if card.category == "education"
    }
    for item_index, education in enumerate(draft.education_section):
        key = normalize_token(education)
        card = education_facts.get(key)
        if card:
            used_fact_ids.add(card.id)
            continue
        closest = _closest_fact(education, list(education_facts.values()))
        if closest:
            used_fact_ids.add(closest.id)
            source = closest.source_excerpt or closest.text
            items.append(
                DraftDiffItem(
                    id="draft:education:{0}".format(item_index),
                    change_type="modified",
                    target_type="education",
                    label="教育背景",
                    original_text=source,
                    revised_text=education,
                    item_index=item_index,
                    fact_ids=[closest.id],
                    source_excerpts=[source],
                    risk_message="已映射到最接近的教育事实。",
                )
            )
        else:
            items.append(
                DraftDiffItem(
                    id="draft:education:{0}".format(item_index),
                    change_type="added",
                    target_type="education",
                    label="教育背景",
                    revised_text=education,
                    item_index=item_index,
                    risk_level="high",
                    risk_message="该教育信息没有已确认的事实卡支撑。",
                )
            )

    for card in fact_cards:
        if card.id in used_fact_ids:
            continue
        removed_item = _removed_fact_item(card, candidate, draft)
        if removed_item:
            items.append(removed_item)

    return DraftDiffResponse(
        items=items,
        added_count=sum(item.change_type == "added" for item in items),
        modified_count=sum(item.change_type == "modified" for item in items),
        removed_count=sum(item.change_type == "removed" for item in items),
        ungrounded_count=sum(item.risk_level == "high" for item in items),
    )


def _summary_diff(candidate: CandidateProfile, draft: ResumeDraft) -> List[DraftDiffItem]:
    original = (candidate.summary or "").strip()
    revised = (draft.summary or "").strip()
    if normalize_token(original) == normalize_token(revised):
        return []
    change_type = "modified" if original and revised else "added" if revised else "removed"
    return [
        DraftDiffItem(
            id="draft:summary",
            change_type=change_type,
            target_type="summary",
            label="个人摘要",
            original_text=original,
            revised_text=revised,
            risk_level="medium",
            risk_message="摘要是综合表达，请结合下方事实来源人工确认。",
        )
    ]


def _headline_diff(candidate: CandidateProfile, draft: ResumeDraft) -> List[DraftDiffItem]:
    original = (candidate.basics.name or "").strip()
    revised = (draft.headline or "").strip()
    if not revised or normalize_token(original) == normalize_token(revised):
        return []
    return [
        DraftDiffItem(
            id="draft:headline",
            change_type="modified" if original else "added",
            target_type="headline",
            label="标题",
            original_text=original,
            revised_text=revised,
            risk_level="low",
            risk_message="标题包含目标岗位语境，不代表新增候选人经历。",
        )
    ]


def _removed_fact_item(
    card: FactCard,
    candidate: CandidateProfile,
    draft: ResumeDraft,
) -> Optional[DraftDiffItem]:
    target_type = ""
    restore_section_index = None
    if card.category == "work_bullet":
        target_type = "experience_removed"
        label = "删除 · 工作经历"
        restore_section_index = _find_work_section(card, candidate, draft)
    elif card.category == "project_bullet":
        target_type = "project_removed"
        label = "删除 · 项目经历"
        restore_section_index = _find_project_section(card, candidate, draft)
    elif card.category == "skill":
        target_type = "skill_removed"
        label = "删除 · 技能"
    elif card.category == "education":
        target_type = "education_removed"
        label = "删除 · 教育背景"
    else:
        return None
    source = card.source_excerpt or card.text
    return DraftDiffItem(
        id="removed:{0}".format(card.id),
        change_type="removed",
        target_type=target_type,
        label=label,
        original_text=source,
        restore_section_index=restore_section_index,
        fact_ids=[card.id],
        source_excerpts=[source],
        risk_message="该事实未出现在当前定制版本中。",
    )


def _find_work_section(card: FactCard, candidate: CandidateProfile, draft: ResumeDraft) -> Optional[int]:
    experience_id = _source_entity_id(card.source_span, "work_experiences")
    experience = next((item for item in candidate.work_experiences if item.id == experience_id), None)
    if experience is None:
        return 0 if draft.experience_section else None
    signals = {normalize_token(experience.title or ""), normalize_token(experience.company or "")}
    for index, section in enumerate(draft.experience_section):
        if signals & {normalize_token(section.heading), normalize_token(section.subheading or "")}:
            return index
    return 0 if draft.experience_section else None


def _find_project_section(card: FactCard, candidate: CandidateProfile, draft: ResumeDraft) -> Optional[int]:
    project_id = _source_entity_id(card.source_span, "projects")
    project = next((item for item in candidate.projects if item.id == project_id), None)
    if project is None:
        return 0 if draft.project_section else None
    for index, section in enumerate(draft.project_section):
        if normalize_token(section.heading) == normalize_token(project.name):
            return index
    return 0 if draft.project_section else None


def _source_entity_id(source_span: str, prefix: str) -> str:
    parts = (source_span or "").split(".")
    return parts[1] if len(parts) > 1 and parts[0] == prefix else ""


def _source_excerpts(fact_ids: List[str], fact_lookup: Dict[str, FactCard]) -> List[str]:
    values = []
    for fact_id in fact_ids:
        card = fact_lookup[fact_id]
        value = (card.source_excerpt or card.text).strip()
        if value and value not in values:
            values.append(value)
    return values


def _closest_fact(text: str, cards: List[FactCard]) -> Optional[FactCard]:
    normalized = normalize_token(text)
    for card in cards:
        candidate = normalize_token(card.text)
        if candidate and (candidate in normalized or normalized in candidate):
            return card
    return None
