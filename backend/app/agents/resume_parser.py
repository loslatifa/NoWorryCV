import re
from typing import Dict, List, Tuple
from uuid import uuid4

from backend.app.agents.base import BaseAgent
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.schemas.candidate import (
    CandidateBasics,
    CandidateProfile,
    EducationEntry,
    ProjectExperience,
    SkillSet,
    WorkExperience,
)
from backend.app.schemas.common import FactCard
from backend.app.services.parsers.file_parser import detect_language, first_non_empty_line
from backend.app.services.scoring.heuristics import canonicalize_skills, extract_known_skills, split_inline_items, unique_preserve_order


class ResumeParserAgent(BaseAgent):
    name = "resume_parser"
    GENERIC_TITLE_LINES = {"resume", "cv", "个人简历", "简历"}

    SECTION_ALIASES = {
        "summary": ["summary", "profile", "about", "个人简介", "简介"],
        "experience": ["experience", "work experience", "professional experience", "工作经历", "经历"],
        "skills": ["skills", "technical skills", "专业技能", "技能"],
        "projects": ["projects", "project experience", "项目经历", "项目"],
        "education": ["education", "教育背景", "学历", "教育"],
        "certifications": ["certification", "certifications", "证书", "认证"],
    }

    def run(
        self,
        resume_text: str,
        candidate_notes: str = "",
        force_fallback: bool = False,
    ) -> Tuple[CandidateProfile, List[FactCard]]:
        fallback_profile, fallback_fact_cards = self._run_fallback(resume_text, candidate_notes)
        if force_fallback or not self.llm_service.is_available:
            return fallback_profile, fallback_fact_cards

        try:
            profile = self.invoke_structured(
                context={
                    "resume_text": resume_text,
                    "candidate_notes": candidate_notes,
                },
                response_model=CandidateProfile,
            )
            normalized_profile = self._normalize_profile(profile, resume_text, candidate_notes)
            fact_cards = self._build_fact_cards(normalized_profile)
            if not self._has_minimum_signal(normalized_profile, fact_cards):
                return fallback_profile, fallback_fact_cards
            return normalized_profile, fact_cards
        except StructuredLLMError:
            return fallback_profile, fallback_fact_cards

    def _run_fallback(self, resume_text: str, candidate_notes: str = "") -> Tuple[CandidateProfile, List[FactCard]]:
        normalized_text = self._normalize_text(resume_text)
        language = detect_language(normalized_text, fallback="en")
        sections = self._split_sections(normalized_text)
        basics = CandidateBasics(
            name=self._detect_name(normalized_text),
            language=language,
        )

        summary = self._build_summary_block(sections.get("summary", []), basics.name)
        if candidate_notes.strip():
            summary = "\n".join(filter(None, [summary, candidate_notes.strip()]))

        skills = self._parse_skills(sections.get("skills", []), normalized_text)
        work_experiences = self._parse_experiences(sections.get("experience", []))
        projects = self._parse_projects(sections.get("projects", []))
        education = self._parse_education(sections.get("education", []))
        certifications = unique_preserve_order(sections.get("certifications", []))

        profile = CandidateProfile(
            basics=basics,
            summary=summary,
            work_experiences=work_experiences,
            projects=projects,
            education=education,
            skills=skills,
            certifications=certifications,
        )
        fact_cards = self._build_fact_cards(profile)
        return profile, fact_cards

    def _normalize_profile(
        self,
        profile: CandidateProfile,
        resume_text: str,
        candidate_notes: str,
    ) -> CandidateProfile:
        normalized_text = self._normalize_text(resume_text)
        if not profile.basics.name:
            profile.basics.name = self._detect_name(normalized_text)
        if not profile.basics.language or profile.basics.language == "auto":
            profile.basics.language = detect_language(normalized_text, fallback="en")
        if candidate_notes.strip() and candidate_notes not in profile.summary:
            profile.summary = "\n".join(filter(None, [profile.summary.strip(), candidate_notes.strip()]))

        for index, experience in enumerate(profile.work_experiences, start=1):
            if not experience.id:
                experience.id = "exp_{0}".format(index)
        for index, project in enumerate(profile.projects, start=1):
            if not project.id:
                project.id = "proj_{0}".format(index)
        for index, education in enumerate(profile.education, start=1):
            if not education.id:
                education.id = "edu_{0}".format(index)
        return profile

    def _has_minimum_signal(self, profile: CandidateProfile, fact_cards: List[FactCard]) -> bool:
        return bool(profile.work_experiences or profile.projects or profile.skills.hard_skills or fact_cards)

    def _normalize_text(self, text: str) -> str:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        normalized_lines = []
        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            line = re.sub(r"^\s*#{1,6}\s*", "", line)
            line = line.replace("\u00a0", " ").strip()
            normalized_lines.append(line)
        return "\n".join(normalized_lines)

    def _split_sections(self, text: str) -> Dict[str, List[str]]:
        sections: Dict[str, List[str]] = {"summary": []}
        current = "summary"
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                sections.setdefault(current, []).append("")
                continue
            detected = self._detect_heading(line)
            if detected:
                current = detected
                sections.setdefault(current, [])
                continue
            sections.setdefault(current, []).append(line)
        return sections

    def _detect_heading(self, line: str) -> str:
        normalized = re.sub(r"[:：]+$", "", line.strip().lower())
        for canonical, aliases in self.SECTION_ALIASES.items():
            if normalized in aliases:
                return canonical
        return ""

    def _detect_name(self, text: str) -> str:
        for line in text.splitlines():
            candidate = line.strip()
            if not candidate:
                continue
            lowered = candidate.lower()
            if lowered in self.GENERIC_TITLE_LINES:
                continue
            if self._detect_heading(candidate):
                continue
            if "@" in candidate or re.search(r"\d{6,}", candidate):
                continue
            if len(candidate) > 32:
                continue
            if any(token in candidate for token in ["|", "http", "www."]):
                continue
            return candidate
        first_line = first_non_empty_line(text) or ""
        return "" if first_line.lower() in self.GENERIC_TITLE_LINES else first_line

    def _build_summary_block(self, lines: List[str], candidate_name: str) -> str:
        filtered = []
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            if stripped.lower() in self.GENERIC_TITLE_LINES:
                continue
            if candidate_name and stripped == candidate_name:
                continue
            filtered.append(stripped)
        return "\n".join(filtered).strip()

    def _parse_skills(self, lines: List[str], resume_text: str) -> SkillSet:
        skill_tokens: List[str] = []
        for line in lines:
            cleaned = re.sub(r"^(skills|technical skills|技能|专业技能)[:：]?\s*", "", line.strip(), flags=re.IGNORECASE)
            skill_tokens.extend(split_inline_items(cleaned))
        skill_tokens.extend(extract_known_skills(resume_text))
        unique_skills = canonicalize_skills(skill_tokens)
        hard_skills: List[str] = []
        tools: List[str] = []
        for skill in unique_skills:
            if skill.lower() in {"excel", "tableau", "power bi", "powerbi", "salesforce", "figma"}:
                tools.append(skill)
            else:
                hard_skills.append(skill)
        return SkillSet(hard_skills=hard_skills, tools=tools)

    def _parse_experiences(self, lines: List[str]) -> List[WorkExperience]:
        blocks = self._group_blocks(lines)
        experiences: List[WorkExperience] = []
        for index, block in enumerate(blocks, start=1):
            header = block[0] if block else ""
            bullets = [self._strip_bullet(line) for line in block[1:] if self._strip_bullet(line)]
            company, title = self._split_header(header)
            experiences.append(
                WorkExperience(
                    id="exp_{0}".format(index),
                    company=company,
                    title=title,
                    bullets=bullets,
                    skills_used=canonicalize_skills(extract_known_skills("\n".join(block))),
                    achievements=[bullet for bullet in bullets if re.search(r"\d", bullet)],
                    raw_block="\n".join(block),
                )
            )
        return experiences

    def _parse_projects(self, lines: List[str]) -> List[ProjectExperience]:
        blocks = self._group_blocks(lines)
        projects: List[ProjectExperience] = []
        for index, block in enumerate(blocks, start=1):
            header = block[0] if block else "Project {0}".format(index)
            bullets = [self._strip_bullet(line) for line in block[1:] if self._strip_bullet(line)]
            projects.append(
                ProjectExperience(
                    id="proj_{0}".format(index),
                    name=header,
                    bullets=bullets,
                    skills_used=canonicalize_skills(extract_known_skills("\n".join(block))),
                )
            )
        return projects

    def _parse_education(self, lines: List[str]) -> List[EducationEntry]:
        entries: List[EducationEntry] = []
        for index, line in enumerate([value for value in lines if value.strip()], start=1):
            parts = [part.strip() for part in re.split(r"[|,，]+", line) if part.strip()]
            school = parts[0] if parts else "Unknown School"
            degree = parts[1] if len(parts) > 1 else None
            field = parts[2] if len(parts) > 2 else None
            entries.append(
                EducationEntry(
                    id="edu_{0}".format(index),
                    school=school,
                    degree=degree,
                    field_of_study=field,
                )
            )
        return entries

    def _group_blocks(self, lines: List[str]) -> List[List[str]]:
        blocks: List[List[str]] = []
        current: List[str] = []
        for line in lines:
            if not line.strip():
                if current:
                    blocks.append(current)
                    current = []
                continue
            if current and not self._is_bullet(line) and self._is_bullet(current[-1]):
                blocks.append(current)
                current = [line]
                continue
            current.append(line)
        if current:
            blocks.append(current)
        return blocks

    def _is_bullet(self, line: str) -> bool:
        return bool(re.match(r"^[-*•]\s+", line.strip()))

    def _strip_bullet(self, line: str) -> str:
        return re.sub(r"^[-*•]\s+", "", line.strip())

    def _split_header(self, header: str) -> Tuple[str, str]:
        parts = [part.strip() for part in re.split(r"\|| @ | - |, ", header, maxsplit=1) if part.strip()]
        if len(parts) >= 2:
            return parts[0], parts[1]
        return header.strip(), ""

    def _build_fact_cards(self, profile: CandidateProfile) -> List[FactCard]:
        fact_cards: List[FactCard] = []
        for experience in profile.work_experiences:
            for index, bullet in enumerate(experience.bullets, start=1):
                fact_cards.append(
                    FactCard(
                        id="fact_{0}".format(uuid4().hex[:10]),
                        category="work_bullet",
                        text=bullet,
                        source_span="work_experiences.{0}.bullets.{1}".format(experience.id, index),
                    )
                )
        for project in profile.projects:
            for index, bullet in enumerate(project.bullets, start=1):
                fact_cards.append(
                    FactCard(
                        id="fact_{0}".format(uuid4().hex[:10]),
                        category="project_bullet",
                        text=bullet,
                        source_span="projects.{0}.bullets.{1}".format(project.id, index),
                    )
                )
        for skill in profile.skills.hard_skills + profile.skills.tools:
            fact_cards.append(
                FactCard(
                    id="fact_{0}".format(uuid4().hex[:10]),
                    category="skill",
                    text=skill,
                    source_span="skills",
                )
            )
        for education in profile.education:
            education_parts = [education.school, education.degree or "", education.field_of_study or ""]
            education_text = " | ".join(part for part in education_parts if part)
            if education_text:
                fact_cards.append(
                    FactCard(
                        id="fact_{0}".format(uuid4().hex[:10]),
                        category="education",
                        text=education_text,
                        source_span="education.{0}".format(education.id),
                    )
                )
        for index, certification in enumerate(profile.certifications, start=1):
            fact_cards.append(
                FactCard(
                    id="fact_{0}".format(uuid4().hex[:10]),
                    category="certification",
                    text=certification,
                    source_span="certifications.{0}".format(index),
                )
            )
        return fact_cards
