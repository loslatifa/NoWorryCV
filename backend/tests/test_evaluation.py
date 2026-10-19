from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.services.evaluation import compare_baseline, evaluate_dataset

DATASET = Path(__file__).resolve().parents[2] / "evals/resume_quality_v1.json"


def test_fixed_synthetic_suite_runs_and_reports_metrics_without_resume_text():
    report = evaluate_dataset(DATASET)
    assert report["passed"]
    assert len(report["cases"]) == 4
    assert {case["metrics"]["language"] for case in report["cases"]} == {"zh", "en"}
    assert {case["metrics"]["hiring_track"] for case in report["cases"]} == {"campus", "intern", "experienced"}
    assert all(case["metrics"]["traceability_coverage"] == 1 for case in report["cases"])
    text = json.dumps(report, ensure_ascii=False)
    assert "Candidate C" not in text and "候选人甲" not in text and "resume_text" not in text
    assert not compare_baseline(report, report)


def test_regression_gate_fails_when_score_or_truthfulness_deteriorates():
    baseline = evaluate_dataset(DATASET)
    report = deepcopy(baseline)
    metrics = report["cases"][0]["metrics"]
    metrics["score"] -= 5
    metrics["traceability_coverage"] = 0.5
    metrics["unsupported_claims"] = 1
    metrics["risk_level"] = "high"
    regressions = compare_baseline(report, baseline)
    assert len(regressions) == 1
    assert len(regressions[0]["reasons"]) == 4


def test_baseline_must_use_identical_dataset_and_complete_case_ids():
    report = evaluate_dataset(DATASET)
    baseline = deepcopy(report)
    baseline["dataset_digest"] = "different-dataset"
    with pytest.raises(ValueError): compare_baseline(report, baseline)
    baseline = deepcopy(report)
    baseline["cases"].pop()
    with pytest.raises(ValueError): compare_baseline(report, baseline)


def test_real_user_dataset_is_rejected_instead_of_silently_added(tmp_path):
    dataset = json.loads(DATASET.read_text())
    dataset["data_policy"] = "user_resumes"
    path = tmp_path / "unreviewed.json"
    path.write_text(json.dumps(dataset))
    with pytest.raises(ValueError): evaluate_dataset(path)


def test_contact_details_must_be_removed_from_reviewed_dataset(tmp_path):
    dataset = json.loads(DATASET.read_text())
    dataset["cases"][0]["input"]["confirmed_candidate_profile"]["basics"]["email"] = "private@example.com"
    path = tmp_path / "contact.json"
    path.write_text(json.dumps(dataset))
    with pytest.raises(ValueError): evaluate_dataset(path)


def test_provider_failure_is_redacted_and_fails_quality_gate(monkeypatch):
    def fail(*args):
        raise RuntimeError("secret request with candidate@example.com")
    monkeypatch.setattr("backend.app.services.evaluation.evaluate_case", fail)
    report = evaluate_dataset(DATASET)
    assert not report["passed"]
    text = json.dumps(report)
    assert "candidate@example.com" not in text and "secret request" not in text


def test_invalid_baseline_is_rejected_before_any_model_call_even_if_generation_would_fail(monkeypatch, tmp_path):
    baseline=evaluate_dataset(DATASET)
    baseline["dataset_digest"]="wrong"
    path=tmp_path/"baseline.json";path.write_text(json.dumps(baseline))
    def forbidden(*args): raise AssertionError("Must not call the model")
    monkeypatch.setattr("backend.app.services.evaluation.evaluate_case",forbidden)
    with pytest.raises(ValueError,match="规则版本不同"):
        evaluate_dataset(DATASET,path)


@pytest.mark.parametrize("mutation", ["duplicate", "missing_metrics", "negative", "nan", "boolean", "bad_risk"])
def test_malformed_baseline_is_not_accepted(mutation):
    report=evaluate_dataset(DATASET);baseline=deepcopy(report)
    if mutation=="duplicate": baseline["cases"].append(deepcopy(baseline["cases"][0]))
    elif mutation=="missing_metrics": baseline["cases"][0]["metrics"]={}
    elif mutation=="bad_risk": baseline["cases"][0]["metrics"]["risk_level"]="other"
    else: baseline["cases"][0]["metrics"]["score"]={"negative":-1,"nan":float("nan"),"boolean":True}[mutation]
    with pytest.raises(ValueError): compare_baseline(report,baseline)


def test_partial_failures_do_not_hide_regressions_in_other_cases(monkeypatch, tmp_path):
    baseline=evaluate_dataset(DATASET)
    path=tmp_path/"baseline.json";path.write_text(json.dumps(baseline))
    def changed(case):
        if case["id"]==baseline["cases"][0]["case_id"]: raise RuntimeError("private input")
        result=deepcopy(next(item for item in baseline["cases"] if item["case_id"]==case["id"]))
        result["metrics"]["score"]-=5
        return result
    monkeypatch.setattr("backend.app.services.evaluation.evaluate_case",changed)
    progress=[]
    report=evaluate_dataset(DATASET,path,on_case=lambda item,current,total:progress.append((item["case_id"],current,total)))
    assert not report["passed"] and len(report["regressions"])==4
    assert report["cases"][0]["provenance"]["provider"]=="stub"
    assert report["cases"][0]["provenance"]["processing_mode"]=="application"
    assert progress[-1][1:]==(4,4) and len(progress)==4
    assert all(item["duration_ms"]>=0 for item in report["cases"])
    assert "private" not in json.dumps(report)


def test_unexpected_pipeline_error_retains_stage_type_and_safe_code_location(monkeypatch):
    class BrokenPipeline:
        def __init__(self, progress_callback): self.progress=progress_callback
        def run(self, payload):
            self.progress("rewrite",70,"private candidate message")
            raise KeyError("private candidate key")
    monkeypatch.setattr("backend.app.services.evaluation.ResumeTailorOrchestrator",BrokenPipeline)
    report=evaluate_dataset(DATASET)
    assert not report["passed"]
    error=report["cases"][0]["error"]
    assert error["stage"]=="rewrite" and error["error_type"]=="KeyError"
    assert error["location"]["file"]=="services/evaluation.py"
    assert error["location"]["function"]=="evaluate_case" and error["location"]["line"]>0
    assert "private" not in json.dumps(report)
