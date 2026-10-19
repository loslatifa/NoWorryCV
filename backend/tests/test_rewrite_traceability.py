from pathlib import Path
import json

import pytest

from backend.app.agents.compliance import TruthfulnessComplianceAgent
from backend.app.agents.rewrite import ResumeRewriteAgent
from backend.app.core.config import reset_settings_cache
from backend.app.schemas.agent_outputs import ResumeDraftStructuredOutput, TraceableSectionItem
from backend.app.schemas.common import FactCard, TraceabilityRecord
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.run_state import TailorRunInput
from backend.app.schemas.strategy import GapAnalysis, ResumeDraft, ResumeSectionItem, RewriteStrategy
from backend.app.services.confirmed_profile import align_confirmed_profile


def compose(output, facts, fallback=None, merge=True):
    return ResumeRewriteAgent()._from_structured_output(
        output, facts, JDProfile(job_title="数据工程师"), GapAnalysis(strengths=["SQL"],recommended_focus=["SQL"]),
        "zh", RewriteStrategy(include_projects=True), fallback or ResumeDraft(headline="示例用户"), allow_fallback_merge=merge)


def test_cleaning_empty_sections_and_sorting_move_fact_links_with_their_bullets():
    facts=[FactCard(id="low",category="work_bullet",text="维护报表接口"),
           FactCard(id="high",category="work_bullet",text="使用 SQL 开发数据看板，查询耗时降低20%。")]
    output=ResumeDraftStructuredOutput(experience_section=[
        TraceableSectionItem(heading="空区块",bullets=[{"text":"","fact_ids":["low"]}]),
        TraceableSectionItem(heading="示例公司",bullets=[{"text":"","fact_ids":["low"]},
            {"text":facts[0].text,"fact_ids":["low"]},{"text":facts[1].text,"fact_ids":["high"]}])])
    draft=compose(output,facts,merge=False)
    assert len(draft.experience_section)==1
    assert draft.experience_section[0].bullets==[facts[1].text,facts[0].text]
    assert {item.draft_span:item.fact_ids for item in draft.traceability}=={
        "experience_section.1.bullets.1":["high"],"experience_section.1.bullets.2":["low"]}
    assert TruthfulnessComplianceAgent().run(draft,facts).unsupported_claims==[]


@pytest.mark.parametrize("trigger",["education","experience"])
def test_fallback_in_one_module_does_not_replace_another_modules_model_citations(trigger):
    facts=[FactCard(id="work",category="work_bullet",text="开发并测试报表服务"),
        FactCard(id="old",category="project_bullet",text="整理历史项目数据"),
        FactCard(id="new",category="project_bullet",text="使用 Python 完成批处理程序测试")]
    fallback=ResumeDraft(headline="示例用户",education_section=["示例大学"],
        experience_section=[ResumeSectionItem(heading="示例公司",bullets=[facts[0].text])] if trigger=="experience" else [],
        project_section=[ResumeSectionItem(heading="项目",bullets=[facts[1].text])],
        traceability=[TraceabilityRecord(draft_span="experience_section.1.bullets.1",fact_ids=["work"])] if trigger=="experience" else [])
    fallback.traceability.append(TraceabilityRecord(draft_span="project_section.1.bullets.1",fact_ids=["old"]))
    output=ResumeDraftStructuredOutput(project_section=[TraceableSectionItem(heading="项目",bullets=[{"text":facts[2].text,"fact_ids":["new"]}])])
    draft=compose(output,facts,fallback)
    assert draft.project_section[0].bullets==[facts[2].text]
    links={item.draft_span:item.fact_ids for item in draft.traceability}
    assert links["project_section.1.bullets.1"]==["new"]
    if trigger=="experience":assert links["experience_section.1.bullets.1"]==["work"]
    assert draft.education_section==["示例大学"]
    assert TruthfulnessComplianceAgent().run(draft,facts).unsupported_claims==[]


def test_unknown_citations_do_not_support_new_claims_but_exact_facts_can_recover_their_link():
    facts=[FactCard(id="fact",category="project_bullet",text="使用 Python 编写并测试接口服务")]
    output=ResumeDraftStructuredOutput(project_section=[TraceableSectionItem(heading="项目",bullets=[
        {"text":"独立负责全部开发，收入提升80%。","fact_ids":["invented"]},
        {"text":facts[0].text,"fact_ids":[]}])])
    draft=compose(output,facts,merge=False)
    assert draft.project_section[0].bullets==[facts[0].text]
    assert draft.traceability[0].fact_ids==["fact"]
    assert "80%" not in draft.markdown


def test_deduplication_combines_only_the_same_statement_sources():
    facts=[FactCard(id="one",category="project_bullet",text="Built a Python API service"),
        FactCard(id="two",category="project_bullet",text="Built a Python API service")]
    output=ResumeDraftStructuredOutput(project_section=[TraceableSectionItem(heading="API",bullets=[
        {"text":facts[0].text,"fact_ids":["one"]},{"text":facts[1].text,"fact_ids":["two"]}])])
    draft=compose(output,facts,merge=False)
    assert len(draft.project_section[0].bullets)==1
    assert draft.traceability[0].fact_ids==["one","two"]


def test_orphan_traces_cannot_satisfy_missing_final_bullet_evidence():
    draft=ResumeDraft(project_section=[ResumeSectionItem(heading="项目",bullets=["条目一","条目二"])],traceability=[
        TraceabilityRecord(draft_span="project_section.1.bullets.1",fact_ids=["one"]),
        TraceabilityRecord(draft_span="project_section.2.bullets.1",fact_ids=["two"])])
    assert not ResumeRewriteAgent()._has_traceable_content(draft)


def test_project_only_candidate_does_not_trigger_an_unnecessary_compact_model_request(monkeypatch):
    monkeypatch.setenv("LLM_STRICT_MODE","true");reset_settings_cache()
    case=json.loads((Path(__file__).resolve().parents[2]/"evals/resume_quality_v1.json").read_text())["cases"][0]
    payload=TailorRunInput.model_validate(case["input"])
    candidate=payload.confirmed_candidate_profile;facts=payload.confirmed_fact_cards
    align_confirmed_profile(candidate,facts)
    class Model:
        is_available=True
        calls=0
        def generate(self,**kwargs):
            self.calls+=1
            return ResumeDraftStructuredOutput(headline="候选人甲",skills_section=["SQL","Python"],
                project_section=[TraceableSectionItem(heading="数据看板",bullets=[{"text":facts[0].text,"fact_ids":[facts[0].id]}])],
                education_section=["示例大学 | Bachelor | Computer Science"])
    model=Model()
    draft=ResumeRewriteAgent(model).run(candidate,facts,JDProfile(job_title="数据分析师",hiring_track="campus"),
        GapAnalysis(),RewriteStrategy(include_projects=True,audience_hint="campus"),"zh")
    assert model.calls==1
    assert draft.project_section[0].bullets==[facts[0].text]
    assert draft.traceability[0].fact_ids==[facts[0].id]
