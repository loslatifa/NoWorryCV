from typing import Dict, Iterable, List

from backend.app.schemas.jd import JDProfile, KnowledgeReviewCard
from backend.app.services.scoring.heuristics import normalize_token, unique_preserve_order


TOPIC_LIBRARY: Dict[str, Dict[str, str]] = {
    "sql": {
        "title": "SQL 与数据口径",
        "focus_area": "硬技能",
        "why_it_matters": "JD 明确提到 SQL，说明岗位会看你是否能独立取数、拆指标并解释数据结论。",
        "review_tip": "回顾 JOIN、GROUP BY、窗口函数，以及你如何把分析结果转成业务动作。",
        "sample_question": "如果面试官让你讲一次用 SQL 发现问题并推动优化的经历，你会怎么回答？",
    },
    "a b testing": {
        "title": "A/B 测试与实验设计",
        "focus_area": "方法论",
        "why_it_matters": "岗位强调实验设计，通常意味着需要你能提出假设、定义指标并判断实验是否可信。",
        "review_tip": "复习实验假设、样本量、主指标、显著性，以及实验污染和干扰变量控制。",
        "sample_question": "请准备一个你如何设计实验、观察结果并做决策的真实案例。",
    },
    "user research": {
        "title": "用户研究与需求洞察",
        "focus_area": "用户洞察",
        "why_it_matters": "JD 提到用户研究，说明岗位需要你不只会执行，还能从访谈或反馈里提炼洞察。",
        "review_tip": "回顾用户分层、访谈提纲、信息归纳和洞察落地，不要把收集反馈等同于研究。",
        "sample_question": "如果面试官问你如何验证一个用户需求是否真实存在，你会怎么回答？",
    },
    "用户研究": {
        "title": "用户研究与需求洞察",
        "focus_area": "用户洞察",
        "why_it_matters": "JD 提到用户研究，说明岗位需要你不只会执行，还能从访谈或反馈里提炼洞察。",
        "review_tip": "回顾用户分层、访谈提纲、信息归纳和洞察落地，不要把收集反馈等同于研究。",
        "sample_question": "如果面试官问你如何验证一个用户需求是否真实存在，你会怎么回答？",
    },
    "数据分析": {
        "title": "数据分析与业务判断",
        "focus_area": "分析能力",
        "why_it_matters": "JD 提到数据分析，说明岗位会关注你是否能从指标波动中定位问题并给出判断。",
        "review_tip": "准备一个完整案例：问题定义、指标拆解、分析过程、结论和业务动作。",
        "sample_question": "请准备一个你如何通过数据分析发现问题并推动后续动作的案例。",
    },
    "data analysis": {
        "title": "数据分析与业务判断",
        "focus_area": "分析能力",
        "why_it_matters": "JD 提到数据分析，说明岗位会关注你是否能从指标波动中定位问题并给出判断。",
        "review_tip": "准备一个完整案例：问题定义、指标拆解、分析过程、结论和业务动作。",
        "sample_question": "请准备一个你如何通过数据分析发现问题并推动后续动作的案例。",
    },
    "增长": {
        "title": "增长漏斗与转化优化",
        "focus_area": "业务场景",
        "why_it_matters": "岗位强调增长时，面试通常会追问你如何理解漏斗、转化、留存和增长实验闭环。",
        "review_tip": "回顾 AARRR、关键漏斗节点、转化提升方法和留存分析思路。",
        "sample_question": "如果让你优化一个增长漏斗，你会先看哪些环节？",
    },
    "跨团队协作": {
        "title": "跨团队协作与推进",
        "focus_area": "协作能力",
        "why_it_matters": "JD 提到跨团队协作，通常意味着需要你能与研发、设计、运营等角色对齐目标并推进落地。",
        "review_tip": "回顾一个你如何推动多方协作、解决分歧并拿到结果的案例。",
        "sample_question": "如果项目推进中多个团队目标不一致，你会如何协调？",
    },
    "产品管理": {
        "title": "产品思考与优先级",
        "focus_area": "产品能力",
        "why_it_matters": "当 JD 关注产品能力时，面试往往会考察你如何定义问题、拆需求和做优先级判断。",
        "review_tip": "准备好讲清楚目标、约束、方案取舍和最终判断依据。",
        "sample_question": "如果资源有限，你会如何在多个需求之间做优先级排序？",
    },
    "Tableau": {
        "title": "可视化看板与指标呈现",
        "focus_area": "工具能力",
        "why_it_matters": "JD 提到 Tableau 或 BI 工具，通常意味着你需要把分析结果变成业务可用的看板和共识。",
        "review_tip": "回顾你如何定义核心指标、搭建仪表盘，以及如何推动业务方使用。",
        "sample_question": "如果要为业务团队搭一个看板，你会优先放哪些指标？",
    },
}


def build_review_cards(jd_profile: JDProfile, jd_text: str, max_cards: int = 5) -> List[KnowledgeReviewCard]:
    del jd_text
    topics = _collect_topics(jd_profile)
    cards: List[KnowledgeReviewCard] = []
    for index, topic in enumerate(topics[:max_cards], start=1):
        normalized = normalize_token(topic)
        template = _resolve_template(normalized)
        if template:
            cards.append(
                KnowledgeReviewCard(
                    id="review_{0}".format(index),
                    title=template["title"],
                    focus_area=template["focus_area"],
                    why_it_matters=template["why_it_matters"],
                    review_tip=template["review_tip"],
                    sample_question=template["sample_question"],
                    keywords=[topic],
                )
            )
            continue

        cards.append(
            KnowledgeReviewCard(
                id="review_{0}".format(index),
                title=topic,
                focus_area=_classify_topic(topic),
                why_it_matters="JD 明确提到了“{0}”，很可能会出现在简历筛选或面试追问里。".format(topic),
                review_tip="回顾你是否有与“{0}”直接相关的项目、方法、工具或结果，并准备 1 个真实案例。".format(topic),
                sample_question="如果面试官追问你在“{0}”上的实践，你会用什么事实来证明？".format(topic),
                keywords=[topic],
            )
        )
    return cards


def _collect_topics(jd_profile: JDProfile) -> List[str]:
    items: List[str] = []
    items.extend(jd_profile.must_have_skills)
    items.extend(jd_profile.nice_to_have_skills[:2])
    items.extend(jd_profile.domain_signals)
    items.extend(_responsibility_phrases(jd_profile.responsibilities))
    return [topic for topic in unique_preserve_order(items) if _is_card_worthy(topic)]


def _responsibility_phrases(responsibilities: Iterable[str]) -> List[str]:
    phrases: List[str] = []
    for responsibility in responsibilities:
        chunks = [chunk.strip() for chunk in responsibility.replace("，", "、").split("、") if chunk.strip()]
        for chunk in chunks:
            if len(chunk) <= 16:
                phrases.append(chunk)
    return phrases


def _resolve_template(normalized_topic: str):
    if normalized_topic in TOPIC_LIBRARY:
        return TOPIC_LIBRARY[normalized_topic]
    for key, template in TOPIC_LIBRARY.items():
        if key in normalized_topic or normalized_topic in key:
            return template
    return None


def _classify_topic(topic: str) -> str:
    normalized = normalize_token(topic)
    if normalized in {"sql", "python", "tableau", "excel", "power bi", "powerbi"}:
        return "硬技能"
    if normalized in {"增长", "数据分析", "用户研究"}:
        return "业务能力"
    if normalized in {"跨团队协作"}:
        return "协作能力"
    return "岗位知识点"


def _is_card_worthy(topic: str) -> bool:
    normalized = normalize_token(topic)
    if not normalized:
        return False
    if normalized.isdigit():
        return False
    if len(normalized) <= 1:
        return False
    noise = {
        "职责",
        "要求",
        "任职要求",
        "岗位职责",
        "加分项",
        "岗位",
        "2025",
        "2026",
        "2027",
    }
    return normalized not in noise
