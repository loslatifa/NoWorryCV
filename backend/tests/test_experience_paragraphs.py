from fastapi.testclient import TestClient
import pytest

from backend.app.agents.resume_parser import ResumeParserAgent
from backend.app.agents.rewrite import ResumeRewriteAgent
from backend.app.main import create_app
from backend.app.schemas.candidate import CandidateProfile, WorkExperience, ProjectExperience
from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.strategy import GapAnalysis, RewriteStrategy
from backend.app.services.confirmed_profile import align_confirmed_profile


def test_paragraph_persists_with_point_sources_and_project_dates():
    client = TestClient(create_app())
    paragraph = "使用 SQL 分析数据；通过 A/B Testing 提升转化率 5.5%；维护 Power BI 看板"
    response = client.post("/api/v1/candidate-profiles", json={
        "confirmed": True, "storage_consent": True,
        "candidate_profile": {"projects": [{"id": "project-a", "name": "增长项目", "role": "负责人",
            "start_date": "2024.03", "end_date": "2024.09", "review_paragraph": paragraph}]},
        "fact_cards": [
            {"id":"old-a","category":"project_bullet","text":"使用 SQL 分析数据", "source_span":"projects.project-a.bullets.1", "confirmed":True},
            {"id":"new-b","category":"project_bullet","text":"通过 A/B Testing 提升转化率 5.5%", "source_span":"projects.project-a.bullets.new-b",
             "source_type":"user","source_excerpt":"通过 A/B Testing 提升转化率 5.5%","replaces_fact_ids":["old-b"],"confirmed":True},
            {"id":"old-c","category":"project_bullet","text":"维护 Power BI 看板", "source_span":"projects.project-a.bullets.3", "confirmed":True},
        ],
    })
    assert response.status_code == 201, response.text
    archive = response.json()
    loaded = client.get('/api/v1/candidate-profiles/' + archive['id'], headers={'X-Profile-Token':archive['access_token']}).json()
    project = loaded['candidate_profile']['projects'][0]
    assert project['review_paragraph'] == paragraph
    assert len(project['bullets']) == 3
    assert project['start_date'] == '2024.03'
    assert project['end_date'] == '2024.09'
    assert [fact['id'] for fact in loaded['fact_cards']] == ['old-a','new-b','old-c']
    assert loaded['fact_cards'][1]['replaces_fact_ids'] == ['old-b']
    assert loaded['fact_cards'][1]['source_excerpt'] != '转化率提升 3.5%'


def test_stale_paragraph_does_not_override_changed_points_or_numbers():
    profile = CandidateProfile(work_experiences=[WorkExperience(id='work-a',review_paragraph='将效率提升 13.5%')])
    facts = [FactCard(id='a',category='work_bullet',text='将效率提升 3.5%',source_span='work_experiences.work-a.bullets.1')]
    align_confirmed_profile(profile,facts)
    assert profile.work_experiences[0].review_paragraph is None
    assert profile.work_experiences[0].bullets == ['将效率提升 3.5%']


def test_unassigned_supplements_stay_independent_until_explicitly_owned():
    profile = CandidateProfile(work_experiences=[WorkExperience(id='work-a',company='公司甲')],
                               projects=[ProjectExperience(id='project-a',name='项目甲')])
    owned = FactCard(id='a',category='work_bullet',text='维护 SQL 看板',source_span='work_experiences.work-a.bullets.1')
    supplemental = FactCard(id='b',category='work_bullet',text='完成独立公益调研',source_type='user',source_span='follow_up.scope')
    facts = [owned,supplemental]
    align_confirmed_profile(profile,facts)
    assert profile.work_experiences[0].bullets == [owned.text]
    assert not profile.projects[0].bullets
    draft = ResumeRewriteAgent().run(profile,facts,JDProfile(job_title='产品经理'),GapAnalysis(),RewriteStrategy(include_projects=True),'zh')
    assert supplemental.text not in str(draft.model_dump())
    supplemental.source_span = 'projects.project-a.bullets.b'
    supplemental.category = 'project_bullet'
    align_confirmed_profile(profile,facts)
    assert profile.projects[0].bullets == [supplemental.text]
    assert profile.work_experiences[0].bullets == [owned.text]


@pytest.mark.parametrize('lines,expected',[
    (['增长实验项目 | 2024.03-2024.09','- 负责数据分析'],('2024.03','2024.09')),
    (['增长实验项目','角色：负责人','2024/03 至 2024/09','- 负责数据分析'],('2024/03','2024/09')),
    (['Analytics Project | 2024-03 to Present','- Built dashboards'],('2024-03','Present')),
    (['增长实验项目','- 负责数据分析'],(None,None)),
])
def test_project_date_extraction_keeps_explicit_header_precision(lines,expected):
    projects = ResumeParserAgent()._parse_projects(lines)
    assert len(projects) == 1
    assert (projects[0].start_date,projects[0].end_date) == expected
    assert len(projects[0].bullets) == 1
    if '角色：负责人' in lines:
        assert projects[0].role == '负责人'


def test_unlabeled_responsibility_prose_remains_project_body():
    projects = ResumeParserAgent()._parse_projects([
        '增长实验项目', '负责数据分析并协调研发', '完成实验复盘',
    ])
    assert len(projects) == 1
    assert projects[0].role is None
    assert projects[0].bullets == ['负责数据分析并协调研发', '完成实验复盘']


def test_review_only_paragraph_is_not_requested_from_resume_model():
    schema = CandidateProfile.model_json_schema()
    assert 'review_paragraph' not in schema['$defs']['WorkExperience']['properties']
    assert 'review_paragraph' not in schema['$defs']['ProjectExperience']['properties']
    profile = CandidateProfile(projects=[ProjectExperience(id='p',name='项目',review_paragraph='模型不应提供的展示段落')])
    normalized = ResumeParserAgent()._normalize_profile(profile,'项目：项目','')
    assert normalized.projects[0].review_paragraph is None
