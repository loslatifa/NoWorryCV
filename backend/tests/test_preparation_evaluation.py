from copy import deepcopy
import json
from pathlib import Path

import pytest

from backend.app.services.preparation_evaluation import evaluate_preparation_dataset
from backend.app.services.llm.structured import StructuredLLMError

DATASET=Path(__file__).resolve().parents[2]/"evals/preparation_quality_v1.json"


def test_preparation_suite_covers_both_languages_materials_and_interview_risk_boundaries_without_private_outputs(tmp_path,monkeypatch):
    monkeypatch.chdir(tmp_path)
    progress=[]
    report=evaluate_preparation_dataset(DATASET,on_case=lambda case,current,total:progress.append((case["case_id"],current,total)))
    assert report["passed"] and len(report["cases"])==10
    assert {item["kind"] for item in report["cases"]}=={"materials","interview"}
    assert all(all(item["checks"].values()) for item in report["cases"])
    assert progress[-1][1:]==(10,10)
    serialized=json.dumps(report,ensure_ascii=False)
    for private in ("20%","40%","99%","候选人","resume_text","fact_cards","api_key","jd_text"):
        assert private not in serialized
    assert not list(tmp_path.rglob("*.sqlite3"))  # No user stores or task queues are opened.


@pytest.mark.parametrize("change",["data_policy","email","context_id","duplicate_case","unconfirmed_only","contradictory_expectations"])
def test_invalid_preparation_dataset_is_rejected_before_model_calls(tmp_path,monkeypatch,change):
    data=json.loads(DATASET.read_text())
    if change=="data_policy":data["data_policy"]="user_data"
    elif change=="email":data["contexts"]["zh"]["candidate_profile"]["basics"]["email"]="private@example.com"
    elif change=="context_id":data["cases"][0]["context_id"]="missing"
    elif change=="duplicate_case":data["cases"].append(deepcopy(data["cases"][0]))
    elif change=="unconfirmed_only":
        for fact in data["contexts"]["zh"]["fact_cards"]:fact["confirmed"]=False
    else:data["cases"][2].update(required_issue_kinds=["inconsistent"],forbidden_issue_kinds=["inconsistent"])
    target=tmp_path/"invalid.json";target.write_text(json.dumps(data))
    def forbidden(*args):raise AssertionError("Must validate before invoking the model")
    monkeypatch.setattr("backend.app.services.preparation_evaluation.generate_pack",forbidden)
    monkeypatch.setattr("backend.app.services.preparation_evaluation.MockInterviewAgent.evaluate",forbidden)
    with pytest.raises(ValueError):evaluate_preparation_dataset(target)


def test_preparation_baseline_and_partial_failures_keep_all_regressions(tmp_path,monkeypatch):
    baseline=evaluate_preparation_dataset(DATASET)
    file=tmp_path/"baseline.json";file.write_text(json.dumps(baseline))
    assert evaluate_preparation_dataset(DATASET,file)["passed"]
    def failure(*args):raise StructuredLLMError("private provider text",agent_name="materials")
    monkeypatch.setattr("backend.app.services.preparation_evaluation.generate_pack",failure)
    report=evaluate_preparation_dataset(DATASET,file)
    assert not report["passed"] and len(report["regressions"])==2
    assert len(report["cases"])==10 and sum(item["passed"] for item in report["cases"])==8
    assert "private" not in json.dumps(report)


@pytest.mark.parametrize("change",["digest","duplicate","no_checks","invalid_metric"])
def test_invalid_baseline_fails_before_any_provider_call(tmp_path,monkeypatch,change):
    baseline=evaluate_preparation_dataset(DATASET)
    if change=="digest":baseline["dataset_digest"]="wrong"
    elif change=="duplicate":baseline["cases"].append(deepcopy(baseline["cases"][0]))
    elif change=="no_checks":baseline["cases"][0]["checks"]={}
    else:baseline["cases"][0]["metrics"]["failed_checks"]=float("nan")
    target=tmp_path/"invalid.json";target.write_text(json.dumps(baseline))
    def forbidden(*args):raise AssertionError("No model calls for an invalid baseline")
    monkeypatch.setattr("backend.app.services.preparation_evaluation.generate_pack",forbidden)
    with pytest.raises(ValueError):evaluate_preparation_dataset(DATASET,target)


def test_manually_expected_risks_are_gates_independent_of_rule_fallback(monkeypatch):
    from backend.app.agents.mock_interview import deterministic_feedback
    def erase(self,session,answer):
        feedback=deterministic_feedback(session,answer);feedback.issues=[]
        return feedback
    monkeypatch.setattr("backend.app.services.preparation_evaluation.MockInterviewAgent.evaluate",erase)
    report=evaluate_preparation_dataset(DATASET)
    failures={item["case_id"]:item for item in report["cases"] if not item["passed"]}
    assert "interview-inflated-zh" in failures and "interview-project-metric-isolation-en" in failures
    assert not failures["interview-inflated-zh"]["checks"]["required_issue_kinds"]
    assert not failures["interview-inflated-zh"]["checks"]["rule_risks_retained"]
