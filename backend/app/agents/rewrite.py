import re
from typing import List

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

        try:
            structured_output = self.invoke_structured(
                context={
                    "candidate_profile": candidate,
                    "fact_cards": fact_cards,
                    "jd_profile": jd_profile,
                    "gap_analysis": gap_analysis,
                    "rewrite_strategy": strategy,
                    "language": language,
                },
                response_model=ResumeDraftStructuredOutput,
            )
            if self.strict_llm_mode and self._is_structured_output_incomplete(structured_output, fallback, strategy):
                raise StructuredLLMError("Rewrite agent returned incomplete structured output.")
            draft = self._from_structured_output(structured_output, fact_cards, language, strategy, fallback)
            if not self._has_traceable_content(draft):
                raise StructuredLLMError("Rewrite agent returned insufficient traceable content.")
            return draft
        except StructuredLLMError as exc:
            return self.fallback_on_error(exc, fallback)

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
            bullets = self._rank_bullets(experience.bullets, gap_analysis, strategy.max_bullets_per_experience)
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
                bullets = self._rank_bullets(project.bullets, gap_analysis, 2)
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
        language: str,
        strategy: RewriteStrategy,
        fallback: ResumeDraft,
    ) -> ResumeDraft:
        fact_id_set = {card.id for card in fact_cards}
        used_fallback_sections = False
        experience_section = self._convert_sections(output.experience_section)
        if not self.strict_llm_mode and self._should_use_fallback_sections(experience_section, fallback.experience_section):
            experience_section = fallback.experience_section
            used_fallback_sections = True
        project_section = self._convert_sections(output.project_section)
        if strategy.include_projects and not self.strict_llm_mode and self._should_use_fallback_sections(project_section, fallback.project_section):
            project_section = fallback.project_section
            used_fallback_sections = True
        education_section = output.education_section
        if not self.strict_llm_mode and self._should_use_fallback_education(education_section, fallback.education_section):
            education_section = fallback.education_section
            used_fallback_sections = True
        skills_section = self._normalize_skills(output.skills_section, fact_cards, fallback.skills_section)
        headline = self._sanitize_headline(output.headline, fallback.headline, language)
        summary = self._sanitize_summary(output.summary, fallback.summary, language)
        traceability = self._build_traceability(output.experience_section, output.project_section, fact_id_set, fact_cards)
        if used_fallback_sections or not traceability:
            traceability = fallback.traceability
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

    def _convert_sections(self, sections: List[TraceableSectionItem]) -> List[ResumeSectionItem]:
        return [
            ResumeSectionItem(
                heading=section.heading,
                subheading=section.subheading,
                bullets=[bullet.text for bullet in section.bullets if bullet.text.strip()],
            )
            for section in sections
        ]

    def _build_traceability(
        self,
        experience_sections: List[TraceableSectionItem],
        project_sections: List[TraceableSectionItem],
        fact_id_set: set,
        fact_cards: List[FactCard],
    ) -> List[TraceabilityRecord]:
        traceability: List[TraceabilityRecord] = []
        exact_text_map = {}
        for card in fact_cards:
            exact_text_map.setdefault(card.text, []).append(card.id)

        for section_index, section in enumerate(experience_sections, start=1):
            for bullet_index, bullet in enumerate(section.bullets, start=1):
                fact_ids = [fact_id for fact_id in bullet.fact_ids if fact_id in fact_id_set]
                if not fact_ids and bullet.text in exact_text_map:
                    fact_ids = exact_text_map[bullet.text]
                traceability.append(
                    TraceabilityRecord(
                        draft_span="experience_section.{0}.bullets.{1}".format(section_index, bullet_index),
                        fact_ids=fact_ids,
                    )
                )
        for section_index, section in enumerate(project_sections, start=1):
            for bullet_index, bullet in enumerate(section.bullets, start=1):
                fact_ids = [fact_id for fact_id in bullet.fact_ids if fact_id in fact_id_set]
                if not fact_ids and bullet.text in exact_text_map:
                    fact_ids = exact_text_map[bullet.text]
                traceability.append(
                    TraceabilityRecord(
                        draft_span="project_section.{0}.bullets.{1}".format(section_index, bullet_index),
                        fact_ids=fact_ids,
                    )
                )
        return traceability

    def _has_traceable_content(self, draft: ResumeDraft) -> bool:
        bullets = sum(len(section.bullets) for section in draft.experience_section + draft.project_section)
        if bullets == 0:
            return False
        traced = sum(1 for record in draft.traceability if record.fact_ids)
        return traced >= max(1, int(bullets * 0.8))

    def _is_structured_output_incomplete(
        self,
        output: ResumeDraftStructuredOutput,
        fallback: ResumeDraft,
        strategy: RewriteStrategy,
    ) -> bool:
        if not output.experience_section:
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
        for experience in experiences:
            haystack = normalize_token(" ".join([experience.title or "", experience.company or ""] + experience.bullets))
            score = sum(1 for keyword in gap_analysis.strengths if normalize_token(keyword) in haystack)
            scored.append((score, experience))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[: strategy.max_experiences]]

    def _select_projects(
        self,
        projects: List[ProjectExperience],
        strategy: RewriteStrategy,
        gap_analysis: GapAnalysis,
    ) -> List[ProjectExperience]:
        if not strategy.include_projects:
            return []
        scored = []
        for project in projects:
            haystack = normalize_token(" ".join([project.name] + project.bullets))
            score = sum(1 for keyword in gap_analysis.recommended_focus if normalize_token(keyword) in haystack)
            scored.append((score, project))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:2]]

    def _rank_bullets(self, bullets: List[str], gap_analysis: GapAnalysis, max_items: int) -> List[str]:
        scored = []
        for index, bullet in enumerate(unique_preserve_order(bullets)):
            normalized = normalize_token(bullet)
            score = sum(1 for keyword in gap_analysis.recommended_focus if normalize_token(keyword) in normalized)
            if any(char.isdigit() for char in bullet):
                score += 3
            if any(token in bullet for token in self.ACTION_HINTS) or any(token in normalized for token in self.ACTION_HINTS):
                score += 2
            if any(token in bullet for token in self.RESULT_HINTS) or any(token in normalized for token in self.RESULT_HINTS):
                score += 2
            if 14 <= len(bullet) <= 80:
                score += 1
            scored.append((score, -index, bullet))
        scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return [item[2] for item in scored[:max_items]]

    def _select_skills(
        self,
        candidate: CandidateProfile,
        gap_analysis: GapAnalysis,
        strategy: RewriteStrategy,
    ) -> List[str]:
        prioritized = gap_analysis.strengths + candidate.skills.hard_skills + candidate.skills.tools
        return unique_preserve_order(prioritized)[: strategy.max_skills]

    def _build_education(self, candidate: CandidateProfile) -> List[str]:
        lines = []
        for education in candidate.education:
            parts = [education.school, education.degree or "", education.field_of_study or ""]
            line = " | ".join(part for part in parts if part)
            if line:
                lines.append(line)
        return lines

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
                    return "{0}背景，具备{1}等基础能力，曾通过{2}积累与{3}相关的项目实践。".format(
                        education[0],
                        focus,
                        project_signal,
                        target_role,
                    )
                if education and focus:
                    return "{0}背景，具备{1}等与{2}相关的基础能力，适合在校招场景中进一步展示项目与学习潜力。".format(
                        education[0],
                        focus,
                        target_role,
                    )
                return "具备与{0}相关的基础能力和学习潜力，适合从教育、项目与实践经历中展开证明。".format(target_role)
            if hiring_track == "intern":
                if project_signal and focus:
                    return "具备{0}等基础能力，并通过{1}积累了与{2}相关的项目实践，能够较快进入实习岗位工作节奏。".format(
                        focus,
                        project_signal,
                        target_role,
                    )
                return "具备与{0}相关的基础能力、项目实践和快速学习潜力，适合实习岗位场景。".format(target_role)
            if experience_signal and focus:
                if summary_style == "impact_and_scope":
                    return "具备{0}等与{1}高度相关的实践经验，曾{2}，能够支撑业务推进、跨团队协作与结果交付。".format(
                        focus,
                        target_role,
                        experience_signal,
                    )
                return "具备{0}等与{1}高度相关的实践经验，曾{2}，能够支撑相关岗位所需的业务推进与结果交付。".format(
                    focus,
                    target_role,
                    experience_signal,
                )
            if focus:
                if summary_style == "impact_and_scope":
                    return "具备与{0}相关的技能和业务实践基础，核心能力包括{1}，适合继续展开职责范围与结果证明。".format(
                        target_role,
                        focus,
                    )
                return "具备与{0}相关的技能和实践基础，重点能力包括{1}。".format(
                    target_role,
                    focus,
                )
            return "具备与{0}相关的实践基础，能够从真实经历中展开说明业务理解、执行过程与结果。".format(target_role)
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
        if language == "zh":
            safe_markers = ("面向", "申请", "定制简历")
            if any(marker in value for marker in safe_markers):
                return value
            return fallback
        safe_markers = ("for ", "tailored", "application")
        if any(marker in value.lower() for marker in safe_markers):
            return value
        return fallback

    def _sanitize_summary(self, summary: str, fallback: str, language: str) -> str:
        value = (summary or "").strip()
        if len(value) < 24:
            return fallback
        meta_markers = ["围绕", "已按", "当前以", "重排", "reordered", "tailored resume", "this resume"]
        vague_markers = ["优秀", "出色", "资深", "highly motivated", "excellent", "seasoned"]
        lowered = value.lower()
        if any(marker in value or marker in lowered for marker in meta_markers):
            return fallback
        if any(marker in value or marker in lowered for marker in vague_markers):
            return fallback
        if language == "zh" and len(value) < 28:
            return fallback
        return value

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

    def _summary_skills(self, candidate: CandidateProfile, gap_analysis: GapAnalysis) -> List[str]:
        return unique_preserve_order(gap_analysis.strengths + candidate.skills.hard_skills + candidate.skills.tools)

    def _best_project_signal(self, candidate: CandidateProfile) -> str:
        for project in candidate.projects:
            if project.bullets:
                return project.bullets[0]
        return ""

    def _best_experience_signal(self, candidate: CandidateProfile) -> str:
        for experience in candidate.work_experiences:
            for bullet in experience.achievements + experience.bullets:
                if bullet:
                    return bullet
        return ""

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
            return "{0} 与 {1} 方向相关，适合从教育、项目或实习经历中进一步展开能力证明。".format(
                self._shorten_signal(value),
                role,
            )
        if jd_profile.hiring_track == "intern":
            return "{0}，适合从项目实践和快速学习能力切入 {1} 实习场景。".format(
                self._shorten_signal(value),
                role,
            )
        focus_items = self._summary_skills_from_gap(gap_analysis)
        if focus_items:
            if strategy_style == "impact_and_scope":
                return "{0}，并具备{1}等与{2}相关的能力基础，能够进一步展开职责范围与业务结果。".format(
                    self._shorten_signal(value),
                    "、".join(focus_items[:3]),
                    role,
                )
            return "{0}，并具备{1}等与{2}相关的能力基础。".format(
                self._shorten_signal(value),
                "、".join(focus_items[:3]),
                role,
            )
        return value

    def _summary_skills_from_gap(self, gap_analysis: GapAnalysis) -> List[str]:
        return unique_preserve_order(gap_analysis.strengths + gap_analysis.recommended_focus)
