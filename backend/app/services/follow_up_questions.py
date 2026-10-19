from typing import List

from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.run_state import FollowUpQuestion
from backend.app.schemas.strategy import GapAnalysis
from backend.app.services.scoring.heuristics import normalize_token, unique_preserve_order


def build_follow_up_questions(
    candidate: CandidateProfile,
    fact_cards: List[FactCard],
    jd_profile: JDProfile,
    gap_analysis: GapAnalysis,
    limit: int = 5,
) -> List[FollowUpQuestion]:
    questions: List[FollowUpQuestion] = []
    known_text = normalize_token(" ".join(card.text for card in fact_cards))

    missing_keywords = unique_preserve_order(
        gap_analysis.missing_keywords + jd_profile.must_have_skills
    )
    for keyword in missing_keywords:
        normalized_keyword = normalize_token(keyword)
        if not normalized_keyword or normalized_keyword in known_text:
            continue
        questions.append(
            FollowUpQuestion(
                id="missing_skill_{0}".format(len(questions) + 1),
                prompt="是否希望补充与“{0}”相关的学习、项目或工作经历？可以描述具体场景、行动和结果。".format(
                    keyword
                ),
                reason="目标 JD 关注“{0}”，可以补充简历尚未展开的相关细节。".format(keyword),
                priority="recommended" if keyword in jd_profile.must_have_skills else "optional",
                suggested_category="general",
                related_keywords=[keyword],
            )
        )
        if len(questions) >= 2:
            break

    measurable_fact = _first_unquantified_impact_fact(fact_cards)
    if measurable_fact:
        questions.append(
            FollowUpQuestion(
                id="quantified_impact",
                prompt="关于“{0}”，是否希望补充规模或结果数据，例如用户量、转化率、效率、收入、成本或交付周期？".format(
                    measurable_fact.text
                ),
                reason="具体数据有助于呈现成果；没有可补充的数据时，保留原有描述即可。",
                priority="recommended",
                suggested_category="achievement",
            )
        )

    if candidate.work_experiences and not _has_scope_signal(fact_cards):
        questions.append(
            FollowUpQuestion(
                id="work_scope",
                prompt="是否希望补充最近一段工作的业务范围、协作团队或服务对象？",
                reason="这些背景有助于读者理解工作内容。",
                priority="optional",
                suggested_category="general",
            )
        )

    if jd_profile.hiring_track in {"campus", "intern"} and candidate.projects:
        questions.append(
            FollowUpQuestion(
                id="project_role",
                prompt="在最相关的项目中，你具体负责哪一部分？最终交付了什么，遇到过什么关键问题？",
                reason="补充项目分工和交付物，可以更具体地展示项目经验。",
                priority="recommended",
                suggested_category="project_bullet",
            )
        )
    elif jd_profile.hiring_track == "experienced" and candidate.work_experiences:
        questions.append(
            FollowUpQuestion(
                id="decision_ownership",
                prompt="是否希望补充相关工作中的关键决策、行动和负责内容？",
                reason="这些细节有助于呈现岗位相关的工作经验。",
                priority="recommended",
                suggested_category="work_bullet",
            )
        )

    return _deduplicate_questions(questions)[: max(0, min(limit, 5))]


def _first_unquantified_impact_fact(fact_cards: List[FactCard]):
    action_markers = ("负责", "推动", "搭建", "优化", "提升", "完成", "主导", "built", "improved", "led")
    for card in fact_cards:
        if card.category not in {"work_bullet", "project_bullet"}:
            continue
        if any(character.isdigit() for character in card.text):
            continue
        lowered = card.text.lower()
        if any(marker in card.text or marker in lowered for marker in action_markers):
            return card
    return None


def _has_scope_signal(fact_cards: List[FactCard]) -> bool:
    scope_markers = ("用户", "团队", "部门", "业务线", "地区", "客户", "人", "万", "million", "team", "users")
    return any(
        any(marker in card.text or marker in card.text.lower() for marker in scope_markers)
        for card in fact_cards
        if card.category in {"work_bullet", "project_bullet", "achievement", "general"}
    )


def _deduplicate_questions(questions: List[FollowUpQuestion]) -> List[FollowUpQuestion]:
    seen = set()
    deduplicated = []
    for question in questions:
        normalized = normalize_token(question.prompt)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduplicated.append(question)
    return deduplicated
