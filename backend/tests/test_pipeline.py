from backend.app.graph.resume_tailor_graph import run_tailor_pipeline
from backend.app.schemas.run_state import TailorRunInput


def test_tailor_pipeline_generates_reviewed_resume() -> None:
    payload = TailorRunInput(
        resume_text=(
            "张三\n"
            "产品经理\n\n"
            "工作经历\n"
            "A公司 | 产品经理\n"
            "- 负责用户增长策略\n"
            "- 推动 A/B 测试与漏斗优化，提升转化率 12%\n\n"
            "项目经历\n"
            "增长分析看板\n"
            "- 使用 SQL 和 Tableau 搭建周报仪表盘\n\n"
            "技能\n"
            "Python, SQL, Tableau, A/B Testing\n"
        ),
        jd_text=(
            "高级产品经理\n"
            "职责：负责增长策略、数据分析、跨团队协作。\n"
            "要求：熟悉 SQL、A/B 测试、用户研究。"
        ),
        output_language="zh",
        max_iterations=2,
    )

    result = run_tailor_pipeline(payload)

    assert result.status == "completed"
    assert result.iterations >= 1
    assert result.candidate_profile.basics.name == "张三"
    assert result.jd_profile.job_title == "高级产品经理"
    assert result.final_package.draft.markdown
    assert "工作经历" in result.final_package.draft.markdown
    assert result.reviews
    assert "当前以" not in result.final_package.draft.summary
