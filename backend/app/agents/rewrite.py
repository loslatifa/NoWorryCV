import re
from typing import Dict, List, Optional, Tuple

from backend.app.agents.base import BaseAgent
from backend.app.agents.base import _NO_FALLBACK
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.schemas.candidate import CandidateProfile, ProjectExperience, WorkExperience
from backend.app.schemas.agent_outputs import ResumeDraftStructuredOutput, TraceableSectionItem
from backend.app.schemas.common import FactCard, TraceabilityRecord
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.strategy import GapAnalysis, ResumeDraft, ResumeSectionItem, RewriteStrategy
from backend.app.services.scoring.heuristics import normalize_token, unique_preserve_order


class ResumeRewriteAgent(BaseAgent):
    name = "resume_rewrite"
    prompt_name = "rewrite"
    llm_metadata = {"max_tokens": 1600, "timeout_seconds": 90}
    JD_META_MARKERS = (
        "jd",
        "岗位要求",
        "任职要求",
        "加分项",
        "对应要求",
        "对应 jd",
        "匹配 jd",
        "符合 jd",
        "岗位匹配",
        "岗位需求",
    )
    ACTION_HINTS = {
        "负责",
        "推动",
        "搭建",
        "设计",
        "优化",
        "分析",
        "协调",
        "管理",
        "执行",
        "主导",
        "lead",
        "led",
        "built",
        "designed",
        "launched",
        "optimized",
        "analyzed",
        "owned",
        "managed",
    }
    RESULT_HINTS = {
        "提升",
        "降低",
        "增长",
        "转化",
        "效率",
        "复盘",
        "improve",
        "improved",
        "increase",
        "reduced",
        "result",
        "impact",
    }
    WEAK_ACTION_HINTS = {
        "参与",
        "支持",
        "协助",
        "配合",
        "跟进",
        "assist",
        "support",
        "participate",
        "helped",
    }
    GENERIC_BULLET_MARKERS = {
        "相关经验",
        "相关能力",
        "能力基础",
        "能力证明",
        "业务推进",
        "结果交付",
        "岗位场景",
        "岗位方向",
        "支持业务",
        "推动业务",
        "经验沉淀",
        "学习能力",
        "执行能力",
        "相关工作",
        "相关事项",
    }
    ABSTRACT_STYLE_MARKERS = {
        "具备",
        "积累了",
        "形成了",
        "相关经验",
        "相关实践",
        "能力基础",
        "能力证明",
        "适合",
        "支撑业务推进",
        "结果交付",
    }
    CAMPUS_PROJECT_HINTS = {
        "项目",
        "课程",
        "竞赛",
        "校园",
        "研究",
        "实验",
        "社团",
        "实习",
    }
    EXPERIENCED_SCOPE_HINTS = {
        "跨团队",
        "协同",
        "协调",
        "推进",
        "owner",
        "ownership",
        "stakeholder",
        "scope",
        "负责",
        "主导",
    }

    def run(
        self,
        candidate: CandidateProfile,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        gap_analysis: GapAnalysis,
        strategy: RewriteStrategy,
        language: str,
    ) -> ResumeDraft:
        fallback = self._run_fallback(candidate, fact_cards, jd_profile, gap_analysis, strategy, language)
        fallback_result = self.maybe_use_fallback(fallback, force_fallback=False)
        if fallback_result is not _NO_FALLBACK:
            return fallback_result

        full_output: Optional[ResumeDraftStructuredOutput] = None
        try:
            full_output = self.invoke_structured(
                context=self._build_llm_context(
                    candidate,
                    fact_cards,
                    jd_profile,
                    gap_analysis,
                    strategy,
                    language,
                ),
                response_model=ResumeDraftStructuredOutput,
            )
            draft = self._build_draft_from_output(
                output=full_output,
                fact_cards=fact_cards,
                jd_profile=jd_profile,
                gap_analysis=gap_analysis,
                language=language,
                strategy=strategy,
                fallback=fallback,
                allow_fallback_merge=not self.strict_llm_mode,
            )
            if draft is not None:
                return draft
        except StructuredLLMError as exc:
            first_error = exc
        else:
            first_error = StructuredLLMError("Rewrite agent returned incomplete structured output.", agent_name=self.name)

        try:
            compact_output = self.invoke_structured(
                context=self._build_llm_context(
                    candidate,
                    fact_cards,
                    jd_profile,
                    gap_analysis,
                    strategy,
                    language,
                    compact_mode=True,
                ),
                response_model=ResumeDraftStructuredOutput,
            )
            draft = self._build_draft_from_output(
                output=compact_output,
                fact_cards=fact_cards,
                jd_profile=jd_profile,
                gap_analysis=gap_analysis,
                language=language,
                strategy=strategy,
                fallback=fallback,
                allow_fallback_merge=True,
            )
            if draft is not None:
                return draft
        except StructuredLLMError:
            pass

        if full_output is not None:
            repaired = self._build_draft_from_output(
                output=full_output,
                fact_cards=fact_cards,
                jd_profile=jd_profile,
                gap_analysis=gap_analysis,
                language=language,
                strategy=strategy,
                fallback=fallback,
                allow_fallback_merge=True,
            )
            if repaired is not None:
                return repaired

        return self.fallback_on_error(first_error, fallback)

    def _run_fallback(
        self,
        candidate: CandidateProfile,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        gap_analysis: GapAnalysis,
        strategy: RewriteStrategy,
        language: str,
    ) -> ResumeDraft:
        experiences = self._select_experiences(candidate.work_experiences, strategy, gap_analysis)
        projects = self._select_projects(candidate.projects, strategy, gap_analysis)
        skills = self._select_skills(candidate, gap_analysis, strategy)
        traceability: List[TraceabilityRecord] = []

        experience_section: List[ResumeSectionItem] = []
        for exp_index, experience in enumerate(experiences, start=1):
            bullets = self._rank_bullets(
                experience.bullets,
                gap_analysis,
                strategy.max_bullets_per_experience,
                strategy.audience_hint,
            )
            experience_section.append(
                ResumeSectionItem(
                    heading=experience.title or experience.company or "Experience",
                    subheading=experience.company if experience.title else "",
                    bullets=bullets,
                )
            )
            for bullet_index, bullet in enumerate(bullets, start=1):
                traceability.append(
                    TraceabilityRecord(
                        draft_span="experience_section.{0}.bullets.{1}".format(exp_index, bullet_index),
                        fact_ids=self._fact_ids_for_text(fact_cards, bullet),
                    )
                )

        project_section: List[ResumeSectionItem] = []
        if strategy.include_projects:
            for project_index, project in enumerate(projects, start=1):
                bullets = self._rank_bullets(project.bullets, gap_analysis, 2, strategy.audience_hint)
                project_section.append(
                    ResumeSectionItem(
                        heading=project.name,
                        subheading=project.role,
                        bullets=bullets,
                    )
                )
                for bullet_index, bullet in enumerate(bullets, start=1):
                    traceability.append(
                        TraceabilityRecord(
                            draft_span="project_section.{0}.bullets.{1}".format(project_index, bullet_index),
                            fact_ids=self._fact_ids_for_text(fact_cards, bullet),
                        )
                    )

        education_section = self._build_education(candidate)
        summary = self._build_summary(candidate, jd_profile, gap_analysis, strategy, language)
        headline = self._build_headline(candidate, jd_profile, language)
        markdown = self._render_markdown(
            headline=headline,
            summary=summary,
            skills=skills,
            experience_section=experience_section,
            project_section=project_section,
            education_section=education_section,
            language=language,
            strategy=strategy,
        )

        return ResumeDraft(
            headline=headline,
            summary=summary,
            skills_section=skills,
            experience_section=experience_section,
            project_section=project_section,
            education_section=education_section,
            markdown=markdown,
            traceability=traceability,
        )

    def _from_structured_output(
        self,
        output: ResumeDraftStructuredOutput,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        gap_analysis: GapAnalysis,
        language: str,
        strategy: RewriteStrategy,
        fallback: ResumeDraft,
        allow_fallback_merge: bool = False,
    ) -> ResumeDraft:
        experience_section, experience_traces = self._convert_sections(
            output.experience_section,
            fact_cards,
            gap_analysis,
            strategy.audience_hint,
            "experience_section",
        )
        if allow_fallback_merge and self._should_use_fallback_sections(experience_section, fallback.experience_section):
            experience_section = fallback.experience_section
            experience_traces = [record.model_copy(deep=True) for record in fallback.traceability
                                 if record.draft_span.startswith("experience_section.")]
        project_section, project_traces = self._convert_sections(
            output.project_section,
            fact_cards,
            gap_analysis,
            strategy.audience_hint,
            "project_section",
        )
        if strategy.include_projects and allow_fallback_merge and self._should_use_fallback_sections(project_section, fallback.project_section):
            project_section = fallback.project_section
            project_traces = [record.model_copy(deep=True) for record in fallback.traceability
                              if record.draft_span.startswith("project_section.")]
        education_section = output.education_section
        if allow_fallback_merge and self._should_use_fallback_education(education_section, fallback.education_section):
            education_section = fallback.education_section
        skills_section = self._normalize_skills(output.skills_section, fact_cards, fallback.skills_section)
        headline = self._sanitize_headline(output.headline, fallback.headline, language)
        summary = self._sanitize_summary(output.summary, fallback.summary, language)
        if self._should_use_fallback_summary(summary, fallback.summary, strategy.audience_hint, jd_profile, language):
            summary = fallback.summary
        traceability = experience_traces + project_traces
        markdown = self._render_markdown(
            headline=headline,
            summary=summary,
            skills=skills_section,
            experience_section=experience_section,
            project_section=project_section,
            education_section=education_section,
            language=language,
            strategy=strategy,
        )
        return ResumeDraft(
            headline=headline,
            summary=summary,
            skills_section=skills_section,
            experience_section=experience_section,
            project_section=project_section,
            education_section=education_section,
            markdown=markdown,
            traceability=traceability,
        )

    def _build_draft_from_output(
        self,
        output: ResumeDraftStructuredOutput,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        gap_analysis: GapAnalysis,
        language: str,
        strategy: RewriteStrategy,
        fallback: ResumeDraft,
        allow_fallback_merge: bool,
    ) -> Optional[ResumeDraft]:
        if self._is_structured_output_incomplete(output, fallback, strategy) and not allow_fallback_merge:
            return None
        draft = self._from_structured_output(
            output,
            fact_cards,
            jd_profile,
            gap_analysis,
            language,
            strategy,
            fallback,
            allow_fallback_merge=allow_fallback_merge,
        )
        if not self._has_traceable_content(draft):
            return None
        return draft

    def _build_llm_context(
        self,
        candidate: CandidateProfile,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        gap_analysis: GapAnalysis,
        strategy: RewriteStrategy,
        language: str,
        compact_mode: bool = False,
    ) -> Dict:
        if not compact_mode:
            return {
                "candidate_profile": candidate,
                "fact_cards": fact_cards,
                "jd_profile": jd_profile,
                "gap_analysis": gap_analysis,
                "rewrite_strategy": strategy,
                "language": language,
                "compact_mode": False,
            }
        relevant_fact_cards = self._select_relevant_fact_cards(
            fact_cards,
            gap_analysis.recommended_focus + gap_analysis.strengths + jd_profile.must_have_skills,
            limit=8,
        )
        return {
            "compact_mode": True,
            "language": language,
            "jd_profile": {
                "job_title": jd_profile.job_title,
                "department": jd_profile.department,
                "hiring_track": jd_profile.hiring_track,
                "must_have_skills": jd_profile.must_have_skills[:4],
                "keywords": jd_profile.keywords[:6],
                "domain_signals": jd_profile.domain_signals[:3],
            },
            "gap_analysis": {
                "strengths": gap_analysis.strengths[:6],
                "missing_keywords": gap_analysis.missing_keywords[:4],
                "recommended_focus": gap_analysis.recommended_focus[:6],
            },
            "rewrite_strategy": {
                "audience_hint": strategy.audience_hint,
                "section_priority": strategy.section_priority,
                "keyword_plan": strategy.keyword_plan[:6],
                "max_experiences": strategy.max_experiences,
                "max_bullets_per_experience": strategy.max_bullets_per_experience,
                "max_skills": strategy.max_skills,
                "include_projects": strategy.include_projects,
                "summary_style": strategy.summary_style,
            },
            "candidate_profile": {
                "basics": {
                    "name": candidate.basics.name,
                    "language": candidate.basics.language,
                },
                "summary": candidate.summary,
                "work_experiences": [
                    {
                        "company": experience.company,
                        "title": experience.title,
                        "bullets": experience.bullets[:3],
                        "achievements": experience.achievements[:2],
                        "skills_used": experience.skills_used[:4],
                    }
                    for experience in candidate.work_experiences[: strategy.max_experiences]
                ],
                "projects": [
                    {
                        "name": project.name,
                        "role": project.role,
                        "bullets": project.bullets[:2],
                        "skills_used": project.skills_used[:4],
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
                "skills": {
                    "hard_skills": candidate.skills.hard_skills[:8],
                    "tools": candidate.skills.tools[:6],
                },
            },
            "fact_cards": [
                {
                    "id": card.id,
                    "category": card.category,
                    "text": card.text,
                }
                for card in relevant_fact_cards
            ],
        }

    def _convert_sections(
        self,
        sections: List[TraceableSectionItem],
        fact_cards: List[FactCard],
        gap_analysis: GapAnalysis,
        audience_hint: str,
        section_name: str,
    ) -> Tuple[List[ResumeSectionItem], List[TraceabilityRecord]]:
        fact_lookup = {card.id: card.text for card in fact_cards}
        exact_text_map: Dict[str, List[str]] = {}
        for card in fact_cards:
            exact_text_map.setdefault(normalize_token(self._sanitize_bullet_text(card.text)), []).append(card.id)
        converted_sections: List[ResumeSectionItem] = []
        traceability: List[TraceabilityRecord] = []
        for section in sections:
            cleaned_bullets = []
            ids_by_text: Dict[str, List[str]] = {}
            for bullet in section.bullets:
                cleaned = self._sanitize_bullet_text(bullet.text)
                cleaned = self._restore_fact_grounded_bullet(
                    cleaned,
                    bullet.fact_ids,
                    fact_lookup,
                    gap_analysis,
                    audience_hint,
                )
                if not cleaned:
                    continue
                key = normalize_token(cleaned)
                fact_ids = exact_text_map.get(key) or [fact_id for fact_id in bullet.fact_ids if fact_id in fact_lookup]
                if not fact_ids:
                    # Uncited paraphrases cannot acquire evidence from their old position.
                    continue
                ids_by_text[key] = list(dict.fromkeys(ids_by_text.get(key, []) + fact_ids))
                cleaned_bullets.append(cleaned)
            if cleaned_bullets:
                cleaned_bullets = self._rank_bullets(cleaned_bullets, gap_analysis, None, audience_hint)
                converted_sections.append(
                    ResumeSectionItem(
                        heading=section.heading,
                        subheading=section.subheading,
                        bullets=cleaned_bullets,
                    )
                )
                for bullet_index, text in enumerate(cleaned_bullets, 1):
                    traceability.append(TraceabilityRecord(
                        draft_span=f"{section_name}.{len(converted_sections)}.bullets.{bullet_index}",
                        fact_ids=ids_by_text[normalize_token(text)],
                    ))
        return converted_sections, traceability

    def _has_traceable_content(self, draft: ResumeDraft) -> bool:
        spans = [f"{section_name}.{section_index}.bullets.{bullet_index}"
                 for section_name in ("experience_section", "project_section")
                 for section_index, section in enumerate(getattr(draft, section_name), 1)
                 for bullet_index, _bullet in enumerate(section.bullets, 1)]
        traces = {record.draft_span:record.fact_ids for record in draft.traceability}
        return bool(spans) and all(traces.get(span) for span in spans)

    def _is_structured_output_incomplete(
        self,
        output: ResumeDraftStructuredOutput,
        fallback: ResumeDraft,
        strategy: RewriteStrategy,
    ) -> bool:
        if fallback.experience_section and not output.experience_section:
            return True
        if len(output.experience_section) < len(fallback.experience_section):
            return True
        fallback_experience_bullets = sum(len(section.bullets) for section in fallback.experience_section)
        output_experience_bullets = sum(len(section.bullets) for section in output.experience_section)
        if fallback_experience_bullets >= 3 and output_experience_bullets < max(1, int(fallback_experience_bullets * 0.7)):
            return True
        if strategy.include_projects and fallback.project_section and len(output.project_section) < len(fallback.project_section):
            return True
        if fallback.education_section and len(output.education_section) < len(fallback.education_section):
            return True
        return False

    def _should_use_fallback_sections(
        self,
        candidate_sections: List[ResumeSectionItem],
        fallback_sections: List[ResumeSectionItem],
    ) -> bool:
        if not candidate_sections:
            return True
        if not fallback_sections:
            return False
        candidate_count = len(candidate_sections)
        fallback_count = len(fallback_sections)
        candidate_bullets = sum(len(section.bullets) for section in candidate_sections)
        fallback_bullets = sum(len(section.bullets) for section in fallback_sections)

        if candidate_count < fallback_count and fallback_count > 1:
            return True
        if fallback_bullets >= 3 and candidate_bullets < max(1, int(fallback_bullets * 0.7)):
            return True
        if any(not section.bullets for section in candidate_sections[: max(1, min(candidate_count, fallback_count))]):
            return True
        return False

    def _should_use_fallback_education(self, candidate_lines: List[str], fallback_lines: List[str]) -> bool:
        if not candidate_lines and fallback_lines:
            return True
        if fallback_lines and len(candidate_lines) < len(fallback_lines):
            return True
        return False

    def _select_experiences(
        self,
        experiences: List[WorkExperience],
        strategy: RewriteStrategy,
        gap_analysis: GapAnalysis,
    ) -> List[WorkExperience]:
        scored = []
        for index, experience in enumerate(experiences):
            haystack = normalize_token(" ".join([experience.title or "", experience.company or ""] + experience.bullets))
            score = sum(2 for keyword in gap_analysis.recommended_focus if normalize_token(keyword) in haystack)
            score += sum(1 for keyword in gap_analysis.strengths if normalize_token(keyword) in haystack)
            score += min(
                4,
                sum(
                    self._bullet_quality_score(bullet, gap_analysis, strategy.audience_hint)
                    for bullet in experience.bullets
                ),
            )
            score += min(2, len(experience.achievements))
            if any(any(char.isdigit() for char in bullet) for bullet in experience.bullets + experience.achievements):
                score += 2
            if strategy.audience_hint == "experienced" and experience.achievements:
                score += 2
            scored.append((score, -index, experience))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[: strategy.max_experiences]]

    def _select_projects(
        self,
        projects: List[ProjectExperience],
        strategy: RewriteStrategy,
        gap_analysis: GapAnalysis,
    ) -> List[ProjectExperience]:
        if not strategy.include_projects:
            return []
        scored = []
        for index, project in enumerate(projects):
            haystack = normalize_token(" ".join([project.name] + project.bullets))
            score = sum(2 for keyword in gap_analysis.recommended_focus if normalize_token(keyword) in haystack)
            score += min(
                4,
                sum(
                    self._bullet_quality_score(bullet, gap_analysis, strategy.audience_hint)
                    for bullet in project.bullets
                ),
            )
            if strategy.audience_hint in {"campus", "intern"}:
                score += 2
            scored.append((score, -index, project))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:2]]

    def _rank_bullets(
        self,
        bullets: List[str],
        gap_analysis: GapAnalysis,
        max_items: Optional[int],
        audience_hint: str = "general",
    ) -> List[str]:
        scored = []
        for index, bullet in enumerate(unique_preserve_order(bullets)):
            score = self._bullet_quality_score(bullet, gap_analysis, audience_hint)
            scored.append((score, -index, bullet))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        ranked = [item[2] for item in scored]
        if max_items is None:
            return ranked
        return ranked[:max_items]

    def _select_skills(
        self,
        candidate: CandidateProfile,
        gap_analysis: GapAnalysis,
        strategy: RewriteStrategy,
    ) -> List[str]:
        prioritized = gap_analysis.strengths + candidate.skills.hard_skills + candidate.skills.tools
        return unique_preserve_order(prioritized)[: strategy.max_skills]

    def _select_relevant_fact_cards(
        self,
        fact_cards: List[FactCard],
        priorities: List[str],
        limit: int,
    ) -> List[FactCard]:
        normalized_priorities = [normalize_token(item) for item in priorities if normalize_token(item)]
        scored = []
        for index, card in enumerate(fact_cards):
            text = normalize_token(card.text)
            score = sum(max(1, len(normalized_priorities) - priority_index) for priority_index, item in enumerate(normalized_priorities) if item in text)
            scored.append((score, -index, card))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        selected = [item[2] for item in scored if item[0] > 0]
        if len(selected) < limit:
            seen = {card.id for card in selected}
            for card in fact_cards:
                if card.id in seen:
                    continue
                selected.append(card)
                if len(selected) >= limit:
                    break
        return selected[:limit]

    def _build_education(self, candidate: CandidateProfile) -> List[str]:
        lines = []
        for education in candidate.education:
            parts = [education.school, education.degree or "", education.field_of_study or ""]
            line = " | ".join(part for part in parts if part)
            if line:
                lines.append(line)
        return lines

    def _bullet_quality_score(self, bullet: str, gap_analysis: GapAnalysis, audience_hint: str) -> int:
        normalized = normalize_token(bullet)
        score = sum(2 for keyword in gap_analysis.recommended_focus if normalize_token(keyword) in normalized)
        score += sum(1 for keyword in gap_analysis.strengths if normalize_token(keyword) in normalized)
        if any(char.isdigit() for char in bullet):
            score += 3
        if self._has_action_signal(bullet, normalized):
            score += 2
        if self._has_result_signal(bullet, normalized):
            score += 2
        if self._has_concrete_context(bullet, normalized):
            score += 1
        if 14 <= len(bullet) <= 90:
            score += 1
        if self._looks_abstract_or_ai_like(bullet, normalized):
            score -= 4
        if self._starts_with_weak_action(normalized) and not self._has_result_signal(bullet, normalized):
            score -= 2
        if audience_hint in {"campus", "intern"} and any(token in bullet for token in self.CAMPUS_PROJECT_HINTS):
            score += 1
        if audience_hint == "experienced" and any(token.lower() in normalized for token in self.EXPERIENCED_SCOPE_HINTS):
            score += 1
        return score

    def _build_summary(
        self,
        candidate: CandidateProfile,
        jd_profile: JDProfile,
        gap_analysis: GapAnalysis,
        strategy: RewriteStrategy,
        language: str,
    ) -> str:
        if candidate.summary and self._is_candidate_summary_usable(candidate.summary, language):
            return self._refine_summary(candidate.summary, jd_profile, gap_analysis, strategy.summary_style, language=language)

        focus_items = self._summary_skills(candidate, gap_analysis)
        focus = "、".join(focus_items[:4]) if language == "zh" else ", ".join(focus_items[:4])
        education = self._build_education(candidate)
        project_signal = self._shorten_signal(self._best_project_signal(candidate))
        experience_signal = self._shorten_signal(self._best_experience_signal(candidate))
        target_role = jd_profile.job_title or "目标岗位"
        hiring_track = jd_profile.hiring_track
        summary_style = strategy.summary_style
        if language == "zh":
            if hiring_track == "campus":
                if education and project_signal and focus:
                    return "{0}背景，聚焦{1}方向，具备{2}等基础能力，曾在项目或实践中{3}。".format(
                        education[0],
                        target_role,
                        focus,
                        project_signal,
                    )
                if education and focus:
                    return "{0}背景，聚焦{1}方向，具备{2}等基础能力，相关经历主要来自项目、课程或实习实践。".format(
                        education[0],
                        target_role,
                        focus,
                    )
                return "聚焦{0}方向，已通过教育、项目或实践经历形成与岗位相关的基础能力。".format(target_role)
            if hiring_track == "intern":
                if project_signal and focus:
                    return "聚焦{0}方向，具备{1}等基础能力，曾在项目或实习中{2}。".format(
                        target_role,
                        focus,
                        project_signal,
                    )
                return "聚焦{0}方向，具备岗位相关的基础能力和项目实践，重点体现在执行力、分析能力和快速学习上。".format(target_role)
            if experience_signal and focus:
                return "聚焦{0}方向，具备{1}等相关实践，曾{2}。".format(
                    target_role,
                    focus,
                    experience_signal,
                )
            if focus:
                if summary_style == "impact_and_scope":
                    return "聚焦{0}方向，相关实践覆盖{1}等重点能力。".format(
                        target_role,
                        focus,
                    )
                return "聚焦{0}方向，重点能力包括{1}。".format(
                    target_role,
                    focus,
                )
            return "聚焦{0}方向，具备与岗位相关的真实实践，可从过往经历中说明具体动作、场景与结果。".format(target_role)
        if focus:
            return "Experience aligned with {0}, with verified strengths in {1} and evidence from prior work or projects.".format(
                target_role,
                focus,
            )
        return "Verified experience aligned with the target role, emphasizing relevant skills, execution, and measurable impact."

    def _build_headline(self, candidate: CandidateProfile, jd_profile: JDProfile, language: str) -> str:
        name = candidate.basics.name or "Candidate"
        if language == "zh":
            if jd_profile.hiring_track == "campus":
                return "{0} | 面向 {1} 的校招定制简历".format(name, jd_profile.job_title or "目标岗位")
            if jd_profile.hiring_track == "intern":
                return "{0} | 面向 {1} 的实习申请简历".format(name, jd_profile.job_title or "目标岗位")
            return "{0} | 面向 {1} 的定制简历".format(name, jd_profile.job_title or "目标岗位")
        return "{0} | Tailored Resume for {1}".format(name, jd_profile.job_title or "Target Role")

    def _render_markdown(
        self,
        headline: str,
        summary: str,
        skills: List[str],
        experience_section: List[ResumeSectionItem],
        project_section: List[ResumeSectionItem],
        education_section: List[str],
        language: str,
        strategy: RewriteStrategy,
    ) -> str:
        lines = ["# {0}".format(headline), ""]
        summary_label = "简介" if language == "zh" else "Summary"
        skills_label = "核心技能" if language == "zh" else "Core Skills"
        experience_label = "工作经历" if language == "zh" else "Experience"
        project_label = "项目经历" if language == "zh" else "Projects"
        education_label = "教育背景" if language == "zh" else "Education"
        section_blocks = {
            "summary": ["## {0}".format(summary_label), summary, ""] if summary else [],
            "skills": ["## {0}".format(skills_label)] + ["- {0}".format(skill) for skill in skills] + [""] if skills else [],
            "experience": self._render_section_items(experience_label, experience_section),
            "projects": self._render_section_items(project_label, project_section),
            "education": ["## {0}".format(education_label)] + ["- {0}".format(line) for line in education_section] + [""] if education_section else [],
        }
        ordered_keys = []
        for section_name in strategy.section_priority:
            if section_name in section_blocks and section_name not in ordered_keys:
                ordered_keys.append(section_name)
        for section_name in ["summary", "skills", "experience", "projects", "education"]:
            if section_name not in ordered_keys:
                ordered_keys.append(section_name)

        for section_name in ordered_keys:
            block = section_blocks.get(section_name, [])
            if block:
                lines.extend(block)
        return "\n".join(lines).strip()

    def _normalize_skills(self, skills: List[str], fact_cards: List[FactCard], fallback: List[str]) -> List[str]:
        if not skills:
            return fallback
        known_skills = {card.text for card in fact_cards if card.category == "skill"}
        normalized = [skill for skill in skills if skill in known_skills]
        return normalized or fallback

    def _sanitize_headline(self, headline: str, fallback: str, language: str) -> str:
        value = (headline or "").strip()
        if not value:
            return fallback
        expected_name = self._headline_name_from_fallback(fallback)
        expected_role = self._headline_role_from_fallback(fallback, language)
        if language == "zh":
            safe_markers = ("面向", "申请", "定制简历")
            if expected_name and expected_name not in value:
                return fallback
            if expected_role and expected_role not in value:
                return fallback
            if any(marker in value for marker in safe_markers) and "|" in value:
                return value
            return fallback
        safe_markers = ("for ", "tailored", "application")
        if expected_name and expected_name not in value:
            return fallback
        if expected_role and expected_role.lower() not in value.lower():
            return fallback
        if any(marker in value.lower() for marker in safe_markers):
            return value
        return fallback

    def _headline_name_from_fallback(self, fallback: str) -> str:
        if "|" not in fallback:
            return ""
        candidate = fallback.split("|", 1)[0].strip()
        if candidate in {"Candidate", "候选人"}:
            return ""
        return candidate

    def _headline_role_from_fallback(self, fallback: str, language: str) -> str:
        if language == "zh":
            matched = re.search(r"面向\s*(.+?)\s*的", fallback)
            if matched:
                return matched.group(1).strip()
        matched = re.search(r"for\s+(.+)$", fallback, flags=re.IGNORECASE)
        if matched:
            return matched.group(1).strip()
        return ""

    def _sanitize_summary(self, summary: str, fallback: str, language: str) -> str:
        value = (summary or "").strip()
        if len(value) < 24:
            return fallback
        meta_markers = ["围绕", "已按", "当前以", "重排", "reordered", "tailored resume", "this resume"]
        vague_markers = [
            "优秀",
            "出色",
            "资深",
            "highly motivated",
            "excellent",
            "seasoned",
            "能力基础",
            "结果交付",
            "业务推进",
            "进一步展开",
        ]
        lowered = value.lower()
        if any(marker in value or marker in lowered for marker in meta_markers):
            return fallback
        if any(marker in value or marker in lowered for marker in vague_markers):
            return fallback
        if language == "zh" and len(value) < 28:
            return fallback
        return value

    def _should_use_fallback_summary(
        self,
        summary: str,
        fallback: str,
        audience_hint: str,
        jd_profile: JDProfile,
        language: str,
    ) -> bool:
        value = (summary or "").strip()
        baseline = (fallback or "").strip()
        if not value:
            return True
        if not baseline or value == baseline:
            return False
        value_score = self._summary_specificity_score(value, audience_hint, jd_profile, language)
        fallback_score = self._summary_specificity_score(baseline, audience_hint, jd_profile, language)
        if self._summary_is_list_like(value, language) and not self._summary_is_list_like(baseline, language):
            return True
        if fallback_score >= value_score + 2:
            return True
        if self._summary_has_role_context(baseline, jd_profile) and not self._summary_has_role_context(value, jd_profile):
            return True
        if self._summary_has_result_or_action_signal(baseline) and not self._summary_has_result_or_action_signal(value):
            return True
        return False

    def _fact_ids_for_text(self, fact_cards: List[FactCard], text: str) -> List[str]:
        return [card.id for card in fact_cards if card.text == text]

    def _render_section_items(self, label: str, items: List[ResumeSectionItem]) -> List[str]:
        if not items:
            return []
        lines = ["## {0}".format(label)]
        for item in items:
            lines.append("### {0}".format(item.heading))
            if item.subheading:
                lines.append(item.subheading)
            lines.extend("- {0}".format(bullet) for bullet in item.bullets)
            lines.append("")
        return lines

    def _sanitize_bullet_text(self, bullet: str) -> str:
        value = (bullet or "").strip()
        if not value:
            return ""

        value = re.sub(
            r"\s*[（(][^）)]*(?:JD|岗位要求|任职要求|加分项|对应要求|岗位需求|匹配 JD|符合 JD)[^）)]*[）)]\s*",
            "",
            value,
            flags=re.IGNORECASE,
        ).strip()

        separator_match = re.match(
            r"^(?P<core>.+?)\s*(?:[-—–:：;；,，])\s*(?P<meta>.+)$",
            value,
        )
        if separator_match and self._looks_like_jd_tail(separator_match.group("meta")):
            value = separator_match.group("core").strip()

        clause_split = re.split(r"(?:(?:，|,|；|;)\s*)", value)
        if len(clause_split) > 1 and self._looks_like_jd_tail(clause_split[-1]):
            value = "，".join(part.strip() for part in clause_split[:-1] if part.strip()).strip()

        return value.strip(" -—–:：;；,，")

    def _looks_like_jd_tail(self, text: str) -> bool:
        normalized = normalize_token(text)
        if not normalized:
            return False
        if any(marker in normalized for marker in self.JD_META_MARKERS):
            return True
        if "对应" in text and ("要求" in text or "岗位" in text):
            return True
        if "匹配" in text and ("岗位" in text or "jd" in normalized):
            return True
        if "符合" in text and ("岗位" in text or "jd" in normalized):
            return True
        return False

    def _restore_fact_grounded_bullet(
        self,
        bullet: str,
        fact_ids: List[str],
        fact_lookup: Dict[str, str],
        gap_analysis: GapAnalysis,
        audience_hint: str,
    ) -> str:
        value = (bullet or "").strip()
        if not value or not fact_ids:
            return value
        source_candidates = [fact_lookup[fact_id] for fact_id in fact_ids if fact_id in fact_lookup]
        if not source_candidates:
            return value
        normalized = normalize_token(value)
        if not self._looks_abstract_or_ai_like(value, normalized):
            return value
        ranked_sources = sorted(
            source_candidates,
            key=lambda item: self._bullet_quality_score(item, gap_analysis, audience_hint),
            reverse=True,
        )
        source_text = self._sanitize_bullet_text(ranked_sources[0])
        if not source_text:
            return value
        source_score = self._bullet_quality_score(source_text, gap_analysis, audience_hint)
        candidate_score = self._bullet_quality_score(value, gap_analysis, audience_hint)
        source_specificity = self._bullet_specificity_score(source_text, audience_hint)
        candidate_specificity = self._bullet_specificity_score(value, audience_hint)
        if source_specificity >= candidate_specificity + 1 and source_score >= candidate_score:
            return source_text
        if source_score >= candidate_score + 2:
            return source_text
        return value

    def _has_action_signal(self, bullet: str, normalized: str) -> bool:
        return any(token in bullet for token in self.ACTION_HINTS) or any(token in normalized for token in self.ACTION_HINTS)

    def _has_result_signal(self, bullet: str, normalized: str) -> bool:
        return any(token in bullet for token in self.RESULT_HINTS) or any(token in normalized for token in self.RESULT_HINTS)

    def _has_concrete_context(self, bullet: str, normalized: str) -> bool:
        if any(symbol in bullet for symbol in ("SQL", "A/B", "Tableau", "Power BI", "Python", "Excel")):
            return True
        context_terms = ("用户", "漏斗", "实验", "看板", "渠道", "投放", "增长", "转化", "项目", "指标", "复盘", "分析")
        return any(term in bullet or term in normalized for term in context_terms)

    def _starts_with_weak_action(self, normalized: str) -> bool:
        return any(normalized.startswith(token) for token in self.WEAK_ACTION_HINTS)

    def _looks_abstract_or_ai_like(self, bullet: str, normalized: str) -> bool:
        if any(marker in bullet or marker in normalized for marker in self.GENERIC_BULLET_MARKERS):
            return True
        if any(marker in bullet or marker in normalized for marker in self.ABSTRACT_STYLE_MARKERS):
            if not self._has_concrete_context(bullet, normalized) or not self._has_action_signal(bullet, normalized):
                return True
        if "能力" in bullet and not any(char.isdigit() for char in bullet):
            return True
        if self._starts_with_weak_action(normalized) and not self._has_result_signal(bullet, normalized):
            return True
        if len(normalized) < 10:
            return True
        return False

    def _summary_has_result_or_action_signal(self, summary: str) -> bool:
        normalized = normalize_token(summary)
        return (
            self._has_action_signal(summary, normalized)
            or self._has_result_signal(summary, normalized)
            or any(char.isdigit() for char in summary)
        )

    def _summary_has_role_context(self, summary: str, jd_profile: JDProfile) -> bool:
        role = (jd_profile.job_title or "").strip()
        if role and role in summary:
            return True
        track_markers = {
            "campus": ("校招", "应届", "项目", "课程", "实习"),
            "intern": ("实习", "项目", "上手", "执行"),
            "experienced": ("负责", "主导", "业务", "跨团队", "增长", "运营", "产品"),
        }
        return any(marker in summary for marker in track_markers.get(jd_profile.hiring_track, ()))

    def _summary_is_list_like(self, summary: str, language: str) -> bool:
        value = (summary or "").strip()
        if not value:
            return False
        if language == "zh":
            delimiter_count = value.count("、") + value.count("，")
        else:
            delimiter_count = value.count(",")
        normalized = normalize_token(value)
        return delimiter_count >= 2 and not self._summary_has_result_or_action_signal(value) and not self._has_concrete_context(value, normalized)

    def _summary_specificity_score(
        self,
        summary: str,
        audience_hint: str,
        jd_profile: JDProfile,
        language: str,
    ) -> int:
        value = (summary or "").strip()
        normalized = normalize_token(value)
        score = 0
        if self._summary_has_role_context(value, jd_profile):
            score += 2
        if self._summary_has_result_or_action_signal(value):
            score += 2
        if self._has_concrete_context(value, normalized):
            score += 1
        if not self._summary_is_list_like(value, language):
            score += 1
        if audience_hint in {"campus", "intern"} and any(token in value for token in self.CAMPUS_PROJECT_HINTS):
            score += 1
        if audience_hint == "experienced" and any(token.lower() in normalized for token in self.EXPERIENCED_SCOPE_HINTS):
            score += 1
        if any(marker in value or marker in normalized for marker in self.GENERIC_BULLET_MARKERS):
            score -= 2
        return score

    def _bullet_specificity_score(self, bullet: str, audience_hint: str) -> int:
        normalized = normalize_token(bullet)
        score = 0
        if any(char.isdigit() for char in bullet):
            score += 2
        if self._has_action_signal(bullet, normalized):
            score += 2
        if self._has_result_signal(bullet, normalized):
            score += 2
        if self._has_concrete_context(bullet, normalized):
            score += 1
        if audience_hint == "experienced" and any(token.lower() in normalized for token in self.EXPERIENCED_SCOPE_HINTS):
            score += 1
        if audience_hint in {"campus", "intern"} and any(token in bullet for token in self.CAMPUS_PROJECT_HINTS):
            score += 1
        if self._looks_abstract_or_ai_like(bullet, normalized):
            score -= 3
        return score

    def _summary_skills(self, candidate: CandidateProfile, gap_analysis: GapAnalysis) -> List[str]:
        return unique_preserve_order(gap_analysis.strengths + candidate.skills.hard_skills + candidate.skills.tools)

    def _best_project_signal(self, candidate: CandidateProfile) -> str:
        candidates = []
        empty_gap = GapAnalysis()
        for project in candidate.projects:
            for bullet in project.bullets:
                candidates.append((self._bullet_quality_score(bullet, empty_gap, "campus"), bullet))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1] if candidates else ""

    def _best_experience_signal(self, candidate: CandidateProfile) -> str:
        candidates = []
        empty_gap = GapAnalysis()
        for experience in candidate.work_experiences:
            for bullet in experience.achievements + experience.bullets:
                if bullet:
                    candidates.append((self._bullet_quality_score(bullet, empty_gap, "experienced"), bullet))
        candidates.sort(key=lambda item: item[0], reverse=True)
        return candidates[0][1] if candidates else ""

    def _shorten_signal(self, signal: str) -> str:
        value = (signal or "").strip().strip("。.;；")
        if len(value) <= 34:
            return value
        clauses = re.split(r"[，,。.;；]", value)
        for clause in clauses:
            cleaned = clause.strip()
            if 8 <= len(cleaned) <= 30:
                return cleaned
        return value[:30].rstrip("，,。.;；")

    def _is_candidate_summary_usable(self, summary: str, language: str) -> bool:
        normalized = normalize_token(summary)
        if not normalized:
            return False
        meta_markers = {"围绕", "已按", "当前以", "简历", "resume", "tailored", "reordered"}
        if any(marker in summary or marker in normalized for marker in meta_markers):
            return False
        if language == "zh":
            return len(summary.strip()) >= 24
        return len(summary.strip()) >= 32

    def _refine_summary(
        self,
        summary: str,
        jd_profile: JDProfile,
        gap_analysis: GapAnalysis,
        strategy_style: str,
        language: str,
    ) -> str:
        value = (summary or "").strip()
        if language != "zh":
            return value
        role = jd_profile.job_title or "目标岗位"
        if jd_profile.hiring_track == "campus":
            return "{0}，并在教育、项目或实习经历中形成了与{1}相关的基础实践。".format(
                self._shorten_signal(value),
                role,
            )
        if jd_profile.hiring_track == "intern":
            return "{0}，重点体现在项目实践、执行力和快速学习能力上。".format(
                self._shorten_signal(value),
            )
        focus_items = self._summary_skills_from_gap(gap_analysis)
        if focus_items:
            if strategy_style == "impact_and_scope":
                return "{0}，相关实践覆盖{1}等方向。".format(
                    self._shorten_signal(value),
                    "、".join(focus_items[:3]),
                )
            return "{0}，重点经验包括{1}。".format(
                self._shorten_signal(value),
                "、".join(focus_items[:3]),
            )
        return value

    def _summary_skills_from_gap(self, gap_analysis: GapAnalysis) -> List[str]:
        return unique_preserve_order(gap_analysis.strengths + gap_analysis.recommended_focus)
