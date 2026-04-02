from typing import Dict, Iterable, List

from backend.app.schemas.jd import JDProfile, KnowledgeReviewCard
from backend.app.services.scoring.heuristics import (
    canonicalize_skills,
    extract_known_skills,
    extract_tokens,
    normalize_token,
    unique_preserve_order,
)


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
    "tableau": {
        "title": "可视化看板与指标呈现",
        "focus_area": "工具能力",
        "why_it_matters": "JD 提到 Tableau 或 BI 工具，通常意味着你需要把分析结果变成业务可用的看板和共识。",
        "review_tip": "回顾你如何定义核心指标、搭建仪表盘，以及如何推动业务方使用。",
        "sample_question": "如果要为业务团队搭一个看板，你会优先放哪些指标？",
    },
    "power bi": {
        "title": "可视化看板与指标呈现",
        "focus_area": "工具能力",
        "why_it_matters": "JD 提到 BI 工具，通常意味着你需要把分析结果变成业务可用的看板和共识。",
        "review_tip": "回顾你如何定义核心指标、搭建仪表盘，以及如何推动业务方使用。",
        "sample_question": "如果要为业务团队搭一个看板，你会优先放哪些指标？",
    },
}


def build_review_cards(jd_profile: JDProfile, jd_text: str, max_cards: int = 5) -> List[KnowledgeReviewCard]:
    topics = _collect_topics(jd_profile, jd_text)
    evidence_lines = _build_evidence_map(topics, jd_profile, jd_text)
    cards: List[KnowledgeReviewCard] = []
    for index, topic in enumerate(topics[:max_cards], start=1):
        normalized = normalize_token(topic)
        template = _resolve_template(normalized)
        evidence = evidence_lines.get(normalized, [])
        if template:
            why_it_matters = _contextualize_why_it_matters(topic, template["why_it_matters"], jd_profile, evidence)
            review_tip = _contextualize_review_tip(topic, template["review_tip"], jd_profile, evidence)
            sample_question = _contextualize_sample_question(topic, template["sample_question"], jd_profile, evidence)
            cards.append(
                KnowledgeReviewCard(
                    id="review_{0}".format(index),
                    title=template["title"],
                    focus_area=template["focus_area"],
                    why_it_matters=why_it_matters,
                    review_tip=review_tip,
                    sample_question=sample_question,
                    keywords=[topic],
                )
            )
            continue

        cards.append(
            KnowledgeReviewCard(
                id="review_{0}".format(index),
                title=topic,
                focus_area=_classify_topic(topic),
                why_it_matters=_generic_why_it_matters(topic, jd_profile, evidence),
                review_tip=_generic_review_tip(topic, jd_profile, evidence),
                sample_question=_generic_sample_question(topic, jd_profile, evidence),
                keywords=[topic],
            )
        )
    return cards


def _collect_topics(jd_profile: JDProfile, jd_text: str) -> List[str]:
    items: List[str] = []
    items.extend(jd_profile.must_have_skills)
    items.extend(jd_profile.nice_to_have_skills[:2])
    items.extend(jd_profile.keywords[:4])
    items.extend(jd_profile.domain_signals)
    items.extend(_responsibility_phrases(jd_profile.responsibilities))
    items.extend(_collect_topics_from_jd_text(jd_text))
    topics = [topic for topic in unique_preserve_order(items) if _is_card_worthy(topic)]
    if topics:
        return topics
    job_title = (jd_profile.job_title or "").strip()
    if _is_card_worthy(job_title):
        return [job_title]
    return []


def _collect_topics_from_jd_text(jd_text: str) -> List[str]:
    items: List[str] = []
    items.extend(canonicalize_skills(extract_known_skills(jd_text)))

    raw_lines = [line.strip() for line in jd_text.splitlines() if line.strip()]
    for line in raw_lines:
        cleaned_line = line
        for prefix in ("岗位职责", "任职要求", "要求", "加分项", "职责"):
            cleaned_line = cleaned_line.replace(prefix, "")
        cleaned_line = cleaned_line.strip("：:- ")
        if not cleaned_line:
            continue
        items.extend(_responsibility_phrases([cleaned_line]))

    for token in extract_tokens(jd_text):
        normalized = normalize_token(token)
        if len(normalized) > 12:
            continue
        items.append(token)

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


def _build_evidence_map(topics: List[str], jd_profile: JDProfile, jd_text: str) -> Dict[str, List[str]]:
    raw_lines = [line.strip() for line in jd_text.splitlines() if line.strip()]
    searchable_lines = raw_lines[1:] if len(raw_lines) > 1 else raw_lines
    searchable_lines.extend(jd_profile.responsibilities)
    evidence_map: Dict[str, List[str]] = {}
    for topic in topics:
        normalized_topic = normalize_token(topic)
        matched = []
        for line in searchable_lines:
            normalized_line = normalize_token(line)
            if not normalized_line:
                continue
            if normalized_topic in normalized_line or normalized_line in normalized_topic:
                matched.append(line)
        evidence_map[normalized_topic] = unique_preserve_order(matched)[:2]
    return evidence_map


def _contextualize_why_it_matters(topic: str, base_text: str, jd_profile: JDProfile, evidence: List[str]) -> str:
    normalized = normalize_token(topic)
    if normalized == "sql":
        return "{0} {1}".format(base_text, _sql_context(jd_profile))
    if normalized in {"a b testing", "实验设计"}:
        return "{0} {1}".format(base_text, _experiment_context(jd_profile))
    if normalized in {"用户研究", "user research"}:
        return "{0} {1}".format(base_text, _user_research_context(jd_profile))
    if evidence:
        return "{0} JD 里还直接提到“{1}”，这意味着面试官大概率会追问到相关实践。".format(base_text, evidence[0])
    return "{0} {1}".format(base_text, _hiring_track_context(jd_profile))


def _contextualize_review_tip(topic: str, base_text: str, jd_profile: JDProfile, evidence: List[str]) -> str:
    normalized = normalize_token(topic)
    if normalized == "sql" and jd_profile.department == "product":
        return "{0} 重点准备你如何用 SQL 支撑增长漏斗、用户行为分析或实验复盘。".format(base_text)
    if normalized == "sql" and jd_profile.department == "data":
        return "{0} 重点准备口径定义、异常定位和取数分析的完整过程。".format(base_text)
    if normalized in {"a b testing", "实验设计"} and "growth" in jd_profile.domain_signals:
        return "{0} 最好准备一段你如何定义实验指标并解释结果的增长案例。".format(base_text)
    if evidence:
        return "{0} 可以结合 JD 中“{1}”这一要求，准备一个最贴近的真实案例。".format(base_text, evidence[0])
    return base_text


def _contextualize_sample_question(topic: str, base_text: str, jd_profile: JDProfile, evidence: List[str]) -> str:
    normalized = normalize_token(topic)
    if normalized == "sql" and jd_profile.department == "product":
        return "如果让你用 SQL 分析一个增长漏斗的掉点，并提出优化动作，你会怎么拆解？"
    if normalized == "sql" and jd_profile.department == "data":
        return "如果业务指标突然异常，你会如何用 SQL 建口径、查原因并输出结论？"
    if normalized in {"a b testing", "实验设计"}:
        return "请讲一个你如何提出实验假设、定义指标并判断实验是否成立的真实案例。"
    if evidence:
        return "JD 提到了“{0}”，如果面试官围绕这一点追问，你会拿哪段经历来作答？".format(evidence[0])
    if jd_profile.hiring_track == "campus":
        return "如果面试官问你对“{0}”的理解，你会用哪段项目或课程经历证明自己？".format(topic)
    return base_text


def _generic_why_it_matters(topic: str, jd_profile: JDProfile, evidence: List[str]) -> str:
    if evidence:
        return "JD 直接提到了“{0}”，说明这不是泛泛加分项，而是岗位真实关注点。".format(evidence[0])
    return "JD 明确提到了“{0}”，很可能会出现在简历筛选或面试追问里。{1}".format(topic, _hiring_track_context(jd_profile))


def _generic_review_tip(topic: str, jd_profile: JDProfile, evidence: List[str]) -> str:
    if jd_profile.hiring_track == "campus":
        return "优先回顾你在课程、项目、竞赛或实习里和“{0}”最相关的 1 到 2 个真实片段。".format(topic)
    if evidence:
        return "回顾你是否有与“{0}”和 JD 中“{1}”同时相关的项目、方法、工具或结果。".format(topic, evidence[0])
    return "回顾你是否有与“{0}”直接相关的项目、方法、工具或结果，并准备 1 个真实案例。".format(topic)


def _generic_sample_question(topic: str, jd_profile: JDProfile, evidence: List[str]) -> str:
    if evidence:
        return "如果面试官围绕 JD 中“{0}”展开追问，你会用什么事实来证明你具备“{1}”？".format(evidence[0], topic)
    if jd_profile.department == "product":
        return "如果面试官追问你在“{0}”上的实践，你会如何说明它如何影响产品判断或业务结果？".format(topic)
    return "如果面试官追问你在“{0}”上的实践，你会用什么事实来证明？".format(topic)


def _sql_context(jd_profile: JDProfile) -> str:
    if jd_profile.department == "product" or "growth" in jd_profile.domain_signals:
        return "在这个 JD 语境里，SQL 更像业务判断工具，重点是漏斗分析、实验复盘和增长决策支持。"
    if jd_profile.department == "data":
        return "在这个 JD 语境里，SQL 更像核心生产工具，重点是独立取数、建口径和定位异常。"
    if jd_profile.department == "marketing":
        return "在这个 JD 语境里，SQL 更偏渠道和转化分析，重点是看懂投放效果与用户路径。"
    return _hiring_track_context(jd_profile)


def _experiment_context(jd_profile: JDProfile) -> str:
    if "growth" in jd_profile.domain_signals or jd_profile.department == "product":
        return "这通常意味着岗位不只关心会不会做实验，还关心你能否把实验结果转成产品或增长动作。"
    return _hiring_track_context(jd_profile)


def _user_research_context(jd_profile: JDProfile) -> str:
    if jd_profile.hiring_track == "campus":
        return "校招语境下，面试通常更关注你是否理解研究方法，以及是否做过访谈、问卷或需求验证。"
    return "这通常意味着岗位会看你是否能从用户反馈里提炼洞察，而不只是罗列现象。"


def _hiring_track_context(jd_profile: JDProfile) -> str:
    if jd_profile.hiring_track == "campus":
        return "校招语境下，面试更重视你是否真正理解知识点并能结合项目或课程讲清楚。"
    if jd_profile.hiring_track == "intern":
        return "实习语境下，面试通常更关注你是否能快速上手并把基础方法讲明白。"
    return "社招语境下，面试通常更关注你是否做过、怎么做的，以及最后拿到了什么结果。"
