"""Synthetic acceptance gates for the production material and interview paths."""
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time
from typing import Dict, List, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from backend.app.agents.materials import TITLES, review_document
from backend.app.agents.mock_interview import MockInterviewAgent, TECHNOLOGY, build_follow_up, build_questions, deterministic_feedback, metrics, negated
from backend.app.core.config import get_settings
from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from backend.app.schemas.interview import InterviewSession, InterviewTurn
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.review import ATSReport, ComplianceReport
from backend.app.schemas.run_state import DraftVersion, TailorRunJobStatus, TailorRunResult
from backend.app.schemas.strategy import FinalResumePackage, GapAnalysis, ResumeDraft, RewriteStrategy
from backend.app.services.interviews import interview_report
from backend.app.services.llm.diagnostics import safe_failure
from backend.app.services.llm.provider import get_llm_provider
from backend.app.services.materials import generate_pack, material_markdown, pack_zip
from backend.app.services.provenance import capture_provenance

EVALUATION_VERSION = "preparation-quality-v1"
SLUG = r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}$"


class PreparationContext(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Literal["zh", "en"]
    company: str = Field(min_length=1, max_length=120)
    jd_text: str = Field(min_length=1, max_length=30000)
    jd_profile: JDProfile
    candidate_profile: CandidateProfile
    draft: ResumeDraft
    fact_cards: List[FactCard] = Field(min_length=1, max_length=60)

    @model_validator(mode="after")
    def reviewed_inputs(self):
        if self.candidate_profile.basics.email or self.candidate_profile.basics.phone:
            raise ValueError("合成样例不得包含联系方式。")
        ids = [fact.id for fact in self.fact_cards]
        if len(set(ids)) != len(ids) or any(not fact.text.strip() for fact in self.fact_cards):
            raise ValueError("事实必须非空且 ID 唯一。")
        if not any(fact.confirmed for fact in self.fact_cards):
            raise ValueError("评测需要已确认事实。")
        return self


class PreparationCase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=SLUG)
    kind: Literal["materials", "interview"]
    context_id: str = Field(pattern=SLUG)
    question_index: int = Field(default=0, ge=0, le=2)
    answer: str = Field(default="", max_length=6000)
    required_issue_kinds: List[Literal["inconsistent", "unverified", "expression"]] = Field(default_factory=list)
    forbidden_issue_kinds: List[Literal["inconsistent", "unverified", "expression"]] = Field(default_factory=list)
    required_issue_quotes: List[str] = Field(default_factory=list, max_length=6)

    @model_validator(mode="after")
    def valid_expectations(self):
        if self.kind == "interview" and not self.answer.strip():
            raise ValueError("面试样例需要明确的合成回答。")
        if self.kind == "materials" and (self.answer or self.required_issue_kinds or self.forbidden_issue_kinds or self.required_issue_quotes):
            raise ValueError("材料样例不能使用面试断言。")
        if set(self.required_issue_kinds) & set(self.forbidden_issue_kinds):
            raise ValueError("断言冲突。")
        if any(not quote or quote not in self.answer for quote in self.required_issue_quotes):
            raise ValueError("风险断言必须引用合成回答原句。")
        return self


class PreparationDataset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = Field(min_length=1)
    data_policy: Literal["synthetic_only"]
    contexts: Dict[str, PreparationContext]
    cases: List[PreparationCase] = Field(min_length=1)

    @model_validator(mode="after")
    def complete_cases(self):
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)) or any(not re.fullmatch(SLUG, key) for key in self.contexts):
            raise ValueError("样例和上下文 ID 必须为唯一的短标识。")
        if any(case.context_id not in self.contexts for case in self.cases):
            raise ValueError("样例缺少上下文。")
        return self


def saved_job(context, case_id):
    """Create validated snapshots in memory, without opening user stores or queues."""
    draft = context.draft.model_copy(deep=True)
    version = DraftVersion(id="version-" + case_id, label="Synthetic saved resume", source="generated",
        created_at="2026-10-15T00:00:00+00:00", draft=draft, compliance_report=ComplianceReport(), ats_report=ATSReport())
    result = TailorRunResult(run_id="run-" + case_id, status="completed", iterations=1, stop_reason="synthetic fixture",
        candidate_profile=context.candidate_profile.model_copy(deep=True), jd_profile=context.jd_profile.model_copy(deep=True),
        gap_analysis=GapAnalysis(), rewrite_strategy=RewriteStrategy(), fact_cards=[fact.model_copy(deep=True) for fact in context.fact_cards],
        drafts=[draft], reviews=[], final_package=FinalResumePackage(draft=draft), draft_versions=[version], active_version_id=version.id,
        resolved_language=context.language)
    return TailorRunJobStatus(run_id=result.run_id, status="completed", target_company=context.company,
        target_job_title=context.jd_profile.job_title, jd_text=context.jd_text, expires_at="2100-01-01T00:00:00+00:00", result=result), version


def check_materials(context, case):
    job, version = saved_job(context, case.id)
    before = job.model_dump_json()
    pack = generate_pack(job, version)
    evidence = {item.id:item for item in pack.evidence}
    facts = {fact.id:fact.text for fact in context.fact_cards if fact.confirmed}
    spans = {f"{section_name}.{section_index}.bullets.{bullet_index}":text
        for section_name in ("experience_section", "project_section")
        for section_index, section in enumerate(getattr(version.draft, section_name), 1)
        for bullet_index, text in enumerate(section.bullets, 1)}
    combined = "\n".join(doc.content for doc in pack.documents)
    deep = next((doc for doc in pack.documents if doc.id == "project_deep_dive"), None)
    groups = {evidence[key].group for key in deep.evidence_ids if key in evidence} if deep else set()
    intros = [next((doc.content for doc in pack.documents if doc.id==key), "") for key in ("intro_short","intro_medium","intro_long")]
    modified = pack.documents[0].content + ("\n转化率提升99%。我独立完成 Kafka 项目。" if context.language=="zh" else "\nConversion improved by 99%. I was solely responsible for a Kafka project.")
    issues = review_document(pack.documents[0], modified, pack)
    checks = {
        "seven_document_types":len(pack.documents)==7 and {doc.id for doc in pack.documents}==set(TITLES),
        "confirmed_evidence":bool(evidence) and all(item.fact_ids and all(key in facts and facts[key]==item.text for key in item.fact_ids) for item in evidence.values()),
        "saved_resume_reference":all(spans.get(item.resume_span)==item.resume_text for item in evidence.values()),
        "document_citations":all(all(key in evidence and evidence[key].text in doc.content for key in doc.evidence_ids) for doc in pack.documents),
        "no_unconfirmed_experience":all(not fact.text.strip() or fact.text.strip() not in combined for fact in context.fact_cards if not fact.confirmed),
        "project_isolation":bool(deep) and bool(groups) and len(groups)==1 and all(group.startswith("project_section.") for group in groups),
        "introduction_lengths":0<len(intros[0])<=len(intros[1])<len(intros[2]),
        "target_jd_and_version":pack.jd_text==context.jd_text and pack.version_id==version.id and all(context.jd_text in material_markdown(pack,doc) and version.id in material_markdown(pack,doc) for doc in pack.documents),
        "review_not_automatic":all(not doc.reviewed for doc in pack.documents),
        "manual_edit_risk":any(issue.quote=="99%" for issue in issues) and any(issue.quote=="Kafka" for issue in issues),
        "source_immutable":job.model_dump_json()==before,
        "zip_serialization":pack_zip(pack).startswith(b"PK"),
        "model_ran":not (get_settings().llm_strict_mode and get_llm_provider().is_available) or pack.method=="model_selection",
    }
    return checks, {"document_count":len(pack.documents),"evidence_count":len(evidence),"method":pack.method}


def check_interview(context, case):
    facts = [fact.model_copy(deep=True) for fact in context.fact_cards if fact.confirmed]
    questions = build_questions(context.draft,context.jd_profile,facts,3,context.language)
    # Selecting a later standalone question exercises knowledge/reflection without inventing previous answers.
    selected = questions[case.question_index]
    session = InterviewSession(id="session-"+case.id,run_id="run-"+case.id,version_id="version-"+case.id,
        version_label="Synthetic saved resume",language=context.language,rounds=3,created_at="2026-10-15T00:00:00+00:00",
        updated_at="2026-10-15T00:00:00+00:00",expires_at="2100-01-01T00:00:00+00:00",draft=context.draft.model_copy(deep=True),
        jd_profile=context.jd_profile.model_copy(deep=True),fact_cards=facts,questions=[selected])
    before = session.model_dump_json()
    rules = deterministic_feedback(session,case.answer)
    feedback = MockInterviewAgent().evaluate(session,case.answer)
    known = {fact.id for fact in facts}
    assessments = [getattr(feedback,name) for name in ("structure","evidence","clarity","consistency")]
    all_issues = feedback.issues
    kinds = {issue.kind for issue in all_issues}
    advice = [item.reason for item in assessments] + feedback.suggestions + [text for issue in all_issues for text in (issue.explanation,issue.recommendation)]
    allowed = case.answer + " " + " ".join(fact.text for fact in facts)
    technologies = {value.lower() for value in TECHNOLOGY.findall(allowed)}
    fabrication = re.compile(r"(?:可以|建议(?:你)?|请)(?:去)?(?:编造|虚构)|\b(?:invent|fabricate|make up)\s+(?:a|an|the|some)\b",re.I)
    follow = build_follow_up(selected,feedback,case.answer,context.language)
    reviewed = session.model_copy(deep=True)
    reviewed.turns=[InterviewTurn(question=selected,answer=case.answer,answered_at="2026-10-15T00:00:00+00:00",feedback=feedback)]
    report = interview_report(reviewed)
    checks = {
        "question_references":bool(selected.jd_reference) and selected.jd_reference in selected.prompt and selected.resume_reference in selected.prompt,
        "answer_quotes":all(item.answer_quote and item.answer_quote in case.answer for item in assessments) and all(issue.answer_quote in case.answer for issue in all_issues) and (not feedback.follow_up_quote or feedback.follow_up_quote in case.answer),
        "known_fact_ids":all(set(issue.fact_ids)<=known and (issue.kind!="inconsistent" or issue.fact_ids) for issue in all_issues),
        "required_issue_kinds":set(case.required_issue_kinds)<=kinds,
        "forbidden_issue_kinds":not (set(case.forbidden_issue_kinds)&kinds),
        "required_issue_quotes":all(any(quote in issue.answer_quote for issue in all_issues) for quote in case.required_issue_quotes),
        "rule_risks_retained":all(any(issue.kind==original.kind and issue.answer_quote==original.answer_quote for issue in all_issues) for original in rules.issues),
        "scores_bounded_by_risks":not rules.issues or feedback.consistency.score<=rules.consistency.score and feedback.evidence.score<=rules.evidence.score,
        "advice_has_no_new_metrics":all(metrics(text)<=metrics(allowed) for text in advice),
        "advice_has_no_new_technologies":all({value.lower() for value in TECHNOLOGY.findall(text)}<=technologies for text in advice),
        "no_fabrication_advice":not any(not negated(text,match.start()) for text in advice for match in fabrication.finditer(text)),
        "followup_boundaries":not follow or follow.parent_question_id==selected.id and follow.fact_ids==selected.fact_ids and follow.jd_reference==selected.jd_reference and build_follow_up(follow,feedback,case.answer,context.language) is None,
        "review_report":case.answer in report and session.version_id in report and selected.jd_reference in report,
        "source_immutable":session.model_dump_json()==before,
        "model_ran":not (get_settings().llm_strict_mode and get_llm_provider().is_available) or feedback.method=="model",
    }
    return checks,{"issue_count":len(all_issues),"rule_issue_count":len(rules.issues),"method":feedback.method}


def validate_preparation_baseline(header, cases, baseline):
    if not isinstance(baseline,dict) or baseline.get("evaluation_version")!=EVALUATION_VERSION or baseline.get("dataset_digest")!=header["dataset_digest"]:
        raise ValueError("准备材料评测集或规则与基线不一致。")
    previous=baseline.get("cases")
    if not isinstance(previous,list) or any(not isinstance(item,dict) or not isinstance(item.get("case_id"),str) for item in previous):
        raise ValueError("准备材料基线格式无效。")
    indexed={item["case_id"]:item for item in previous}
    if len(indexed)!=len(previous) or set(indexed)!={case.id for case in cases}:
        raise ValueError("准备材料基线样例不完整。")
    for case in cases:
        item=indexed[case.id]
        if item.get("kind")!=case.kind or not isinstance(item.get("passed"),bool) or not isinstance(item.get("checks"),dict) or not item["checks"] or any(not isinstance(value,bool) for value in item["checks"].values()):
            raise ValueError("准备材料基线缺少有效检查。")
        metrics_value=item.get("metrics",{}).get("failed_checks")
        if isinstance(metrics_value,bool) or not isinstance(metrics_value,(int,float)) or not math.isfinite(metrics_value) or metrics_value<0:
            raise ValueError("准备材料基线指标无效。")
    return indexed


def evaluate_preparation_dataset(dataset_path, baseline_path=None, max_score_drop=2, on_case=None):
    # Keep the common CLI signature; this suite has boolean gates, not JD scores.
    raw=Path(dataset_path).read_bytes()
    dataset=PreparationDataset.model_validate_json(raw)
    report={"evaluation_version":EVALUATION_VERSION,"report_schema_version":2,"dataset_version":dataset.version,
        "dataset_digest":hashlib.sha256(raw).hexdigest(),"started_at":datetime.now(timezone.utc).isoformat(),"cases":[],"regressions":[],"passed":False}
    previous=validate_preparation_baseline(report,dataset.cases,json.loads(Path(baseline_path).read_text())) if baseline_path else None
    for index,case in enumerate(dataset.cases,1):
        start=time.perf_counter()
        provenance=capture_provenance("materials" if case.kind=="materials" else "mock_interview").model_dump(mode="json")
        try:
            checker=check_materials if case.kind=="materials" else check_interview
            checks,counts=checker(dataset.contexts[case.context_id],case)
            failed=[key for key,passed in checks.items() if not passed]
            output={"case_id":case.id,"kind":case.kind,"passed":not failed,"checks":checks,
                "metrics":{**counts,"check_count":len(checks),"failed_checks":len(failed)},"failures":failed}
        except Exception as exc:
            output={"case_id":case.id,"kind":case.kind,"passed":False,"checks":{},"metrics":{},"error":safe_failure(exc),"failures":["preparation_generation_failed"]}
        output.update(provenance=provenance,duration_ms=max(0,round((time.perf_counter()-start)*1000)))
        report["cases"].append(output)
        if on_case:on_case(output,index,len(dataset.cases))
        if previous:
            old=previous[case.id]
            reasons=[key for key,passed in old["checks"].items() if passed and not output["checks"].get(key)]
            if not output["metrics"]:reasons.append("无法生成评测指标")
            if reasons:report["regressions"].append({"case_id":case.id,"reasons":reasons})
    report.update(passed=all(item["passed"] for item in report["cases"]) and not report["regressions"],completed_at=datetime.now(timezone.utc).isoformat())
    return report
