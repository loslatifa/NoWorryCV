"""Evidence-grounded practice questions and quote-validated answer feedback."""
import re
from decimal import Decimal
from typing import List

from backend.app.agents.base import BaseAgent, _NO_FALLBACK
from backend.app.schemas.interview import AnswerAssessment, AnswerIssue, InterviewFeedback, InterviewQuestion
from backend.app.services.llm.structured import StructuredLLMError


METRIC = re.compile(r"\d+(?:\.\d+)?\s*(?:%|％|万人|万|亿|人|个|天|小时|分钟|个月|年|users\b|days\b|hours\b|months\b|million\b)", re.I)
OWNERSHIP = re.compile(r"主导|独立负责|带领团队|独立完成|led the team|solely responsible|single.hand(?:edly)?", re.I)
PARTICIPATION = re.compile(r"参与|协助|支持|assisted|participated|supported", re.I)
TECHNOLOGY = re.compile(r"\b(?:Python|SQL|Java|C\+\+|React|Redis|Kafka|Kubernetes|Docker|TensorFlow|PyTorch|Spark|Hadoop)\b", re.I)


def metrics(text):
    values = set()
    for match in METRIC.finditer(text):
        value = re.sub(r"\s+", "", match.group()).replace("％", "%").lower()
        number = re.match(r"\d+(?:\.\d+)?", value).group()
        values.add(format(Decimal(number).normalize(), "f") + value[len(number):])
    return values


def excerpt(answer, needle=None, limit=300):
    if needle:
        position = answer.find(needle)
        if position >= 0:
            start = max(answer.rfind("。", 0, position), answer.rfind("\n", 0, position), answer.rfind(";", 0, position)) + 1
            # Keep the claim in view even when a single sentence is longer than the quote budget.
            start = max(start, position - 60)
            ending = re.search(r"[。；;\n]|[.!?](?:\s|$)", answer[position:])
            end = position + ending.end() if ending else len(answer)
            return answer[start:min(end, start + limit)].strip()
    return answer[:limit].strip()


def negated(text, position):
    prefix = text[max(0, position - 25):position]
    return bool(re.search(r"(?:没有|没|并非|不是|并未|未曾|不曾|不|未|never|did not|not)\s*(?:达到|提升|增长|使用|用|used|use|a|the)?\s*$", prefix, re.I))


def build_questions(draft, jd, facts, rounds, language):
    en = language == "en"
    requirements = list(dict.fromkeys(value for value in jd.must_have_skills + jd.responsibilities + jd.keywords if value.strip()))
    requirements = requirements or [jd.job_title or ("岗位要求" if not en else "the role")]
    entries = []
    for section_name in ("experience_section", "project_section"):
        for section_index, section in enumerate(getattr(draft, section_name), 1):
            for bullet_index, bullet in enumerate(section.bullets, 1):
                span = f"{section_name}.{section_index}.bullets.{bullet_index}"
                ids = [fact_id for trace in draft.traceability if trace.draft_span == span for fact_id in trace.fact_ids]
                entries.append((bullet, ids))
    known = {fact.id for fact in facts}
    entries = entries or [(draft.summary or ", ".join(draft.skills_section) or draft.headline, [])]
    questions = []
    for index in range(rounds):
        reference, ids = entries[index % len(entries)]
        ids = [fact_id for fact_id in ids if fact_id in known]
        if not ids:
            ids = [fact.id for fact in facts if fact.text and fact.text in reference]
        reference = reference[:600]
        requirement = requirements[index % len(requirements)][:500]
        prompts = [
            ("experience", f"The JD asks for {requirement}; your resume says ‘{reference}’. Describe the context, your own actions and the outcome." if en else f"JD 关注「{requirement}」，简历写到「{reference}」。请说明当时的背景、你个人的行动和结果。"),
            ("knowledge", f"Using the resume example ‘{reference}’, explain how you would apply {requirement} and verify the result. Distinguish what you did from a proposed approach." if en else f"结合简历中的「{reference}」，解释你会如何应用「{requirement}」并验证效果。请区分实际做过的事和设想的方法。"),
            ("reflection", f"Looking back at ‘{reference}’, what was the main limitation or difficulty? What would you change, and why does it matter for {requirement}?" if en else f"回顾「{reference}」，最大的限制或困难是什么？你会如何改进，这与岗位要求「{requirement}」有什么关系？"),
            ("experience", f"In ‘{reference}’, how did you coordinate with others? Explain your responsibility boundary rather than claiming the whole team's outcome." if en else f"在「{reference}」中，你如何与其他人协作？请说清职责边界，区分个人贡献和团队成果。"),
            ("knowledge", f"For {requirement}, which assumptions in ‘{reference}’ would you test first, and how would you handle an inconclusive result?" if en else f"对于「{requirement}」，你会先验证「{reference}」中的哪些假设？如果结果不明确，你会如何处理？"),
            ("reflection", f"Which part of ‘{reference}’ best supports {requirement}? Which capability still needs learning or evidence?" if en else f"「{reference}」中的哪部分最能证明「{requirement}」？还有哪些能力需要学习或补充证据？"),
        ]
        kind, prompt = prompts[index]
        questions.append(InterviewQuestion(round_number=index + 1, kind=kind, prompt=prompt,
                                           jd_reference=requirement, resume_reference=reference, fact_ids=ids))
    return questions


def deterministic_feedback(session, answer):
    question = session.current_question
    en = session.language == "en"
    lookup = {fact.id: fact for fact in session.fact_cards}
    related = [lookup[fact_id] for fact_id in question.fact_ids if fact_id in lookup]
    baseline = " ".join(fact.text for fact in related)
    quote = excerpt(answer)
    issues: List[AnswerIssue] = []
    # Questions about approaches must not turn a hypothetical metric into a claimed result.
    hypothesis = re.compile(r"如果|假设|设想|例如|我会|无法确认|不确定|would|hypothetic|for example|cannot verify|not sure", re.I)
    past_experience = bool(re.search(r"我(?:曾|实际|在|使用|负责|完成|参与)|项目中.*(?:使用|用了)|I (?:used|built|led|implemented|developed)", answer, re.I))
    hypothetical = question.kind == "knowledge" and not past_experience
    if not hypothetical:
        unknown_metrics = metrics(answer) - metrics(baseline)
        for metric in sorted(unknown_metrics)[:3]:
            match = next((match for match in METRIC.finditer(answer) if metric in metrics(match.group())), None)
            issue_quote = excerpt(answer, match.group() if match else None)
            if hypothesis.search(issue_quote) or (match and negated(answer, match.start())):
                continue
            unit = re.sub(r"^[\d.]+", "", metric)
            same_unit = any(re.sub(r"^[\d.]+", "", known) == unit for known in metrics(baseline))
            issues.append(AnswerIssue(kind="inconsistent" if same_unit and question.fact_ids else "unverified", answer_quote=issue_quote, fact_ids=question.fact_ids,
                explanation="This metric is not supported by the confirmed facts for this resume example; it needs verification." if en else "这项数字在当前简历条目的已确认事实中没有依据；可能是新信息，也可能与原结果不一致，需要核实。",
                recommendation="Check the source and measurement scope. If you cannot verify it, remove the number or state the uncertainty." if en else "核对数据来源、口径和时间范围；无法确认时去掉数字或明确说明不确定，不要估算补造。"))
        ownership = next((match for match in OWNERSHIP.finditer(answer) if not negated(answer, match.start())), None)
        if (ownership and PARTICIPATION.search(baseline) and not OWNERSHIP.search(baseline)
                and not hypothesis.search(excerpt(answer, ownership.group()))):
            issues.append(AnswerIssue(kind="inconsistent", answer_quote=excerpt(answer, ownership.group()), fact_ids=question.fact_ids,
                explanation="The confirmed facts describe participation or support, while this answer claims stronger ownership." if en else "已确认事实描述的是参与或协助，回答却使用了更强的主导或独立负责表达，职责边界可能不一致。",
                recommendation="Separate personal actions from the team's outcome and verify your actual responsibility." if en else "区分个人动作和团队成果，核实实际负责范围，按能证明的职责回答。"))
        known_text = " ".join(fact.text for fact in session.fact_cards).lower()
        for match in TECHNOLOGY.finditer(answer):
            if (match.group().lower() not in known_text and re.search(r"使用|用|开发|实现|built|used|implemented|developed", excerpt(answer, match.group()), re.I)
                    and not hypothesis.search(excerpt(answer, match.group())) and not negated(answer, match.start())):
                issues.append(AnswerIssue(kind="unverified", answer_quote=excerpt(answer, match.group()), fact_ids=[],
                    explanation="This claimed technical experience is not in the confirmed facts." if en else "回答声称使用的技术未出现在已确认事实中，需要核实真实经历。",
                    recommendation="Confirm what you actually used; distinguish experience from knowledge or a proposed solution." if en else "确认实际使用过的技术，区分真实经历、知识了解与设想方案。"))
                break
    for turn in session.turns:
        if turn.question.round_number == question.round_number and metrics(turn.answer) and metrics(answer) and metrics(turn.answer) != metrics(answer) and not hypothetical and not hypothesis.search(answer):
            issues.append(AnswerIssue(kind="unverified", answer_quote=quote, fact_ids=question.fact_ids,
                explanation="Metrics differ from the earlier answer in this round. They may use different scopes; please clarify." if en else "本轮回答中的数字与之前回答不同，可能采用不同口径，请解释并核实。",
                recommendation="Explain the relationship between the numbers and correct any mistaken claim." if en else "说明数字之间的关系与口径，纠正说错的结果。"))
            break
    structure_signals = sum(bool(re.search(pattern, answer, re.I)) for pattern in (
        r"背景|目标|当时|context|goal|task", r"我|负责|使用|行动|\bI\b|action|used", r"结果|完成|交付|result|outcome|delivered"))
    structure_score = min(4, structure_signals + int(len(answer) > 70))
    clarity_score = 1 if len(answer) < 20 else (2 if len(answer) > 2200 else 3)
    evidence_terms = [term for term in TECHNOLOGY.findall(baseline) + session.jd_profile.must_have_skills if term]
    relevant = any(term.lower() in answer.lower() for term in evidence_terms)
    evidence_score = 3 if related and relevant and not issues and len(answer) >= 60 else 1
    structure_checks = [("背景" if not en else "context", r"背景|目标|当时|context|goal|task"),
                        ("个人行动" if not en else "personal actions", r"我|负责|使用|行动|\bI\b|action|used"),
                        ("结果" if not en else "outcome", r"结果|完成|交付|result|outcome|delivered")]
    missing = [label for label, pattern in structure_checks if not re.search(pattern, answer, re.I)]
    structure_reason = (("尚未清楚说明：" + "、".join(missing) + "。请补充能够确认的细节。") if missing else "回答已出现背景、个人行动和结果线索，继续检查个人贡献与结果之间的关系。") if not en else (("Missing explicit " + ", ".join(missing) + ". Add verifiable details.") if missing else "Context, personal action and outcome are present; check the link between contribution and result.")
    consistency_score = 1 if any(issue.kind == "inconsistent" for issue in issues) else (2 if issues or not related else 3)
    def assessment(score, zh, english):
        return AnswerAssessment(score=score, reason=english if en else zh, answer_quote=quote)
    focus = "measurement" if any(metrics(issue.answer_quote) for issue in issues) else ("scope" if issues else ("result" if structure_score < 3 else "none"))
    return InterviewFeedback(
        structure=AnswerAssessment(score=structure_score, reason=structure_reason, answer_quote=quote),
        evidence=assessment(evidence_score, "证据评分参考与当前简历条目关联的事实；数字的来源和个人贡献仍需解释。", "Evidence is assessed against linked resume facts; explain data sources and your contribution."),
        clarity=assessment(clarity_score, "回答过短会缺少解释，过长需要收束；优先用明确的行动和结果组织内容。", "Short answers may lack detail; long answers need focus. Organize around specific actions and outcomes."),
        consistency=assessment(consistency_score, "与已确认事实及本轮之前的回答进行有限比较；未发现提示不代表事实已获验证。", "Limited comparison with confirmed facts and earlier answers; no warning does not establish truth."),
        issues=issues[:12], follow_up_focus=focus, follow_up_quote=(issues[0].answer_quote if issues else quote)[:200],
        suggestions=["用背景—任务—个人行动—结果组织回答，只保留可解释和核实的经历。" if not en else "Structure the answer as context, task, personal action and outcome; retain only verifiable experience.",
                     "无法提供数据时说明限制，可描述已确认的交付物，不要补造量化成果。" if not en else "State limitations when data is unavailable; describe confirmed deliverables instead of inventing metrics."],
    )


def build_follow_up(question, feedback, answer, language):
    if question.kind == "follow_up" or feedback.follow_up_focus == "none":
        return None
    en = language == "en"
    requests = {
        "scope": ("哪些动作由你亲自完成，哪些由团队完成？", "Which actions did you personally perform, and which belonged to the team?"),
        "measurement": ("这个数字来自什么记录，使用什么口径？无法确认时请直接说明。", "What record and measurement scope support this number? State it if you cannot verify it."),
        "reasoning": ("为什么选择这种方法，有哪些限制或替代方案？", "Why did you choose this method, and what limitations or alternatives did it have?"),
        "result": ("最后实际交付了什么，你如何确认结果？没有量化数据也可以说明真实交付物。", "What did you actually deliver, and how did you verify it? A real deliverable is enough if no metric is available."),
    }
    quoted = feedback.follow_up_quote if feedback.follow_up_quote and feedback.follow_up_quote in answer else excerpt(answer, limit=200)
    request = requests[feedback.follow_up_focus][int(en)]
    return InterviewQuestion(round_number=question.round_number, kind="follow_up",
        prompt=f"You said ‘{quoted}’. {request}" if en else f"你刚才说「{quoted}」。{request}",
        jd_reference=question.jd_reference, resume_reference=question.resume_reference,
        fact_ids=question.fact_ids, parent_question_id=question.id)


class MockInterviewAgent(BaseAgent):
    name = "mock_interview"
    llm_metadata = {"max_tokens": 1600}

    def evaluate(self, session, answer):
        fallback = deterministic_feedback(session, answer)
        available = self.maybe_use_fallback(fallback)
        if available is not _NO_FALLBACK:
            return available
        question = session.current_question
        facts = sorted(session.fact_cards, key=lambda fact: fact.id not in question.fact_ids)[:40]
        try:
            feedback = self.invoke_structured({
                "language": session.language, "question": question, "answer": answer,
                "jd_profile": session.jd_profile, "saved_resume": session.draft,
                "confirmed_facts": facts, "previous_turns": [{"question": turn.question.prompt, "answer": turn.answer} for turn in session.turns[-6:]],
                "detected_issues": fallback.issues,
            }, InterviewFeedback)
        except StructuredLLMError as exc:
            return self.fallback_on_error(exc, fallback)
        known_ids = {fact.id for fact in facts}
        allowed_context = answer + " " + " ".join(fact.text for fact in facts)
        allowed_metrics = metrics(allowed_context)
        allowed_technologies = {value.lower() for value in TECHNOLOGY.findall(allowed_context)}
        def grounded_advice(text):
            return (metrics(text) <= allowed_metrics
                    and {value.lower() for value in TECHNOLOGY.findall(text)} <= allowed_technologies
                    and not re.search(r"建议(?:你)?(?:编造|虚构)|可以(?:编造|虚构)|make up a|invent a|fabricate a", text, re.I))
        for name in ("structure", "evidence", "clarity", "consistency"):
            assessment = getattr(feedback, name)
            if not assessment.answer_quote or assessment.answer_quote not in answer or not grounded_advice(assessment.reason):
                setattr(feedback, name, getattr(fallback, name))
        model_issues = [issue for issue in feedback.issues if issue.answer_quote in answer and set(issue.fact_ids) <= known_ids
                           and (issue.kind != "inconsistent" or issue.fact_ids)
                           and grounded_advice(issue.explanation) and grounded_advice(issue.recommendation)]
        # Preserve deterministic fact risks before applying the display limit.
        feedback.issues = list(fallback.issues)
        for issue in model_issues:
            if not any(item.answer_quote == issue.answer_quote and item.kind == issue.kind for item in feedback.issues):
                feedback.issues.append(issue)
        feedback.issues = feedback.issues[:12]
        if fallback.issues:
            feedback.consistency.score = min(feedback.consistency.score, fallback.consistency.score)
            feedback.evidence.score = min(feedback.evidence.score, fallback.evidence.score)
            feedback.follow_up_focus, feedback.follow_up_quote = fallback.follow_up_focus, fallback.follow_up_quote
        # Advice may not introduce a new numeric result, even if a model returns one.
        feedback.suggestions = [suggestion[:700] for suggestion in feedback.suggestions if suggestion.strip() and grounded_advice(suggestion)]
        feedback.suggestions = feedback.suggestions or fallback.suggestions
        if feedback.follow_up_quote not in answer:
            feedback.follow_up_quote = fallback.follow_up_quote
        feedback.method = "model"
        return feedback
