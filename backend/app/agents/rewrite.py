from typing import List

from backend.app.agents.base import BaseAgent
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
        if not self.llm_service.is_available:
            return fallback

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
            draft = self._from_structured_output(structured_output, fact_cards, language, strategy, fallback)
            if not self._has_traceable_content(draft):
                return fallback
            return draft
        except StructuredLLMError:
            return fallback

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
        summary = self._build_summary(candidate, jd_profile, gap_analysis, language)
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
        if not experience_section:
            experience_section = fallback.experience_section
            used_fallback_sections = True
        project_section = self._convert_sections(output.project_section)
        if strategy.include_projects and not project_section:
            project_section = fallback.project_section
            used_fallback_sections = True
        education_section = output.education_section or fallback.education_section
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
        for bullet in bullets:
            normalized = normalize_token(bullet)
            score = sum(1 for keyword in gap_analysis.recommended_focus if normalize_token(keyword) in normalized)
            if any(char.isdigit() for char in bullet):
                score += 1
            scored.append((score, bullet))
        scored.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored[:max_items]]

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
        language: str,
    ) -> str:
        focus_items = self._summary_skills(candidate, gap_analysis)
        focus = "、".join(focus_items[:4]) if language == "zh" else ", ".join(focus_items[:4])
        education = self._build_education(candidate)
        project_signal = self._best_project_signal(candidate)
        experience_signal = self._best_experience_signal(candidate)
        target_role = jd_profile.job_title or "目标岗位"
        hiring_track = jd_profile.hiring_track
        if language == "zh":
            if hiring_track == "campus":
                if education and project_signal and focus:
                    return "{0}，具备 {1} 基础，曾在项目实践中 {2}，可支持 {3} 相关申请。".format(
                        education[0],
                        focus,
                        project_signal,
                        target_role,
                    )
                if education and focus:
                    return "{0}，具备 {1} 等与 {2} 相关的基础能力，适合校招场景下进一步展示项目与学习潜力。".format(
                        education[0],
                        focus,
                        target_role,
                    )
                return "围绕 {0} 相关要求整理，优先突出教育背景、项目实践与可迁移能力。".format(target_role)
            if hiring_track == "intern":
                if project_signal and focus:
                    return "具备 {0} 基础，并通过项目实践完成 {1}，适合 {2} 实习岗位所需的快速上手场景。".format(
                        focus,
                        project_signal,
                        target_role,
                    )
                return "围绕 {0} 实习岗位整理，强调基础能力、项目实践与快速学习能力。".format(target_role)
            if experience_signal and focus:
                return "具备 {0} 等与 {1} 高相关的经验，过往实践包括 {2}。".format(
                    focus,
                    target_role,
                    experience_signal,
                )
            if focus:
                return "围绕 {0} 需求整理，优先展示与岗位最相关的技能、经历和业务结果：{1}。".format(
                    target_role,
                    focus,
                )
            return "围绕 {0} 需求整理，优先展示最相关的经验、技能和业务结果。".format(target_role)
        if focus:
            return "This resume is reordered for {0}, emphasizing grounded experience in {1}.".format(
                target_role,
                focus,
            )
        return "This resume is reordered for the target role, highlighting the most relevant verified experience."

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
        vague_markers = ["优秀", "出色", "资深", "highly motivated", "excellent", "seasoned"]
        lowered = value.lower()
        if any(marker in value or marker in lowered for marker in vague_markers):
            return fallback
        if language == "zh" and "真实" not in value and len(value) < 36:
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
