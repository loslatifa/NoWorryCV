import time
from typing import Callable, Dict, List, Optional

from langgraph.graph import END, StateGraph

from backend.app.agents.ats import ATSScoringAgent
from backend.app.agents.compliance import TruthfulnessComplianceAgent
from backend.app.agents.critic import CriticAgent
from backend.app.agents.gap_analysis import GapAnalysisAgent
from backend.app.agents.jd_analyst import JDAnalystAgent
from backend.app.agents.jd_review_card import JDReviewCardAgent
from backend.app.agents.jd_review_doc import JDReviewDocAgent
from backend.app.agents.interview_prep import InterviewPrepAgent
from backend.app.agents.resume_parser import ResumeParserAgent
from backend.app.agents.rewrite import ResumeRewriteAgent
from backend.app.agents.strategy import StrategyAgent
from backend.app.core.config import get_settings
from backend.app.schemas.jd import JDProfile, KnowledgeReviewCard
from backend.app.schemas.prep import JDReviewDocument
from backend.app.schemas.review import ReviewBundle
from backend.app.schemas.run_state import TailorRunInput, TailorRunResult, TailorRunState
from backend.app.schemas.strategy import FinalResumePackage


class ResumeTailorOrchestrator:
    def __init__(
        self,
        progress_callback: Optional[Callable[[str, int, str, Optional[List[KnowledgeReviewCard]]], None]] = None,
    ) -> None:
        self.resume_parser = ResumeParserAgent()
        self.jd_analyst = JDAnalystAgent()
        self.jd_review_card_agent = JDReviewCardAgent()
        self.jd_review_doc_agent = JDReviewDocAgent()
        self.gap_analysis = GapAnalysisAgent()
        self.strategy_agent = StrategyAgent()
        self.rewrite_agent = ResumeRewriteAgent()
        self.compliance_agent = TruthfulnessComplianceAgent()
        self.ats_agent = ATSScoringAgent()
        self.critic_agent = CriticAgent()
        self.interview_prep_agent = InterviewPrepAgent()
        self.progress_callback = progress_callback
        self.graph = self._build_graph()

    def parse_resume(self, payload: TailorRunInput):
        profile, _ = self.resume_parser.run(
            payload.resume_text,
            payload.candidate_notes,
            force_fallback=self._prefer_fast_mode(payload),
        )
        return profile

    def analyze_jd(self, payload: TailorRunInput) -> JDProfile:
        jd_profile = self.jd_analyst.run(payload.jd_text, force_fallback=self._prefer_fast_mode(payload))
        jd_profile.review_cards = self.jd_review_card_agent.run(
            jd_profile,
            payload.jd_text,
            force_fallback=self._prefer_fast_mode(payload),
        )
        return jd_profile

    def build_jd_review_doc(self, payload: TailorRunInput) -> JDReviewDocument:
        jd_profile = self.analyze_jd(payload)
        return self.jd_review_doc_agent.run(
            jd_profile,
            payload.jd_text,
            jd_profile.review_cards,
            force_fallback=self._prefer_fast_mode(payload),
        )

    def run(self, payload: TailorRunInput, run_id: Optional[str] = None) -> TailorRunResult:
        generated_run_id = run_id
        if not generated_run_id:
            field = TailorRunState.model_fields["run_id"]
            generated_run_id = field.default_factory() if field.default_factory else ""
        self._report_progress("queued", 3, "任务已创建，准备优先分析 JD。")
        initial_state = TailorRunState(
            run_id=generated_run_id,
            input=payload,
            resolved_language=payload.output_language,
        )
        final_state = self.graph.invoke(initial_state.model_dump(mode="json"))
        state = TailorRunState.model_validate(final_state)
        state.stop_reason = self._derive_stop_reason(state)
        if state.final_package is None:
            state.final_package = self._build_final_package(state, state.resolved_language)
        self._report_progress("completed", 100, "简历定制完成，结果已准备好。")
        return self._build_result(state)

    def _build_graph(self):
        graph = StateGraph(dict)
        graph.add_node("analyze_jd", self._analyze_jd_node)
        graph.add_node("review_cards", self._review_cards_node)
        graph.add_node("jd_review_doc", self._jd_review_doc_node)
        graph.add_node("parse_resume", self._parse_resume_node)
        graph.add_node("gap_analysis", self._gap_analysis_node)
        graph.add_node("strategy", self._strategy_node)
        graph.add_node("rewrite", self._rewrite_node)
        graph.add_node("review", self._review_node)
        graph.add_node("refine_strategy", self._refine_strategy_node)
        graph.add_node("finalize", self._finalize_node)

        graph.set_entry_point("analyze_jd")
        graph.add_edge("analyze_jd", "review_cards")
        graph.add_edge("review_cards", "jd_review_doc")
        graph.add_edge("jd_review_doc", "parse_resume")
        graph.add_edge("parse_resume", "gap_analysis")
        graph.add_edge("gap_analysis", "strategy")
        graph.add_edge("strategy", "rewrite")
        graph.add_edge("rewrite", "review")
        graph.add_conditional_edges(
            "review",
            self._route_after_review,
            {
                "refine_strategy": "refine_strategy",
                "finalize": "finalize",
            },
        )
        graph.add_edge("refine_strategy", "rewrite")
        graph.add_edge("finalize", END)
        return graph.compile()

    def _analyze_jd_node(self, raw_state: Dict) -> Dict:
        state = TailorRunState.model_validate(raw_state)
        self._report_progress("analyze_jd", 10, "正在分析 JD 结构与岗位要求。")
        started_at = time.perf_counter()
        jd_profile = self.jd_analyst.run(
            state.input.jd_text,
            force_fallback=self._prefer_fast_mode(state.input),
        )
        state.jd_profile = jd_profile
        if state.input.output_language == "auto":
            state.resolved_language = jd_profile.language or state.resolved_language
        else:
            state.resolved_language = state.input.output_language
        state.execution_log.append(
            self.jd_analyst.record(
                "Parsed JD into structured profile.",
                {
                    "keyword_count": str(len(jd_profile.keywords)),
                    "provider": self.jd_analyst.llm_service.provider_name,
                    "elapsed_ms": str(int((time.perf_counter() - started_at) * 1000)),
                },
            )
        )
        self._report_progress("analyze_jd", 18, "JD 已结构化，正在生成复习看板。")
        return state.model_dump(mode="json")

    def _review_cards_node(self, raw_state: Dict) -> Dict:
        state = TailorRunState.model_validate(raw_state)
        self._report_progress("review_cards", 22, "正在提炼 JD 重点知识点。")
        started_at = time.perf_counter()
        review_cards = self.jd_review_card_agent.run(
            state.jd_profile,
            state.input.jd_text,
            force_fallback=self._prefer_fast_mode(state.input),
        )
        state.jd_profile.review_cards = review_cards
        state.execution_log.append(
            self.jd_review_card_agent.record(
                "Generated JD review cards.",
                {
                    "card_count": str(len(review_cards)),
                    "provider": self.jd_review_card_agent.llm_service.provider_name,
                    "elapsed_ms": str(int((time.perf_counter() - started_at) * 1000)),
                },
            )
        )
        self._report_progress(
            "review_cards",
            30,
            "JD 重点已提炼，等待时可以先复习这些知识点。",
            review_cards=review_cards,
        )
        return state.model_dump(mode="json")

    def _jd_review_doc_node(self, raw_state: Dict) -> Dict:
        state = TailorRunState.model_validate(raw_state)
        self._report_progress("jd_review_doc", 32, "正在整理 JD 复习文档。")
        started_at = time.perf_counter()
        state.jd_review_doc = self.jd_review_doc_agent.run(
            state.jd_profile,
            state.input.jd_text,
            state.jd_profile.review_cards,
            force_fallback=self._prefer_fast_mode(state.input),
        )
        state.execution_log.append(
            self.jd_review_doc_agent.record(
                "Generated JD review document.",
                {
                    "topic_count": str(len(state.jd_review_doc.key_topics)),
                    "provider": self.jd_review_doc_agent.llm_service.provider_name,
                    "elapsed_ms": str(int((time.perf_counter() - started_at) * 1000)),
                },
            )
        )
        self._report_progress("jd_review_doc", 36, "JD 复习文档已整理，正在解析简历。")
        return state.model_dump(mode="json")

    def _parse_resume_node(self, raw_state: Dict) -> Dict:
        state = TailorRunState.model_validate(raw_state)
        self._report_progress("parse_resume", 38, "正在解析简历并抽取事实卡片。")
        started_at = time.perf_counter()
        candidate_profile, fact_cards = self.resume_parser.run(
            state.input.resume_text,
            state.input.candidate_notes,
            force_fallback=self._prefer_fast_mode(state.input),
        )
        state.candidate_profile = candidate_profile
        state.fact_cards = fact_cards
        if state.resolved_language == "auto":
            state.resolved_language = candidate_profile.basics.language or "en"
        state.execution_log.append(
            self.resume_parser.record(
                "Parsed resume into candidate profile and fact cards.",
                {
                    "fact_count": str(len(fact_cards)),
                    "provider": self.resume_parser.llm_service.provider_name,
                    "elapsed_ms": str(int((time.perf_counter() - started_at) * 1000)),
                },
            )
        )
        self._report_progress("parse_resume", 44, "已完成简历解析，正在匹配经历与 JD。")
        return state.model_dump(mode="json")

    def _gap_analysis_node(self, raw_state: Dict) -> Dict:
        state = TailorRunState.model_validate(raw_state)
        self._report_progress("gap_analysis", 50, "正在分析简历与 JD 的匹配差距。")
        started_at = time.perf_counter()
        state.gap_analysis = self.gap_analysis.run(
            state.candidate_profile,
            state.fact_cards,
            state.jd_profile,
            force_fallback=self._prefer_fast_mode(state.input),
        )
        state.execution_log.append(
            self.gap_analysis.record(
                "Completed gap analysis.",
                {
                    "fit_score": str(state.gap_analysis.fit_score_initial),
                    "elapsed_ms": str(int((time.perf_counter() - started_at) * 1000)),
                },
            )
        )
        self._report_progress("gap_analysis", 58, "已完成匹配分析，正在制定改写策略。")
        return state.model_dump(mode="json")

    def _strategy_node(self, raw_state: Dict) -> Dict:
        state = TailorRunState.model_validate(raw_state)
        self._report_progress("strategy", 62, "正在制定改写策略与内容优先级。")
        started_at = time.perf_counter()
        state.rewrite_strategy = self.strategy_agent.run(
            state.candidate_profile,
            state.gap_analysis,
            state.fact_cards,
            state.jd_profile,
            state.resolved_language,
            force_fallback=self._prefer_fast_mode(state.input),
        )
        state.execution_log.append(
            self.strategy_agent.record(
                "Created initial rewrite strategy.",
                {
                    "provider": self.strategy_agent.llm_service.provider_name,
                    "elapsed_ms": str(int((time.perf_counter() - started_at) * 1000)),
                },
            )
        )
        self._report_progress("strategy", 70, "改写策略已生成，正在撰写定制简历。")
        return state.model_dump(mode="json")

    def _rewrite_node(self, raw_state: Dict) -> Dict:
        state = TailorRunState.model_validate(raw_state)
        state.current_iteration += 1
        self._report_progress(
            "rewrite",
            min(78, 68 + state.current_iteration * 4),
            "正在生成第 {0} 版定制简历。".format(state.current_iteration),
        )
        started_at = time.perf_counter()
        draft = self.rewrite_agent.run(
            state.candidate_profile,
            state.fact_cards,
            state.jd_profile,
            state.gap_analysis,
            state.rewrite_strategy,
            state.resolved_language,
        )
        state.drafts.append(draft)
        state.execution_log.append(
            self.rewrite_agent.record(
                "Generated tailored resume draft.",
                {
                    "iteration": str(state.current_iteration),
                    "provider": self.rewrite_agent.llm_service.provider_name,
                    "elapsed_ms": str(int((time.perf_counter() - started_at) * 1000)),
                },
            )
        )
        self._report_progress(
            "rewrite",
            min(85, 74 + state.current_iteration * 5),
            "已生成第 {0} 版草稿，正在审查真实性与 ATS。".format(state.current_iteration),
        )
        return state.model_dump(mode="json")

    def _review_node(self, raw_state: Dict) -> Dict:
        state = TailorRunState.model_validate(raw_state)
        self._report_progress(
            "review",
            min(90, 80 + state.current_iteration * 3),
            "正在审查真实性、ATS 和文案质量。",
        )
        started_at = time.perf_counter()
        draft = state.drafts[-1]
        compliance_report = self.compliance_agent.run(draft, state.fact_cards)
        ats_report = self.ats_agent.run(draft, state.jd_profile)
        critic_report = self.critic_agent.run(
            draft,
            state.jd_profile,
            state.rewrite_strategy,
            compliance_report,
            ats_report,
            force_fallback=self._prefer_fast_mode(state.input),
        )
        state.reviews.append(
            ReviewBundle(
                iteration=state.current_iteration,
                compliance_report=compliance_report,
                ats_report=ats_report,
                critic_report=critic_report,
            )
        )
        state.execution_log.append(
            self.critic_agent.record(
                "Completed draft review bundle.",
                {
                    "iteration": str(state.current_iteration),
                    "ats_score": str(ats_report.score),
                    "risk_level": compliance_report.risk_level,
                    "provider": self.critic_agent.llm_service.provider_name,
                    "elapsed_ms": str(int((time.perf_counter() - started_at) * 1000)),
                },
            )
        )
        self._report_progress(
            "review",
            min(94, 84 + state.current_iteration * 4),
            "已完成第 {0} 轮审查，正在判断是否继续优化。".format(state.current_iteration),
        )
        return state.model_dump(mode="json")

    def _refine_strategy_node(self, raw_state: Dict) -> Dict:
        state = TailorRunState.model_validate(raw_state)
        latest_review = state.reviews[-1]
        self._report_progress(
            "refine_strategy",
            min(88, 76 + state.current_iteration * 5),
            "正在根据审查结果收紧下一轮策略。",
        )
        started_at = time.perf_counter()
        state.rewrite_strategy = self.strategy_agent.refine(
            state.rewrite_strategy,
            latest_review.critic_report,
            force_fallback=self._prefer_fast_mode(state.input),
        )
        state.execution_log.append(
            self.strategy_agent.record(
                "Refined rewrite strategy after review feedback.",
                {
                    "iteration": str(state.current_iteration),
                    "elapsed_ms": str(int((time.perf_counter() - started_at) * 1000)),
                },
            )
        )
        self._report_progress(
            "refine_strategy",
            min(88, 76 + state.current_iteration * 5),
            "正在根据审查结果微调策略，准备下一轮改写。",
        )
        return state.model_dump(mode="json")

    def _finalize_node(self, raw_state: Dict) -> Dict:
        state = TailorRunState.model_validate(raw_state)
        self._report_progress("finalize", 96, "正在整理最终结果与复习文档。")
        started_at = time.perf_counter()
        if state.jd_review_doc is None:
            state.jd_review_doc = self.jd_review_doc_agent.run(
                state.jd_profile,
                state.input.jd_text,
                state.jd_profile.review_cards,
                force_fallback=self._prefer_fast_mode(state.input),
            )
        state.interview_prep_doc = self.interview_prep_agent.run(
            state.candidate_profile,
            state.fact_cards,
            state.jd_profile,
            state.gap_analysis,
            state.rewrite_strategy,
            state.drafts[-1],
            state.reviews[-1],
            state.resolved_language,
            force_fallback=self._prefer_fast_mode(state.input),
        )
        state.stop_reason = self._derive_stop_reason(state)
        state.final_package = self._build_final_package(state, state.resolved_language)
        state.execution_log.append(
            self.interview_prep_agent.record(
                "Prepared final documents and package.",
                {"elapsed_ms": str(int((time.perf_counter() - started_at) * 1000))},
            )
        )
        self._report_progress("finalize", 99, "正在整理最终结果、JD 复习文档和面试准备文档。")
        return state.model_dump(mode="json")

    def _route_after_review(self, raw_state: Dict) -> str:
        state = TailorRunState.model_validate(raw_state)
        latest_review = state.reviews[-1]
        if self._should_stop(
            latest_review.compliance_report.risk_level,
            latest_review.ats_report.score,
            latest_review.critic_report.major_issues,
        ):
            state.stop_reason = "quality_threshold_met"
            raw_state["stop_reason"] = state.stop_reason
            return "finalize"

        if state.current_iteration >= state.input.max_iterations:
            state.stop_reason = "max_iterations_reached"
            raw_state["stop_reason"] = state.stop_reason
            return "finalize"

        if len(state.reviews) > 1:
            previous_score = state.reviews[-2].ats_report.score
            if latest_review.ats_report.score <= previous_score + 2:
                state.stop_reason = "score_plateau"
                raw_state["stop_reason"] = state.stop_reason
                return "finalize"

        raw_state["stop_reason"] = ""
        return "refine_strategy"

    def _should_stop(self, risk_level: str, ats_score: int, major_issues: int) -> bool:
        return risk_level == "low" and ats_score >= 80 and major_issues == 0

    def _build_final_package(self, state: TailorRunState, language: str) -> FinalResumePackage:
        latest_draft = state.drafts[-1]
        latest_review = state.reviews[-1]
        if language == "zh":
            change_log = self._build_change_log(state)
            fit_summary = "当前版本 ATS 评分 {0}，初始匹配度 {1}，招聘类型识别为 {2}。".format(
                latest_review.ats_report.score,
                state.gap_analysis.fit_score_initial,
                self._humanize_hiring_track(state.jd_profile.hiring_track),
            )
        else:
            change_log = self._build_change_log(state)
            fit_summary = "ATS score is {0}; initial fit score was {1}; hiring track was detected as {2}.".format(
                latest_review.ats_report.score,
                state.gap_analysis.fit_score_initial,
                state.jd_profile.hiring_track or "unknown",
            )

        risk_notes = list(state.gap_analysis.risk_points[:3])
        if latest_review.compliance_report.unsupported_claims:
            risk_notes.append("存在无法追溯到 fact cards 的表述，需要人工确认。")
        risk_notes.extend(latest_review.ats_report.format_warnings[:3])

        return FinalResumePackage(
            draft=latest_draft,
            change_log=change_log,
            fit_summary=fit_summary,
            risk_notes=risk_notes,
            jd_review_doc=state.jd_review_doc,
            interview_prep_doc=state.interview_prep_doc,
        )

    def _build_result(self, state: TailorRunState) -> TailorRunResult:
        return TailorRunResult(
            run_id=state.run_id,
            status="completed",
            iterations=state.current_iteration,
            stop_reason=state.stop_reason,
            candidate_profile=state.candidate_profile,
            jd_profile=state.jd_profile,
            gap_analysis=state.gap_analysis,
            rewrite_strategy=state.rewrite_strategy,
            drafts=state.drafts,
            reviews=state.reviews,
            final_package=state.final_package,
        )

    def _derive_stop_reason(self, state: TailorRunState) -> str:
        if state.stop_reason:
            return state.stop_reason
        if not state.reviews:
            return ""
        latest_review = state.reviews[-1]
        if self._should_stop(
            latest_review.compliance_report.risk_level,
            latest_review.ats_report.score,
            latest_review.critic_report.major_issues,
        ):
            return "quality_threshold_met"
        if state.current_iteration >= state.input.max_iterations:
            return "max_iterations_reached"
        if len(state.reviews) > 1:
            previous_score = state.reviews[-2].ats_report.score
            if latest_review.ats_report.score <= previous_score + 2:
                return "score_plateau"
        return ""

    def _prefer_fast_mode(self, payload: TailorRunInput) -> bool:
        return (not get_settings().llm_strict_mode) and payload.processing_mode == "fast"

    def _report_progress(
        self,
        stage: str,
        percent: int,
        message: str,
        review_cards: Optional[List[KnowledgeReviewCard]] = None,
    ) -> None:
        if self.progress_callback:
            self.progress_callback(stage, percent, message, review_cards)

    def _humanize_hiring_track(self, hiring_track: str) -> str:
        mapping = {
            "campus": "校招",
            "intern": "实习",
            "experienced": "社招",
            "unknown": "未识别",
        }
        return mapping.get(hiring_track, hiring_track or "未识别")

    def _build_change_log(self, state: TailorRunState):
        if state.resolved_language != "zh":
            return [
                "Prioritized the most relevant verified skills and experience for the JD.",
                "Kept traceability anchored to source facts to avoid unsupported claims.",
                "Applied ATS and critic feedback during the optimization loop.",
            ]

        track = state.jd_profile.hiring_track
        if track == "campus":
            return [
                "已按校招岗位视角重排内容，优先展示教育、项目与实习证据。",
                "已避免使用资深社招口吻包装项目或课程经历。",
                "已保留基于原始事实的 traceability，避免虚构或越界扩写。",
            ]
        if track == "intern":
            return [
                "已按实习岗位视角重排内容，优先展示项目实践、基础能力与上手速度。",
                "已避免把短期实践写成成熟管理经验。",
                "已保留基于原始事实的 traceability，避免虚构或越界扩写。",
            ]
        return [
            "已优先突出与 JD 重合度更高的真实技能与经历。",
            "已保留基于原始事实的 traceability，避免虚构或越界扩写。",
            "已结合 ATS 结果与 critic 建议进行自动优化。",
        ]
