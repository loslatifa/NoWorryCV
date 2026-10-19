"""Deterministic quality gates over reviewed synthetic inputs; outputs contain metrics only."""
import hashlib
import json
import math
from pathlib import Path
import re
import time
from datetime import datetime, timezone

from backend.app.agents.orchestrator import ResumeTailorOrchestrator
from backend.app.schemas.run_state import TailorRunInput
from backend.app.services.llm.diagnostics import safe_failure
from backend.app.services.provenance import capture_provenance

EVALUATION_VERSION = "resume-quality-v1"


class CaseGenerationError(RuntimeError):
    def __init__(self, stage):
        super().__init__("Evaluation pipeline failed.")
        self.stage = stage


def evaluate_case(case):
    stage = {"name":"queued"}
    def progress(name, *_args):
        stage["name"] = name
    try:
        result = ResumeTailorOrchestrator(progress_callback=progress).run(TailorRunInput.model_validate(case["input"]))
    except Exception as exc:
        raise CaseGenerationError(stage["name"]) from exc
    draft = result.final_package.draft
    report = result.reviews[-1]
    facts = {fact.id for fact in result.fact_cards if fact.confirmed}
    traces = {trace.draft_span: trace.fact_ids for trace in draft.traceability}
    bullets = []
    for section_name in ("experience_section", "project_section"):
        for section_index, section in enumerate(getattr(draft, section_name), 1):
            for bullet_index, text in enumerate(section.bullets, 1):
                if text.strip():
                    span = f"{section_name}.{section_index}.bullets.{bullet_index}"
                    bullets.append(bool(traces.get(span)) and set(traces[span]).issubset(facts))
    coverage = sum(bullets) / len(bullets) if bullets else 0
    text = " ".join([draft.headline, draft.summary] + draft.skills_section
                    + [bullet for section in draft.experience_section + draft.project_section for bullet in section.bullets])
    expected = case["expectations"]
    forbidden_hits = [phrase for phrase in expected.get("forbidden_claims", []) if phrase.casefold() in text.casefold()]
    missing_skills = [skill for skill in expected.get("required_skills", []) if skill.casefold() not in " ".join(draft.skills_section).casefold()]
    metrics = {
        "score": report.ats_report.score,
        "traceability_coverage": round(coverage, 4), "bullet_count": len(bullets),
        "unsupported_claims": len(report.compliance_report.unsupported_claims),
        "risk_level": report.compliance_report.risk_level,
        "forbidden_claims_count": len(forbidden_hits), "missing_skills_count": len(missing_skills),
        "hiring_track": result.jd_profile.hiring_track, "language": result.resolved_language,
    }
    failures = []
    if metrics["score"] < expected.get("minimum_score", 0): failures.append("JD 匹配参考分低于样例阈值")
    if coverage < expected.get("minimum_traceability_coverage", 1): failures.append("经历条目的事实溯源覆盖不足")
    if metrics["unsupported_claims"]: failures.append("存在审查未支持的表述")
    if forbidden_hits: failures.append("出现样例明确禁止的虚构表述")
    if missing_skills: failures.append("未保留样例要求的已确认技能")
    if metrics["risk_level"] == "high": failures.append("真实性审查为高风险")
    if metrics["hiring_track"] != case["hiring_track"]: failures.append("招聘类型识别不符合样例")
    if metrics["language"] != case["language"]: failures.append("输出语言不符合样例")
    return {"case_id": case["id"], "passed": not failures, "metrics": metrics, "failures": failures,
            "provenance": result.provenance.model_dump(mode="json")}


def validate_baseline(report, baseline):
    if not isinstance(baseline, dict):
        raise ValueError("基线必须为评测报告。")
    if report["dataset_digest"] != baseline.get("dataset_digest") or report["evaluation_version"] != baseline.get("evaluation_version"):
        raise ValueError("评测集或评测规则版本不同，不能作为回归基线。")
    cases = baseline.get("cases")
    if not isinstance(cases, list) or any(not isinstance(case, dict) or not isinstance(case.get("case_id"), str) for case in cases):
        raise ValueError("基线样例格式无效。")
    old_cases = {case["case_id"]: case for case in cases}
    if len(old_cases) != len(cases) or set(old_cases) != {case["case_id"] for case in report["cases"]}:
        raise ValueError("基线样例不完整。")
    for case in cases:
        metrics = case.get("metrics")
        if not isinstance(case.get("passed"), bool) or not isinstance(metrics, dict):
            raise ValueError("基线缺少有效指标。")
        for field in ("score", "traceability_coverage", "unsupported_claims"):
            value = metrics.get(field)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
                raise ValueError("基线指标无效。")
        if metrics["score"] > 100 or metrics["traceability_coverage"] > 1 or metrics.get("risk_level") not in {"low", "medium", "high"}:
            raise ValueError("基线指标超出范围。")
    return old_cases


def compare_baseline(report, baseline, max_score_drop=2):
    old_cases = validate_baseline(report, baseline)
    regressions = []
    risk_rank = {"low": 0, "medium": 1, "high": 2}
    for case in report["cases"]:
        old = old_cases[case["case_id"]]
        before, after = old["metrics"], case["metrics"]
        if not after:
            regressions.append({"case_id":case["case_id"], "reasons":["无法生成评测指标"]})
            continue
        reasons = []
        if old["passed"] and not case["passed"]: reasons.append("原通过样例未通过")
        if after["score"] < before["score"] - max_score_drop: reasons.append("匹配参考分回退")
        if after["traceability_coverage"] < before["traceability_coverage"]: reasons.append("事实溯源覆盖回退")
        if after["unsupported_claims"] > before["unsupported_claims"]: reasons.append("未支持表述增加")
        if risk_rank.get(after["risk_level"], 2) > risk_rank.get(before["risk_level"], 2): reasons.append("真实性风险增加")
        if reasons: regressions.append({"case_id": case["case_id"], "reasons": reasons})
    return regressions


def evaluate_dataset(dataset_path, baseline_path=None, max_score_drop=2, on_case=None):
    if max_score_drop < 0:
        raise ValueError("分数容差必须非负。")
    raw = Path(dataset_path).read_bytes()
    dataset = json.loads(raw)
    if not isinstance(dataset, dict) or dataset.get("data_policy") != "synthetic_only":
        raise ValueError("仅允许已审核的合成评测集，禁止直接加入用户原始资料。")
    cases = dataset.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测集不能为空。")
    if any(not isinstance(case, dict) or not isinstance(case.get("id"), str) or not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,79}", case["id"]) for case in cases):
        raise ValueError("样例 ID 必须使用非空短标识。")
    if len({case["id"] for case in cases}) != len(cases):
        raise ValueError("评测集不能为空，样例 ID 必须唯一。")
    for case in cases:
        payload = TailorRunInput.model_validate(case["input"])
        if not isinstance(case.get("expectations"), dict) or case.get("hiring_track") not in {"campus", "intern", "experienced", "unknown"} or case.get("language") not in {"zh", "en"}:
            raise ValueError("评测样例缺少有效断言。")
        if not payload.confirmed_candidate_profile or not payload.confirmed_fact_cards or any(not fact.confirmed or not fact.text.strip() for fact in payload.confirmed_fact_cards):
            raise ValueError("评测输入必须包含已确认候选人及事实。")
        basics = payload.confirmed_candidate_profile.basics.model_dump()
        if basics.get("email") or basics.get("phone"):
            raise ValueError("评测集应去除候选人联系方式。")
    report = {"evaluation_version": EVALUATION_VERSION, "report_schema_version": 2, "dataset_version": dataset["version"],
              "dataset_digest": hashlib.sha256(raw).hexdigest(), "cases": [], "passed":False, "regressions":[],
              "started_at":datetime.now(timezone.utc).isoformat()}
    baseline = json.loads(Path(baseline_path).read_text(encoding="utf-8")) if baseline_path else None
    if baseline_path:
        validate_baseline({**report, "cases":[{"case_id":case["id"]} for case in cases]}, baseline)
    outputs = []
    for case in cases:
        started = time.perf_counter()
        runtime = capture_provenance(case["input"].get("processing_mode", "full")).model_dump(mode="json")
        try:
            output = evaluate_case(case)
        except Exception as exc:
            # Report only allowlisted diagnostics, never provider messages or response bodies.
            failure = safe_failure(exc.__cause__ if isinstance(exc, CaseGenerationError) else exc,
                pipeline_stage=exc.stage if isinstance(exc, CaseGenerationError) else "unknown")
            output = {"case_id":case["id"], "passed":False, "metrics":{}, "error":failure,
                      "failures":[failure["message"]], "provenance":runtime}
        output["duration_ms"] = max(0, round((time.perf_counter() - started) * 1000))
        outputs.append(output)
        if on_case is not None:
            on_case(output, len(outputs), len(cases))
    report.update(cases=outputs, passed=all(case["passed"] for case in outputs), completed_at=datetime.now(timezone.utc).isoformat())
    if baseline_path:
        report["regressions"] = compare_baseline(report, baseline, max_score_drop)
        report["passed"] = report["passed"] and not report["regressions"]
    return report
