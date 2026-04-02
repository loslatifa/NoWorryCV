from typing import List

from backend.app.agents.base import BaseAgent
from backend.app.agents.base import _NO_FALLBACK
from backend.app.schemas.agent_outputs import JDReviewDocumentStructuredOutput
from backend.app.schemas.jd import JDProfile, KnowledgeReviewCard
from backend.app.schemas.prep import JDReviewDocument
from backend.app.services.llm.structured import StructuredLLMError


class JDReviewDocAgent(BaseAgent):
    name = "jd_review_doc"
    llm_metadata = {"max_tokens": 1000}

    def run(
        self,
        jd_profile: JDProfile,
        jd_text: str,
        review_cards: List[KnowledgeReviewCard],
        force_fallback: bool = False,
    ) -> JDReviewDocument:
        fallback = self._run_fallback(jd_profile, jd_text, review_cards)
        fallback_result = self.maybe_use_fallback(fallback, force_fallback=force_fallback)
        if fallback_result is not _NO_FALLBACK:
            return fallback_result

        try:
            structured_document = self.invoke_structured(
                context={
                    "jd_profile": jd_profile,
                    "jd_text": jd_text,
                    "review_cards": review_cards,
                },
                response_model=JDReviewDocumentStructuredOutput,
            )
            document = JDReviewDocument(
                title=structured_document.title,
                role_summary=structured_document.role_summary,
                hiring_track_hint=structured_document.hiring_track_hint,
                core_requirements=structured_document.core_requirements,
                key_topics=review_cards[:5],
                foundational_questions=structured_document.foundational_questions,
                review_plan=structured_document.review_plan,
            )
            return self._normalize_document(document, fallback)
        except StructuredLLMError as exc:
            return self.fallback_on_error(exc, fallback)

    def _run_fallback(
        self,
        jd_profile: JDProfile,
        jd_text: str,
        review_cards: List[KnowledgeReviewCard],
    ) -> JDReviewDocument:
        del jd_text
        track_hint = self._build_hiring_track_hint(jd_profile.hiring_track)
        core_requirements = (jd_profile.must_have_skills + jd_profile.responsibilities[:3])[:6]
        foundational_questions = [card.sample_question for card in review_cards[:3] if card.sample_question]
        review_plan = self._build_review_plan(jd_profile, review_cards)
        document = JDReviewDocument(
            title="{0} JD 复习文档".format(jd_profile.job_title or "岗位"),
            role_summary=self._build_role_summary(jd_profile),
            hiring_track_hint=track_hint,
            core_requirements=core_requirements,
            key_topics=review_cards[:5],
            foundational_questions=foundational_questions[:6],
            review_plan=review_plan,
        )
        document.markdown = self._render_markdown(document)
        return document

    def _normalize_document(self, document: JDReviewDocument, fallback: JDReviewDocument) -> JDReviewDocument:
        normalized = JDReviewDocument(
            title=(document.title or fallback.title).strip(),
            role_summary=(document.role_summary or fallback.role_summary).strip(),
            hiring_track_hint=(document.hiring_track_hint or fallback.hiring_track_hint).strip(),
            core_requirements=(document.core_requirements or fallback.core_requirements)[:6],
            key_topics=(document.key_topics or fallback.key_topics)[:5],
            foundational_questions=(document.foundational_questions or fallback.foundational_questions)[:8],
            review_plan=(document.review_plan or fallback.review_plan)[:6],
        )
        normalized.markdown = (document.markdown or "").strip() or self._render_markdown(normalized)
        return normalized

    def _build_role_summary(self, jd_profile: JDProfile) -> str:
        focus = "、".join((jd_profile.must_have_skills or jd_profile.keywords)[:3]) or "基础能力与岗位匹配度"
        return "这个岗位当前最关注的方向是 {0}，并会结合 {1} 语境判断你是否具备可落地的真实经验。".format(
            focus,
            jd_profile.department or "业务",
        )

    def _build_hiring_track_hint(self, hiring_track: str) -> str:
        if hiring_track == "campus":
            return "这是校招语境，面试通常更关注基础扎实度、项目证据、学习能力和表达清晰度。"
        if hiring_track == "intern":
            return "这是实习语境，面试通常更关注你是否具备基础方法、执行能力和快速上手潜力。"
        if hiring_track == "experienced":
            return "这是社招语境，面试通常会重点追问职责范围、业务结果、判断依据和跨团队推进。"
        return "招聘类型未完全识别，建议同时准备基础知识、项目证据和岗位相关经历。"

    def _build_review_plan(self, jd_profile: JDProfile, review_cards: List[KnowledgeReviewCard]) -> List[str]:
        steps = []
        if jd_profile.must_have_skills:
            steps.append("优先复习必备能力：{0}。".format("、".join(jd_profile.must_have_skills[:4])))
        if review_cards:
            steps.append("先准备 1 到 2 个能覆盖 {0} 的真实案例。".format("、".join(review_cards[0].keywords[:2] or [review_cards[0].title])))
        if jd_profile.responsibilities:
            steps.append("对照岗位职责，准备你如何完成“{0}”的回答。".format(jd_profile.responsibilities[0]))
        steps.append(self._build_hiring_track_hint(jd_profile.hiring_track))
        return steps[:4]

    def _render_markdown(self, document: JDReviewDocument) -> str:
        lines = [
            "# {0}".format(document.title),
            "",
            "## 岗位理解",
            document.role_summary,
            "",
            "## 招聘类型提醒",
            document.hiring_track_hint,
            "",
            "## 核心要求",
        ]
        lines.extend("- {0}".format(item) for item in document.core_requirements)
        lines.extend(["", "## 重点知识点"])
        for topic in document.key_topics:
            lines.extend(
                [
                    "### {0}".format(topic.title),
                    "- 为什么重要：{0}".format(topic.why_it_matters),
                    "- 复习提示：{0}".format(topic.review_tip),
                    "- 可能会问：{0}".format(topic.sample_question),
                ]
            )
        lines.extend(["", "## 基础题准备"])
        lines.extend("- {0}".format(item) for item in document.foundational_questions)
        lines.extend(["", "## 建议复习顺序"])
        lines.extend("- {0}".format(item) for item in document.review_plan)
        return "\n".join(lines).strip()
