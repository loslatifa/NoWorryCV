from typing import List

from backend.app.agents.base import BaseAgent
from backend.app.agents.base import _NO_FALLBACK
from backend.app.schemas.agent_outputs import InterviewPrepDocumentStructuredOutput
from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.prep import InterviewPrepDocument
from backend.app.schemas.review import ReviewBundle
from backend.app.schemas.strategy import GapAnalysis, ResumeDraft, RewriteStrategy
from backend.app.services.llm.structured import StructuredLLMError


class InterviewPrepAgent(BaseAgent):
    name = "interview_prep"
    llm_metadata = {"max_tokens": 900}

    def run(
        self,
        candidate_profile: CandidateProfile,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        gap_analysis: GapAnalysis,
        rewrite_strategy: RewriteStrategy,
        draft: ResumeDraft,
        latest_review: ReviewBundle,
        language: str,
        force_fallback: bool = False,
    ) -> InterviewPrepDocument:
        fallback = self._run_fallback(
            candidate_profile,
            fact_cards,
            jd_profile,
            gap_analysis,
            rewrite_strategy,
            draft,
            latest_review,
            language,
        )
        fallback_result = self.maybe_use_fallback(fallback, force_fallback=force_fallback)
        if fallback_result is not _NO_FALLBACK:
            return fallback_result

        try:
            structured_document = self.invoke_structured(
                context=self._build_llm_context(
                    candidate_profile,
                    fact_cards,
                    jd_profile,
                    gap_analysis,
                    rewrite_strategy,
                    draft,
                    latest_review,
                    language,
                ),
                response_model=InterviewPrepDocumentStructuredOutput,
            )
            document = InterviewPrepDocument(
                title=structured_document.title,
                prep_summary=structured_document.prep_summary,
                likely_focus_areas=structured_document.likely_focus_areas,
                ba_gu_questions=structured_document.ba_gu_questions,
                project_deep_dive_questions=structured_document.project_deep_dive_questions,
                experience_deep_dive_questions=structured_document.experience_deep_dive_questions,
                behavioral_questions=structured_document.behavioral_questions,
                risk_alerts=structured_document.risk_alerts,
                answer_framework=structured_document.answer_framework,
            )
            return self._normalize_document(document, fallback)
        except StructuredLLMError as exc:
            return self.fallback_on_error(exc, fallback)

    def _build_llm_context(
        self,
        candidate_profile: CandidateProfile,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        gap_analysis: GapAnalysis,
        rewrite_strategy: RewriteStrategy,
        draft: ResumeDraft,
        latest_review: ReviewBundle,
        language: str,
    ) -> dict:
        del fact_cards
        experience_items = [
            {
                "heading": item.heading,
                "subheading": item.subheading,
                "bullets": item.bullets[:2],
            }
            for item in draft.experience_section[:3]
        ]
        project_items = [
            {
                "heading": item.heading,
                "subheading": item.subheading,
                "bullets": item.bullets[:2],
            }
            for item in draft.project_section[:2]
        ]
        work_highlights = [
            {
                "company": experience.company,
                "title": experience.title,
                "achievements": experience.achievements[:2],
            }
            for experience in candidate_profile.work_experiences[:2]
        ]
        project_highlights = [
            {
                "name": project.name,
                "role": project.role,
                "bullets": project.bullets[:2],
                "skills_used": project.skills_used[:3],
            }
            for project in candidate_profile.projects[:2]
        ]
        return {
            "language": language,
            "jd_profile": {
                "job_title": jd_profile.job_title,
                "department": jd_profile.department,
                "hiring_track": jd_profile.hiring_track,
                "must_have_skills": jd_profile.must_have_skills[:4],
                "keywords": jd_profile.keywords[:6],
                "responsibilities": jd_profile.responsibilities[:3],
                "domain_signals": jd_profile.domain_signals[:3],
            },
            "gap_analysis": {
                "recommended_focus": gap_analysis.recommended_focus[:6],
                "risk_points": gap_analysis.risk_points[:4],
                "strengths": gap_analysis.strengths[:4],
            },
            "rewrite_strategy": {
                "audience_hint": rewrite_strategy.audience_hint,
                "summary_style": rewrite_strategy.summary_style,
                "section_priority": rewrite_strategy.section_priority[:5],
            },
            "resume_draft": {
                "headline": draft.headline,
                "summary": draft.summary,
                "skills_section": draft.skills_section[:8],
                "experience_section": experience_items,
                "project_section": project_items,
            },
            "candidate_signals": {
                "work_highlights": work_highlights,
                "project_highlights": project_highlights,
                "education": candidate_profile.education[:2],
            },
            "latest_review": {
                "ats_score": latest_review.ats_report.score,
                "risk_level": latest_review.compliance_report.risk_level,
                "unsupported_claims": latest_review.compliance_report.unsupported_claims[:2],
                "exaggeration_warnings": latest_review.compliance_report.exaggeration_warnings[:3],
                "critic_issues": latest_review.critic_report.minor_issues[:4],
            },
        }

    def _run_fallback(
        self,
        candidate_profile: CandidateProfile,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        gap_analysis: GapAnalysis,
        rewrite_strategy: RewriteStrategy,
        draft: ResumeDraft,
        latest_review: ReviewBundle,
        language: str,
    ) -> InterviewPrepDocument:
        del fact_cards, rewrite_strategy, language
        likely_focus_areas = list(dict.fromkeys((gap_analysis.recommended_focus + jd_profile.must_have_skills + jd_profile.keywords)[:6]))
        ba_gu_questions = self._build_bagu_questions(jd_profile)
        project_questions = self._build_project_questions(candidate_profile, jd_profile)
        experience_questions = self._build_experience_questions(candidate_profile, draft, jd_profile)
        behavioral_questions = self._build_behavioral_questions(jd_profile)
        risk_alerts = self._build_risk_alerts(gap_analysis, latest_review)
        answer_framework = [
            "先讲背景和目标，再讲你具体做了什么。",
            "尽量补上指标、结果或决策依据，不要只说参与过。",
            "如果是校招或实习，优先讲项目、课程、竞赛和实习中的真实动作。",
            "如果被追问细节，补充你如何判断、如何协作、最终带来什么结果。",
        ]

        document = InterviewPrepDocument(
            title="{0} 面试准备文档".format(jd_profile.job_title or "岗位"),
            prep_summary=self._build_prep_summary(jd_profile, likely_focus_areas),
            likely_focus_areas=likely_focus_areas,
            ba_gu_questions=ba_gu_questions,
            project_deep_dive_questions=project_questions,
            experience_deep_dive_questions=experience_questions,
            behavioral_questions=behavioral_questions,
            risk_alerts=risk_alerts,
            answer_framework=answer_framework,
        )
        document.markdown = self._render_markdown(document)
        return document

    def _normalize_document(self, document: InterviewPrepDocument, fallback: InterviewPrepDocument) -> InterviewPrepDocument:
        normalized = InterviewPrepDocument(
            title=(document.title or fallback.title).strip(),
            prep_summary=(document.prep_summary or fallback.prep_summary).strip(),
            likely_focus_areas=(document.likely_focus_areas or fallback.likely_focus_areas)[:8],
            ba_gu_questions=(document.ba_gu_questions or fallback.ba_gu_questions)[:8],
            project_deep_dive_questions=(document.project_deep_dive_questions or fallback.project_deep_dive_questions)[:8],
            experience_deep_dive_questions=(document.experience_deep_dive_questions or fallback.experience_deep_dive_questions)[:8],
            behavioral_questions=(document.behavioral_questions or fallback.behavioral_questions)[:6],
            risk_alerts=(document.risk_alerts or fallback.risk_alerts)[:8],
            answer_framework=(document.answer_framework or fallback.answer_framework)[:6],
        )
        normalized.markdown = (document.markdown or "").strip() or self._render_markdown(normalized)
        return normalized

    def _build_prep_summary(self, jd_profile: JDProfile, focus_areas: List[str]) -> str:
        focus = "、".join(focus_areas[:4]) or "岗位关键能力"
        return "这份定制简历已经围绕 {0} 做了重排，面试时最可能围绕 {1} 追问你的真实经历和判断过程。".format(
            jd_profile.job_title or "目标岗位",
            focus,
        )

    def _build_bagu_questions(self, jd_profile: JDProfile) -> List[str]:
        questions = []
        for skill in jd_profile.must_have_skills[:4]:
            questions.append("请用自己的话解释 {0} 在这个岗位里的作用，并准备一个真实案例。".format(skill))
        if jd_profile.department == "product":
            questions.append("如果资源有限，你会如何做需求优先级排序？")
        if jd_profile.department == "data":
            questions.append("如果指标突然异常，你会如何建立口径、定位原因并输出结论？")
        if jd_profile.domain_signals:
            questions.append("结合 {0} 语境，这个岗位最核心的业务指标会是什么？".format("、".join(jd_profile.domain_signals[:2])))
        return questions[:6]

    def _build_project_questions(self, candidate_profile: CandidateProfile, jd_profile: JDProfile) -> List[str]:
        questions = []
        for project in candidate_profile.projects[:3]:
            prompt = "请讲清楚项目“{0}”的背景、目标、你的动作和最终结果。".format(project.name)
            questions.append(prompt)
            if jd_profile.must_have_skills:
                questions.append("在项目“{0}”里，你是如何体现 {1} 的？".format(project.name, jd_profile.must_have_skills[0]))
        return list(dict.fromkeys(questions))[:6]

    def _build_experience_questions(
        self,
        candidate_profile: CandidateProfile,
        draft: ResumeDraft,
        jd_profile: JDProfile,
    ) -> List[str]:
        questions = []
        for item in draft.experience_section[:3]:
            if item.bullets:
                questions.append("你在“{0}”这段经历里，最能证明岗位匹配度的一条 bullet 是什么？请展开讲。".format(item.heading))
        for experience in candidate_profile.work_experiences[:2]:
            if experience.achievements:
                questions.append("请量化说明你在 {0} 的结果是如何达成的。".format(experience.company or experience.title or "上一段经历"))
        if jd_profile.hiring_track == "campus":
            questions.append("如果面试官质疑你的经验不足，你会用哪段项目或实习经历证明自己能胜任？")
        return list(dict.fromkeys(questions))[:6]

    def _build_behavioral_questions(self, jd_profile: JDProfile) -> List[str]:
        questions = ["请准备一个你推动合作、解决分歧并拿到结果的真实案例。"]
        if jd_profile.hiring_track == "experienced":
            questions.append("请准备一个你在信息不完整时做判断并承担结果的案例。")
        if jd_profile.hiring_track == "campus":
            questions.append("请准备一个你快速学习新知识并完成任务的案例。")
        if "跨团队协作" in jd_profile.keywords or "协作" in "".join(jd_profile.responsibilities):
            questions.append("如果多个团队目标不一致，你会如何对齐并推进项目？")
        return questions[:4]

    def _build_risk_alerts(self, gap_analysis: GapAnalysis, latest_review: ReviewBundle) -> List[str]:
        items = []
        items.extend(gap_analysis.risk_points[:3])
        items.extend(latest_review.compliance_report.exaggeration_warnings[:2])
        items.extend(latest_review.compliance_report.seniority_mismatches[:2])
        items.extend(latest_review.critic_report.minor_issues[:3])
        return list(dict.fromkeys(items))[:6]

    def _render_markdown(self, document: InterviewPrepDocument) -> str:
        lines = [
            "# {0}".format(document.title),
            "",
            "## 准备总览",
            document.prep_summary,
            "",
            "## 预计高频考点",
        ]
        lines.extend("- {0}".format(item) for item in document.likely_focus_areas)
        lines.extend(["", "## 基础八股题"])
        lines.extend("- {0}".format(item) for item in document.ba_gu_questions)
        lines.extend(["", "## 项目经历拷打"])
        lines.extend("- {0}".format(item) for item in document.project_deep_dive_questions)
        lines.extend(["", "## 简历经历深挖"])
        lines.extend("- {0}".format(item) for item in document.experience_deep_dive_questions)
        lines.extend(["", "## 行为面试题"])
        lines.extend("- {0}".format(item) for item in document.behavioral_questions)
        lines.extend(["", "## 风险提醒"])
        lines.extend("- {0}".format(item) for item in document.risk_alerts)
        lines.extend(["", "## 建议回答框架"])
        lines.extend("- {0}".format(item) for item in document.answer_framework)
        return "\n".join(lines).strip()
