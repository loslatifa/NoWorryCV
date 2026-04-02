from typing import List

from backend.app.agents.base import BaseAgent
from backend.app.agents.base import _NO_FALLBACK
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.strategy import GapAnalysis
from backend.app.services.scoring.heuristics import normalize_token, score_keyword_overlap, unique_preserve_order


class GapAnalysisAgent(BaseAgent):
    name = "gap_analysis"
    llm_metadata = {"max_tokens": 700}

    def run(
        self,
        candidate: CandidateProfile,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        force_fallback: bool = False,
    ) -> GapAnalysis:
        fallback = self._run_fallback(candidate, fact_cards, jd_profile)
        fallback_result = self.maybe_use_fallback(fallback, force_fallback=force_fallback)
        if fallback_result is not _NO_FALLBACK:
            return fallback_result

        try:
            analysis = self.invoke_structured(
                context=self._build_llm_context(candidate, fact_cards, jd_profile),
                response_model=GapAnalysis,
            )
            return self._normalize_gap_analysis(analysis, fallback)
        except StructuredLLMError as exc:
            try:
                compact_analysis = self.invoke_structured(
                    context=self._build_llm_context(candidate, fact_cards, jd_profile, compact_mode=True),
                    response_model=GapAnalysis,
                )
                return self._normalize_gap_analysis(compact_analysis, fallback)
            except StructuredLLMError:
                return self.fallback_on_error(exc, fallback)

    def _run_fallback(self, candidate: CandidateProfile, fact_cards: List[FactCard], jd_profile: JDProfile) -> GapAnalysis:
        candidate_tokens = self._collect_candidate_tokens(candidate, fact_cards)
        matched_keywords = [
            keyword
            for keyword in jd_profile.keywords
            if normalize_token(keyword) in {normalize_token(token) for token in candidate_tokens}
        ]
        missing_keywords = [
            keyword
            for keyword in jd_profile.must_have_skills + jd_profile.keywords
            if normalize_token(keyword) not in {normalize_token(token) for token in candidate_tokens}
        ]
        strengths = unique_preserve_order(matched_keywords)[:8]
        transferable = self._find_transferable_experiences(fact_cards, matched_keywords)
        overlap = score_keyword_overlap(candidate_tokens, jd_profile.keywords)
        fit_score = min(95, int(45 + (overlap * 45) - min(len(unique_preserve_order(missing_keywords)), 5) * 2))

        risk_points: List[str] = []
        if not strengths:
            risk_points.append("当前简历与 JD 的直接关键词重合较少，需要更多用户补充信息。")
        if missing_keywords:
            risk_points.append("存在未覆盖的 JD 要求，后续只能用相关经历做迁移表达，不能新增事实。")
        if jd_profile.hiring_track == "campus" and not (candidate.projects or candidate.education):
            risk_points.append("校招岗位通常需要教育或项目证据，当前简历中的相关信号较弱。")
        if jd_profile.hiring_track == "intern" and not candidate.projects:
            risk_points.append("实习岗位更依赖项目实践或课程作业作为能力证明，当前项目信号偏弱。")
        if jd_profile.hiring_track == "experienced":
            quantified_achievements = sum(len(experience.achievements) for experience in candidate.work_experiences)
            if quantified_achievements == 0:
                risk_points.append("社招岗位通常更看重量化成果，当前工作经历中的数字化结果偏少。")

        recommended_focus = unique_preserve_order(strengths + transferable)[:8]
        return GapAnalysis(
            fit_score_initial=max(fit_score, 20),
            strengths=strengths,
            gaps=unique_preserve_order(missing_keywords)[:10],
            transferable_experiences=transferable[:6],
            missing_keywords=unique_preserve_order(missing_keywords)[:10],
            risk_points=risk_points,
            recommended_focus=recommended_focus,
        )

    def _normalize_gap_analysis(self, analysis: GapAnalysis, fallback: GapAnalysis) -> GapAnalysis:
        analysis.fit_score_initial = min(100, max(0, analysis.fit_score_initial or fallback.fit_score_initial))
        if not analysis.strengths:
            analysis.strengths = fallback.strengths
        if not analysis.missing_keywords:
            analysis.missing_keywords = fallback.missing_keywords
        if not analysis.gaps:
            analysis.gaps = analysis.missing_keywords or fallback.gaps
        if not analysis.recommended_focus:
            analysis.recommended_focus = fallback.recommended_focus
        if not analysis.risk_points:
            analysis.risk_points = fallback.risk_points
        analysis.strengths = unique_preserve_order(analysis.strengths)[:8]
        analysis.gaps = unique_preserve_order(analysis.gaps)[:8]
        analysis.transferable_experiences = unique_preserve_order(analysis.transferable_experiences)[:6]
        analysis.missing_keywords = unique_preserve_order(analysis.missing_keywords)[:8]
        analysis.risk_points = unique_preserve_order(analysis.risk_points)[:6]
        analysis.recommended_focus = unique_preserve_order(analysis.recommended_focus)[:8]
        return analysis

    def _build_llm_context(
        self,
        candidate: CandidateProfile,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        compact_mode: bool = False,
    ) -> dict:
        top_fact_cards = self._select_relevant_fact_cards(fact_cards, jd_profile, limit=6 if compact_mode else 10)
        return {
            "compact_mode": compact_mode,
            "jd_profile": {
                "job_title": jd_profile.job_title,
                "department": jd_profile.department,
                "hiring_track": jd_profile.hiring_track,
                "must_have_skills": jd_profile.must_have_skills[:4],
                "nice_to_have_skills": jd_profile.nice_to_have_skills[:3],
                "keywords": jd_profile.keywords[:6],
                "responsibilities": jd_profile.responsibilities[:3],
                "domain_signals": jd_profile.domain_signals[:3],
            },
            "candidate_profile": {
                "skills": {
                    "hard_skills": candidate.skills.hard_skills[:8],
                    "tools": candidate.skills.tools[:6],
                    "soft_skills": candidate.skills.soft_skills[:4],
                },
                "work_experiences": [
                    {
                        "company": experience.company,
                        "title": experience.title,
                        "skills_used": experience.skills_used[:4],
                        "achievements": experience.achievements[:2],
                        "bullets": experience.bullets[:2],
                    }
                    for experience in candidate.work_experiences[:3]
                ],
                "projects": [
                    {
                        "name": project.name,
                        "role": project.role,
                        "skills_used": project.skills_used[:4],
                        "bullets": project.bullets[:2],
                    }
                    for project in candidate.projects[:2]
                ],
                "education": [
                    {
                        "school": education.school,
                        "degree": education.degree,
                        "field_of_study": education.field_of_study,
                    }
                    for education in candidate.education[:2]
                ],
            },
            "evidence_fact_cards": [
                {
                    "category": card.category,
                    "text": card.text,
                }
                for card in top_fact_cards
            ],
        }

    def _collect_candidate_tokens(self, candidate: CandidateProfile, fact_cards: List[FactCard]) -> List[str]:
        tokens: List[str] = []
        tokens.extend(candidate.skills.hard_skills)
        tokens.extend(candidate.skills.tools)
        for experience in candidate.work_experiences:
            if experience.company:
                tokens.append(experience.company)
            if experience.title:
                tokens.append(experience.title)
            tokens.extend(experience.skills_used)
        tokens.extend(card.text for card in fact_cards)
        return unique_preserve_order(tokens)

    def _find_transferable_experiences(self, fact_cards: List[FactCard], keywords: List[str]) -> List[str]:
        if not keywords:
            return [card.text for card in fact_cards[:3]]
        lowered = [normalize_token(keyword) for keyword in keywords]
        matches = []
        for card in fact_cards:
            text = normalize_token(card.text)
            if any(keyword in text for keyword in lowered):
                matches.append(card.text)
        return unique_preserve_order(matches)

    def _select_relevant_fact_cards(
        self,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        limit: int,
    ) -> List[FactCard]:
        target_tokens = unique_preserve_order(jd_profile.must_have_skills + jd_profile.keywords + jd_profile.domain_signals)

        def score(card: FactCard) -> tuple:
            normalized_text = normalize_token(card.text)
            overlap = sum(1 for token in target_tokens if normalize_token(token) and normalize_token(token) in normalized_text)
            quant_signal = 1 if any(char.isdigit() for char in card.text) else 0
            category_bonus = 1 if "bullet" in card.category or "achievement" in card.category else 0
            return (overlap, quant_signal, category_bonus, len(card.text))

        ranked = sorted(fact_cards, key=score, reverse=True)
        return ranked[:limit]
