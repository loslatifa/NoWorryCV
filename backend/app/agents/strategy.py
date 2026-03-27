from typing import List

from backend.app.agents.base import BaseAgent
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.review import CriticReport
from backend.app.schemas.strategy import GapAnalysis, RewriteStrategy
from backend.app.services.scoring.heuristics import normalize_token


class StrategyAgent(BaseAgent):
    name = "strategy"

    def run(
        self,
        candidate_profile: CandidateProfile,
        gap_analysis: GapAnalysis,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        language: str,
        force_fallback: bool = False,
    ) -> RewriteStrategy:
        fallback = self._run_fallback(candidate_profile, gap_analysis, fact_cards, jd_profile, language)
        if force_fallback or not self.llm_service.is_available:
            return fallback

        try:
            strategy = self.invoke_structured(
                context={
                    "candidate_profile": candidate_profile,
                    "gap_analysis": gap_analysis,
                    "fact_cards": fact_cards,
                    "jd_profile": jd_profile,
                    "language": language,
                },
                response_model=RewriteStrategy,
            )
            return self._normalize_strategy(strategy, fact_cards, fallback)
        except StructuredLLMError:
            return fallback

    def _run_fallback(
        self,
        candidate_profile: CandidateProfile,
        gap_analysis: GapAnalysis,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        language: str,
    ) -> RewriteStrategy:
        emphasize_fact_ids = self._rank_fact_ids(fact_cards, gap_analysis.recommended_focus)
        hiring_track = getattr(jd_profile, "hiring_track", "unknown")
        is_campus_like = hiring_track in {"campus", "intern"}
        has_projects = bool(candidate_profile.projects)
        has_education = bool(candidate_profile.education)
        return RewriteStrategy(
            target_resume_style="campus_ats_clean" if is_campus_like else "experienced_ats_clean",
            audience_hint=hiring_track,
            section_priority=self._section_priority_for_track(hiring_track),
            emphasize_fact_ids=emphasize_fact_ids[:12],
            deemphasize_fact_ids=[card.id for card in fact_cards if card.id not in emphasize_fact_ids][:12],
            keyword_plan=(gap_analysis.strengths + gap_analysis.missing_keywords[:3])[:8],
            terminology_map={token: token for token in gap_analysis.strengths[:8]},
            tone_rules=self._tone_rules(language, hiring_track),
            forbidden_claims=gap_analysis.missing_keywords[:8],
            max_experiences=2 if is_campus_like else 3,
            max_bullets_per_experience=2 if is_campus_like else 3,
            max_skills=10 if is_campus_like else 12,
            include_projects=has_projects if is_campus_like else (has_projects and bool(gap_analysis.transferable_experiences)),
            summary_style="potential_and_evidence" if is_campus_like else "impact_and_scope",
            revision_notes=self._revision_notes_for_track(hiring_track, has_projects, has_education),
        )

    def refine(
        self,
        strategy: RewriteStrategy,
        critic_report: CriticReport,
        force_fallback: bool = False,
    ) -> RewriteStrategy:
        fallback = self._fallback_refine(strategy, critic_report)
        if force_fallback or not self.llm_service.is_available:
            return fallback

        try:
            refined = self.invoke_structured(
                context={
                    "current_strategy": strategy,
                    "critic_report": critic_report,
                },
                response_model=RewriteStrategy,
            )
            return self._normalize_strategy(refined, [], fallback)
        except StructuredLLMError:
            return fallback

    def _fallback_refine(self, strategy: RewriteStrategy, critic_report: CriticReport) -> RewriteStrategy:
        revision_notes = list(strategy.revision_notes)
        revision_notes.extend(critic_report.next_actions[:3])
        max_bullets = strategy.max_bullets_per_experience
        max_skills = strategy.max_skills
        include_projects = strategy.include_projects
        if critic_report.major_issues > 0:
            max_bullets = min(5, max_bullets + 1)
            max_skills = min(16, max_skills + 2)
            include_projects = True
        return RewriteStrategy(
            target_resume_style=strategy.target_resume_style,
            audience_hint=strategy.audience_hint,
            section_priority=strategy.section_priority,
            emphasize_fact_ids=strategy.emphasize_fact_ids,
            deemphasize_fact_ids=strategy.deemphasize_fact_ids,
            keyword_plan=strategy.keyword_plan,
            terminology_map=strategy.terminology_map,
            tone_rules=strategy.tone_rules,
            forbidden_claims=strategy.forbidden_claims,
            max_experiences=strategy.max_experiences,
            max_bullets_per_experience=max_bullets,
            max_skills=max_skills,
            include_projects=include_projects,
            summary_style=strategy.summary_style,
            revision_notes=revision_notes,
        )

    def _normalize_strategy(
        self,
        strategy: RewriteStrategy,
        fact_cards: List[FactCard],
        fallback: RewriteStrategy,
    ) -> RewriteStrategy:
        valid_fact_ids = {card.id for card in fact_cards} if fact_cards else set(fallback.emphasize_fact_ids)
        strategy.emphasize_fact_ids = [
            fact_id for fact_id in strategy.emphasize_fact_ids if fact_id in valid_fact_ids
        ] or fallback.emphasize_fact_ids
        strategy.deemphasize_fact_ids = [
            fact_id for fact_id in strategy.deemphasize_fact_ids if fact_id in valid_fact_ids
        ] or fallback.deemphasize_fact_ids
        strategy.section_priority = self._normalize_section_priority(
            strategy.section_priority or fallback.section_priority,
            fallback.section_priority,
        )
        if not strategy.audience_hint:
            strategy.audience_hint = fallback.audience_hint
        if not strategy.keyword_plan:
            strategy.keyword_plan = fallback.keyword_plan
        strategy.keyword_plan = list(dict.fromkeys(strategy.keyword_plan))[:12]
        if not strategy.tone_rules:
            strategy.tone_rules = fallback.tone_rules
        strategy.tone_rules = list(dict.fromkeys(strategy.tone_rules))
        if not strategy.summary_style:
            strategy.summary_style = fallback.summary_style
        if not strategy.revision_notes:
            strategy.revision_notes = fallback.revision_notes
        strategy.revision_notes = list(dict.fromkeys(strategy.revision_notes))[:8]
        if strategy.max_experiences < 1:
            strategy.max_experiences = fallback.max_experiences
        if strategy.max_bullets_per_experience < 1:
            strategy.max_bullets_per_experience = fallback.max_bullets_per_experience
        if strategy.max_skills < 1:
            strategy.max_skills = fallback.max_skills
        if strategy.audience_hint not in {"campus", "experienced", "intern", "unknown", "general"}:
            strategy.audience_hint = fallback.audience_hint
        return strategy

    def _rank_fact_ids(self, fact_cards: List[FactCard], priorities: List[str]) -> List[str]:
        ranked = []
        lowered = [normalize_token(item) for item in priorities]
        for card in fact_cards:
            text = normalize_token(card.text)
            score = sum(1 for item in lowered if item and item in text)
            if score > 0:
                ranked.append((score, card.id))
        ranked.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in ranked]

    def _tone_rules(self, language: str, hiring_track: str) -> List[str]:
        if language == "zh":
            base_rules = [
                "只使用原始简历或用户补充信息可验证的事实。",
                "优先使用简洁、可扫描、ATS 友好的项目符号表达。",
                "避免夸大性形容词，优先行动词与结果表达。",
            ]
            if hiring_track in {"campus", "intern"}:
                base_rules.append("校招/实习岗位优先强调项目、实习、课程与学习能力，不要伪装成多年全职经验。")
            else:
                base_rules.append("社招岗位优先强调业务结果、职责范围、跨团队协作和可量化成果。")
            return base_rules
        base_rules = [
            "Use only facts grounded in the resume or candidate notes.",
            "Prefer concise ATS-friendly bullets.",
            "Avoid exaggerated adjectives and unsupported claims.",
        ]
        if hiring_track in {"campus", "intern"}:
            base_rules.append("For campus or intern roles, emphasize projects, internships, learning speed, and fundamentals instead of full-time ownership.")
        else:
            base_rules.append("For experienced hiring, emphasize scope, business impact, ownership, and stakeholder collaboration.")
        return base_rules

    def _section_priority_for_track(self, hiring_track: str) -> List[str]:
        if hiring_track == "campus":
            return ["summary", "education", "skills", "projects", "experience"]
        if hiring_track == "intern":
            return ["summary", "skills", "projects", "experience", "education"]
        return ["summary", "skills", "experience", "projects", "education"]

    def _revision_notes_for_track(self, hiring_track: str, has_projects: bool, has_education: bool) -> List[str]:
        if hiring_track == "campus":
            notes = [
                "初版策略：识别为校招岗位，优先突出教育背景、项目与实习证据。",
                "避免把项目包装成多年全职所有权。",
            ]
            if not has_projects:
                notes.append("项目经历较少时，改为突出课程、社团、竞赛或实习中的真实证据。")
            if not has_education:
                notes.append("教育信息不足时避免过度强调学历卖点，优先使用已有项目或实践信号。")
            return notes
        if hiring_track == "intern":
            notes = [
                "初版策略：识别为实习岗位，优先突出基础能力、项目实践和可快速上手信号。",
                "避免把短期实践写成成熟管理经验。",
            ]
            if not has_projects:
                notes.append("项目不足时，用课程作业、研究任务或工具实践补充能力证据。")
            return notes
        return [
            "初版策略：识别为社招/通用岗位，优先前置最相关的工作经历、职责范围和量化成果。",
            "保持 ATS 结构简洁，并控制关键词自然落位。",
        ]

    def _normalize_section_priority(self, current: List[str], fallback: List[str]) -> List[str]:
        allowed = ["summary", "skills", "experience", "projects", "education"]
        normalized = [section for section in current if section in allowed]
        if not normalized:
            return fallback
        for section in fallback:
            if section not in normalized:
                normalized.append(section)
        return normalized
