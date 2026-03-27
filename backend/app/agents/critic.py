from backend.app.agents.base import BaseAgent
from backend.app.agents.base import _NO_FALLBACK
from backend.app.schemas.jd import JDProfile
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.schemas.review import ATSReport, ComplianceReport, CriticReport
from backend.app.schemas.strategy import ResumeDraft, RewriteStrategy


class CriticAgent(BaseAgent):
    name = "critic"

    def run(
        self,
        draft: ResumeDraft,
        jd_profile: JDProfile,
        rewrite_strategy: RewriteStrategy,
        compliance_report: ComplianceReport,
        ats_report: ATSReport,
        force_fallback: bool = False,
    ) -> CriticReport:
        fallback = self._run_fallback(draft, jd_profile, rewrite_strategy, compliance_report, ats_report)
        fallback_result = self.maybe_use_fallback(fallback, force_fallback=force_fallback)
        if fallback_result is not _NO_FALLBACK:
            return fallback_result

        try:
            critique = self.invoke_structured(
                context={
                    "resume_draft": draft,
                    "jd_profile": jd_profile,
                    "rewrite_strategy": rewrite_strategy,
                    "compliance_report": compliance_report,
                    "ats_report": ats_report,
                },
                response_model=CriticReport,
            )
            return critique
        except StructuredLLMError as exc:
            return self.fallback_on_error(exc, fallback)

    def _run_fallback(
        self,
        draft: ResumeDraft,
        jd_profile: JDProfile,
        rewrite_strategy: RewriteStrategy,
        compliance_report: ComplianceReport,
        ats_report: ATSReport,
    ) -> CriticReport:
        major_issues = 0
        minor_issues = []
        next_actions = []

        if compliance_report.risk_level == "high":
            major_issues += 1
            minor_issues.append("存在无法映射到原始事实的表述。")
            next_actions.append("移除无法追溯到 fact_cards 的句子。")
        elif compliance_report.risk_level == "medium":
            minor_issues.append("存在需要人工确认的表达风险，建议收紧 summary/headline 口吻。")
            next_actions.append("移除夸张措辞、弱化过度资历表述，并检查关键词是否自然落位。")
        if compliance_report.seniority_mismatches:
            minor_issues.extend(compliance_report.seniority_mismatches[:2])
            next_actions.append("将 summary/headline 调整为与真实资历相符的表达。")
        if compliance_report.keyword_stuffing_warnings:
            minor_issues.extend(compliance_report.keyword_stuffing_warnings[:2])
            next_actions.append("减少关键词堆砌，优先用真实经历承载技能词。")
        if compliance_report.exaggeration_warnings:
            minor_issues.extend("检测到夸张表达：{0}".format(item) for item in compliance_report.exaggeration_warnings[:2])
            next_actions.append("删除或改写夸张词，保留可验证的动作和结果。")
        if ats_report.score < 70:
            major_issues += 1
            minor_issues.append("ATS 分数偏低，结构或关键词覆盖仍需优化。")
            next_actions.append("增加与 JD 已重合的真实技能词，并前置高相关经历。")
        if ats_report.missing_keywords:
            minor_issues.append("仍有未覆盖关键词：{0}".format(", ".join(ats_report.missing_keywords[:5])))
            next_actions.append("只在有真实依据时补充或重排相关关键词。")
        minor_issues.extend(ats_report.format_warnings)

        track = jd_profile.hiring_track
        if track == "campus":
            if not draft.education_section:
                minor_issues.append("校招岗位通常需要更明确的教育背景呈现。")
                next_actions.append("补充或前置教育背景，突出学校、专业和毕业时间。")
            if not draft.project_section and not rewrite_strategy.include_projects:
                minor_issues.append("校招岗位的项目或实习证据展示偏弱。")
                next_actions.append("优先加入与 JD 相关的项目或实习 bullets。")
            if "多年" in draft.summary or "5年" in draft.summary or "3年" in draft.summary:
                major_issues += 1
                minor_issues.append("校招视角下的 summary 仍带有资深从业者口吻。")
                next_actions.append("改写 summary，强调项目、实习、课程和学习能力，而不是多年经验。")
        elif track == "intern":
            if not draft.project_section and not draft.experience_section:
                major_issues += 1
                minor_issues.append("实习岗位缺少能够证明基础能力的项目或实践内容。")
                next_actions.append("补充最相关的项目实践或短期经历，并保留真实来源。")
        elif track == "experienced":
            if not draft.experience_section:
                major_issues += 1
                minor_issues.append("社招岗位缺少工作经历模块，难以证明职责范围与结果。")
                next_actions.append("前置最相关的工作经历，并补充量化结果或职责范围。")
            elif len(draft.experience_section) < 2:
                minor_issues.append("社招岗位的工作经历展开偏少，层次感不足。")
                next_actions.append("增加第二段高相关经历，体现职责连续性和业务场景。")

        return CriticReport(
            major_issues=major_issues,
            minor_issues=list(dict.fromkeys(minor_issues))[:8],
            next_actions=list(dict.fromkeys(next_actions))[:5],
        )
