"""Select and compose exact, confirmed evidence with role-specific templates."""
import re

from backend.app.agents.base import BaseAgent, _NO_FALLBACK
from backend.app.agents.mock_interview import OWNERSHIP, TECHNOLOGY, metrics
from backend.app.schemas.material import MaterialDocument, MaterialEvidence, MaterialIssue, MaterialPlan
from backend.app.services.llm.structured import StructuredLLMError

TITLES = {
    "cover_letter": ("求职信", "Cover letter"),
    "intro_short": ("自我介绍 · 约 30 秒", "Introduction · about 30 seconds"),
    "intro_medium": ("自我介绍 · 约 60 秒", "Introduction · about 60 seconds"),
    "intro_long": ("自我介绍 · 约 120 秒", "Introduction · about 120 seconds"),
    "project_deep_dive": ("项目深挖讲稿", "Project deep dive"),
    "hr_outreach": ("HR 沟通 · 首次联系", "HR outreach"),
    "hr_followup": ("HR 沟通 · 进展询问", "HR follow-up"),
}


def claim_issues(text, baseline):
    issues = []
    for metric in sorted(metrics(text) - metrics(baseline)):
        issues.append(MaterialIssue(quote=metric, reason="数字或量化结果没有对应事实，请核对。"))
    for match in TECHNOLOGY.finditer(text):
        if match.group().lower() not in baseline.lower():
            issues.append(MaterialIssue(quote=match.group(), reason="技术经历不在对应事实中，请核对。"))
    for match in OWNERSHIP.finditer(text):
        if match.group().lower() not in baseline.lower():
            issues.append(MaterialIssue(quote=match.group(), reason="个人职责可能超出原事实，请核对。"))
    return issues


def collect_evidence(draft, facts):
    lookup = {fact.id: fact for fact in facts if fact.confirmed and fact.text.strip()}
    evidence, seen = [], set()
    trace = {item.draft_span: item.fact_ids for item in draft.traceability}
    for section_name in ("project_section", "experience_section"):
        for section_index, section in enumerate(getattr(draft, section_name), 1):
            for bullet_index, bullet in enumerate(section.bullets, 1):
                span = f"{section_name}.{section_index}.bullets.{bullet_index}"
                ids = trace.get(span) or [fact.id for fact in lookup.values() if fact.text.strip() in bullet]
                if not ids or any(fact_id not in lookup for fact_id in ids):
                    continue
                baseline = " ".join(lookup[fact_id].text for fact_id in ids)
                if claim_issues(bullet, baseline):
                    continue
                # Exact fact text keeps every material's candidate claims identical.
                for fact_id in ids:
                    if fact_id in seen:
                        continue
                    seen.add(fact_id)
                    evidence.append(MaterialEvidence(id=f"e{len(evidence)+1}", text=lookup[fact_id].text.strip(),
                        fact_ids=[fact_id], resume_span=span, resume_text=bullet,
                        group=f"{section_name}.{section_index}"))
    return evidence[:60]


def default_plan(evidence, jd):
    keywords = [value.casefold() for value in jd.must_have_skills + jd.keywords if value]
    ordered = sorted(evidence, key=lambda item: -sum(word in item.text.casefold() for word in keywords))
    ids = [item.id for item in ordered]
    project = next((item.group for item in ordered if item.group.startswith("project_section")), "")
    return MaterialPlan(selections={
        "cover_letter": ids[:4], "intro_short": ids[:1], "intro_medium": ids[:3], "intro_long": ids[:6],
        "project_deep_dive": [item.id for item in ordered if item.group == project][:8],
        "hr_outreach": ids[:1], "hr_followup": [],
    })


class MaterialsAgent(BaseAgent):
    name = "materials"
    llm_metadata = {"max_tokens": 1400}

    def select(self, evidence, draft, jd, language):
        fallback = default_plan(evidence, jd)
        available = self.maybe_use_fallback(fallback)
        if available is not _NO_FALLBACK:
            return available, "rules"
        try:
            proposed = self.invoke_structured({"language": language, "jd_profile": jd,
                "saved_resume": draft, "evidence": evidence, "material_kinds": list(TITLES)}, MaterialPlan)
        except StructuredLLMError as exc:
            return self.fallback_on_error(exc, fallback), "rules"
        known = {item.id: item for item in evidence}
        limits = dict(cover_letter=4, intro_short=1, intro_medium=3, intro_long=6, project_deep_dive=8, hr_outreach=1, hr_followup=0)
        for kind in TITLES:
            selected = list(dict.fromkeys(proposed.selections.get(kind, [])))
            if not selected or any(item not in known for item in selected):
                selected = fallback.selections[kind]
            if kind == "project_deep_dive":
                group = next((known[item].group for item in selected if known[item].group.startswith("project_section")), "")
                selected = [item for item in selected if group and known[item].group == group]
                selected = selected or fallback.selections[kind]
            proposed.selections[kind] = selected[:limits[kind]]
        return proposed, "model_selection"


def compose_documents(plan, evidence, company, role, name, language):
    en = language == "en"
    lookup = {item.id: item for item in evidence}
    target = " · ".join(value for value in (company, role) if value) or ("the target role" if en else "目标岗位")
    greeting = f"Hello, I'm {name}." if en and name else (f"您好，我是{name}。" if name else ("Hello." if en else "您好。"))
    interest = f"I would like to apply for {target}." if en else f"我希望申请「{target}」。"
    evidence_lead = "My confirmed experience includes:" if en else "以下是我在简历中对应的已确认经历："
    invitation = "I'd welcome the chance to discuss these experiences and the role's requirements." if en else "希望有机会进一步交流这些经历与岗位要求。"
    docs = []
    for kind, titles in TITLES.items():
        ids = plan.selections[kind]
        snippets = [lookup[item].text for item in ids]
        opening = [greeting, interest]
        closing = [invitation]
        hint = ""
        if kind.startswith("intro_"):
            # Keep whole facts; never truncate an outcome or a responsibility boundary.
            budget = {"intro_short": (65, 130), "intro_medium": (130, 260), "intro_long": (260, 520)}[kind][int(not en)]
            used, retained = len(" ".join(opening + closing).split()) if en else len("".join(opening + closing)), []
            for item in ids:
                size = len(lookup[item].text.split()) if en else len(lookup[item].text)
                if used + size <= budget:
                    retained.append(item); used += size
            ids = retained; snippets = [lookup[item].text for item in ids]
            if kind == "intro_long":
                closing.insert(0, "I can explain my own contribution, the evidence for the results, and any limitations." if en else "交流时，我会进一步说明个人贡献、结果依据和无法确认的部分。")
            hint = "Timing is a rehearsal target; adjust to your speaking pace. Short evidence may produce a shorter script." if en else "时长是练习目标，请按语速调整；事实较少时讲稿会更短。"
        elif kind == "cover_letter":
            opening = ["Dear hiring team," if en else "招聘团队您好：", greeting, interest, evidence_lead]
            closing += ["Thank you for considering my application." if en else "感谢您审阅我的申请。", name or ""]
        elif kind == "project_deep_dive":
            opening = [f"Target role: {target}" if en else f"目标岗位：{target}",
                       "Confirmed project facts" if en else "项目的已确认事实"]
            closing = ["Context: [add confirmed background and objective]" if en else "背景与目标：[待补充：可核实的项目背景和目标]",
                       "Personal actions: explain the facts above, separating team and individual contributions." if en else "个人行动：围绕上面的事实展开，区分个人动作与团队成果。",
                       "Decisions: [add actual trade-offs and reasons]" if en else "方案取舍：[待补充：实际考虑过的方案与选择依据]",
                       "Outcome: explain confirmed deliverables; [add verifiable records if available]." if en else "结果与依据：解释已有交付物；[待补充：可核实的记录与统计口径]。",
                       "Reflection: [add a real limitation and a proposed improvement, clearly labeled]" if en else "复盘：[待补充：实际遇到的限制与明确标为设想的改进]。"]
            if not snippets:
                snippets = ["[No traceable project evidence in this resume version. Add and confirm facts first.]" if en else "[当前版本没有可追溯的项目事实，请先补充并确认项目经历。]"]
        elif kind == "hr_outreach":
            closing = ["Is this role still open? May I share my resume for your review?" if en else "请问该岗位目前是否仍在招聘？方便的话，我希望发送简历供您参考。",
                       "Availability: [confirm dates before sending]" if en else "到岗 / 面试时间：[请本人确认后填写]。"]
        elif kind == "hr_followup":
            opening = [greeting, f"I'd like to ask about the recruitment process for {target}." if en else f"想了解「{target}」目前的招聘进展。"]
            closing = ["[If you already applied, add the actual application date or contact history.]" if en else "[如已投递，请本人补充实际投递日期或沟通记录。]",
                       "Please let me know if you need additional information. Thank you." if en else "如需补充材料，欢迎告知。感谢您的时间。"]
        if not snippets and kind != "hr_followup":
            snippets = ["[No usable experience evidence here. Add confirmed facts or choose another resume version.]" if en else "[此份材料缺少可引用的经历，请补充已确认事实或选择其他简历版本。]"]
        content = "\n\n".join(value for value in opening + snippets + closing if value)
        docs.append(MaterialDocument(id=kind, title=titles[int(en)], content=content, original_content=content,
            evidence_ids=ids, length_hint=hint, issues=placeholder_issues(content)))
    return docs


def placeholder_issues(content):
    return [MaterialIssue(quote=match.group(), reason="发送前需本人补充或删除占位内容。") for match in re.finditer(r"\[[^\]\n]+\]", content)][:20]


def review_document(document, content, pack):
    # Comparing to this document's evidence prevents borrowing a metric from another project.
    baseline = " ".join(item.text for item in pack.evidence if item.id in document.evidence_ids)
    issues = placeholder_issues(content)
    if content != document.original_content:
        issues += claim_issues(content, baseline + " " + document.original_content)
        issues.append(MaterialIssue(quote="", reason="手工修改的表达需要本人核对；原生成内容的事实引用不自动证明新增文字。"))
    return issues[:30]
