import re
from typing import Dict, List, Optional, Tuple
from uuid import uuid4

from backend.app.agents.base import BaseAgent
from backend.app.agents.base import _NO_FALLBACK
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
    llm_metadata = {"max_tokens": 1600}
    GENERIC_TITLE_LINES = {"resume", "cv", "个人简历", "简历"}
    ACTION_HINTS = {
        "负责",
        "推动",
        "搭建",
        "设计",
        "分析",
        "优化",
        "管理",
        "协调",
        "执行",
        "主导",
        "完成",
        "lead",
        "led",
        "built",
        "launched",
        "improved",
        "managed",
        "drove",
        "owned",
        "developed",
        "created",
        "analyzed",
    }
    ROLE_HINTS = {
        "product manager",
        "product",
        "designer",
        "engineer",
        "developer",
        "analyst",
        "manager",
        "marketing",
        "operations",
        "consultant",
        "intern",
        "产品经理",
        "产品",
        "运营",
        "设计",
        "开发",
        "工程师",
        "分析师",
        "实习",
        "市场",
        "增长",
    }
    CONTACT_HINTS = {"email", "phone", "mobile", "linkedin", "github", "wechat", "邮箱", "电话", "手机", "微信"}

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
        fallback_result = self.maybe_use_fallback((fallback_profile, fallback_fact_cards), force_fallback=force_fallback)
        if fallback_result is not _NO_FALLBACK:
            return fallback_result

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
                raise StructuredLLMError("Resume parser returned insufficient structured signal.")
            return normalized_profile, fact_cards
        except StructuredLLMError as exc:
            return self.fallback_on_error(exc, (fallback_profile, fallback_fact_cards))

    def _run_fallback(self, resume_text: str, candidate_notes: str = "") -> Tuple[CandidateProfile, List[FactCard]]:
        normalized_text = self._normalize_text(resume_text)
        language = detect_language(normalized_text, fallback="en")
        sections = self._split_sections(normalized_text)
        basics = CandidateBasics(
            name=self._detect_name(normalized_text),
            email=self._extract_email(normalized_text),
            phone=self._extract_phone(normalized_text),
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
        candidates: List[Tuple[int, str]] = []
        for line in self._candidate_name_lines(text):
            score = self._score_name_candidate(line)
            if score > 0:
                candidates.append((score, line))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]
        first_line = first_non_empty_line(text) or ""
        return "" if self._score_name_candidate(first_line) <= 0 else first_line

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
            if self._looks_like_contact_line(stripped):
                continue
            if self._score_name_candidate(stripped) >= 80:
                continue
            filtered.append(stripped)
        return "\n".join(filtered).strip()

    def _parse_skills(self, lines: List[str], resume_text: str) -> SkillSet:
        skill_tokens: List[str] = []
        for line in lines:
            cleaned = re.sub(r"^(skills|technical skills|技能|专业技能)[:：]?\s*", "", line.strip(), flags=re.IGNORECASE)
            skill_tokens.extend(split_inline_items(cleaned))
        if lines:
            skill_tokens.extend(extract_known_skills("\n".join(lines)))
        else:
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
        blocks = self._group_blocks(lines, mode="experience")
        experiences: List[WorkExperience] = []
        for index, block in enumerate(blocks, start=1):
            header_lines, bullets = self._split_block_components(block)
            header = header_lines[0] if header_lines else ""
            company, title = self._split_header(header, header_lines[1:])
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
        blocks = self._group_blocks(lines, mode="project")
        projects: List[ProjectExperience] = []
        for index, block in enumerate(blocks, start=1):
            header_lines, bullets = self._split_block_components(block)
            header = header_lines[0] if header_lines else "Project {0}".format(index)
            role = self._infer_project_role(header_lines[1:])
            projects.append(
                ProjectExperience(
                    id="proj_{0}".format(index),
                    name=self._clean_project_name(header),
                    role=role,
                    bullets=bullets,
                    skills_used=canonicalize_skills(extract_known_skills("\n".join(block))),
                )
            )
        return projects

    def _parse_education(self, lines: List[str]) -> List[EducationEntry]:
        entries: List[EducationEntry] = []
        for index, block in enumerate(self._group_blocks(lines, mode="education"), start=1):
            primary_line = block[0] if block else ""
            extra_text = " | ".join(block[1:]) if len(block) > 1 else ""
            parts = [part.strip() for part in re.split(r"[|,，]+", primary_line) if part.strip()]
            school = parts[0] if parts else "Unknown School"
            degree = parts[1] if len(parts) > 1 else None
            field = parts[2] if len(parts) > 2 else None
            graduation_date = self._extract_graduation_date(" | ".join([primary_line, extra_text]).strip())
            entries.append(
                EducationEntry(
                    id="edu_{0}".format(index),
                    school=school,
                    degree=degree,
                    field_of_study=field,
                    graduation_date=graduation_date,
                )
            )
        return entries

    def _group_blocks(self, lines: List[str], mode: str = "generic") -> List[List[str]]:
        blocks: List[List[str]] = []
        current: List[str] = []
        normalized_lines = [line.rstrip() for line in lines]
        for index, raw_line in enumerate(normalized_lines):
            line = raw_line.strip()
            next_line = self._next_non_empty_line(normalized_lines, index + 1)
            if not line.strip():
                if current:
                    blocks.append(current)
                    current = []
                continue
            if current and self._should_start_new_block(mode, current, line, next_line):
                blocks.append(current)
                current = [line]
                continue
            current.append(line)
        if current:
            blocks.append(current)
        return blocks

    def _is_bullet(self, line: str) -> bool:
        return bool(re.match(r"^(?:[-*•]|\d+[\.\)])\s+", line.strip()))

    def _strip_bullet(self, line: str) -> str:
        return re.sub(r"^(?:[-*•]|\d+[\.\)])\s+", "", line.strip())

    def _split_header(self, header: str, detail_lines: Optional[List[str]] = None) -> Tuple[str, str]:
        detail_lines = detail_lines or []
        primary_parts = [part.strip() for part in re.split(r"\s+\|\s+|\s+@\s+|\s+-\s+|,\s+", header, maxsplit=2) if part.strip()]
        company = primary_parts[0] if primary_parts else header.strip()
        title = primary_parts[1] if len(primary_parts) > 1 else ""

        if not title:
            for detail in detail_lines:
                if self._looks_like_role_line(detail):
                    title = detail.strip()
                    break
        return company, title

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

    def _candidate_name_lines(self, text: str) -> List[str]:
        candidates: List[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            if self._detect_heading(stripped) and candidates:
                break
            candidates.append(stripped)
            if len(candidates) >= 8:
                break
        return candidates

    def _score_name_candidate(self, candidate: str) -> int:
        value = (candidate or "").strip()
        lowered = value.lower()
        if not value:
            return -1
        if lowered in self.GENERIC_TITLE_LINES or self._detect_heading(value):
            return -1
        if self._looks_like_contact_line(value):
            return -1
        if any(token in value for token in ["|", "http", "www.", "/", "\\"]):
            return -1
        if re.search(r"\d{4,}", value):
            return -1
        if len(value) > 32:
            return -1

        score = 10
        if re.fullmatch(r"[\u4e00-\u9fff·]{2,5}", value):
            score += 90
        elif re.fullmatch(r"[A-Z][A-Za-z'`-]+(?: [A-Z][A-Za-z'`-]+){1,2}", value):
            score += 80
        elif len(value) <= 12:
            score += 10

        if self._looks_like_role_line(value):
            score -= 40
        if any(hint in lowered for hint in self.ROLE_HINTS):
            score -= 25
        return score

    def _looks_like_contact_line(self, line: str) -> bool:
        lowered = (line or "").lower()
        if "@" in line:
            return True
        if re.search(r"(?:\+?\d[\d\s\-()]{6,}\d)", line):
            return True
        return any(hint in lowered for hint in self.CONTACT_HINTS)

    def _extract_email(self, text: str) -> Optional[str]:
        match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
        return match.group(0) if match else None

    def _extract_phone(self, text: str) -> Optional[str]:
        match = re.search(r"(?:\+?\d[\d\s\-()]{6,}\d)", text)
        return match.group(0).strip() if match else None

    def _split_block_components(self, block: List[str]) -> Tuple[List[str], List[str]]:
        header_lines: List[str] = []
        bullets: List[str] = []
        bullet_mode = False
        for line in block:
            if self._is_bullet(line):
                bullets.append(self._strip_bullet(line))
                bullet_mode = True
                continue
            if not bullet_mode and header_lines and self._looks_like_action_line(line):
                bullets.append(line.strip())
                bullet_mode = True
                continue
            if bullet_mode and self._looks_like_action_line(line):
                bullets.append(line.strip())
                continue
            if bullet_mode and bullets:
                bullets[-1] = "{0} {1}".format(bullets[-1], line.strip()).strip()
                continue
            header_lines.append(line.strip())
        return header_lines, [bullet for bullet in bullets if bullet]

    def _should_start_new_block(self, mode: str, current: List[str], line: str, next_line: str) -> bool:
        if any(self._is_bullet(item) for item in current) and not self._is_bullet(line):
            return True
        if not current:
            return False
        if mode == "education" and self._looks_like_education_header(line) and current:
            return True
        if mode == "experience" and self._looks_like_experience_header(line, next_line) and self._current_block_has_signal(current, mode):
            return True
        if mode == "project" and self._looks_like_project_header(line, next_line) and self._current_block_has_signal(current, mode):
            return True
        if mode == "experience" and any(self._is_bullet(item) for item in current):
            return self._looks_like_experience_header(line, next_line)
        if mode == "project" and any(self._is_bullet(item) for item in current):
            return self._looks_like_project_header(line, next_line)
        return False

    def _next_non_empty_line(self, lines: List[str], start_index: int) -> str:
        for candidate in lines[start_index:]:
            if candidate.strip():
                return candidate.strip()
        return ""

    def _looks_like_experience_header(self, line: str, next_line: str = "") -> bool:
        value = line.strip()
        if not value or self._is_bullet(value):
            return False
        if self._looks_like_contact_line(value):
            return False
        if "|" in value or " @ " in value or " at " in value.lower():
            return True
        if self._looks_like_role_line(value) and next_line and self._is_bullet(next_line):
            return True
        return False

    def _looks_like_project_header(self, line: str, next_line: str = "") -> bool:
        value = line.strip()
        if not value or self._is_bullet(value):
            return False
        if re.search(r"(project|项目|课题|case|实战)", value, flags=re.IGNORECASE):
            return True
        return bool(next_line and self._is_bullet(next_line))

    def _looks_like_education_header(self, line: str) -> bool:
        value = line.strip()
        if not value or self._is_bullet(value):
            return False
        return bool(re.search(r"(大学|学院|university|college|school|本科|硕士|博士)", value, flags=re.IGNORECASE))

    def _looks_like_role_line(self, line: str) -> bool:
        value = (line or "").strip().lower()
        if not value:
            return False
        return any(token in value for token in self.ROLE_HINTS)

    def _looks_like_action_line(self, line: str) -> bool:
        value = (line or "").strip()
        lowered = value.lower()
        if not value or self._looks_like_contact_line(value):
            return False
        if re.search(r"\d", value) and len(value) > 8:
            return True
        return any(hint in lowered or hint in value for hint in self.ACTION_HINTS)

    def _current_block_has_signal(self, current: List[str], mode: str) -> bool:
        meaningful = [line.strip() for line in current if line.strip()]
        if len(meaningful) <= 1:
            return False
        if any(self._is_bullet(line) or self._looks_like_action_line(line) for line in meaningful[1:]):
            return True
        if mode == "education":
            return True
        return len(meaningful) >= 2

    def _infer_project_role(self, detail_lines: List[str]) -> Optional[str]:
        for detail in detail_lines:
            if re.search(r"(负责人|owner|role|角色|leader|pm|产品经理|组长|实习生)", detail, flags=re.IGNORECASE):
                return detail.strip()
        return None

    def _clean_project_name(self, header: str) -> str:
        cleaned = re.sub(r"^(project|项目经历|项目)[:：]?\s*", "", header.strip(), flags=re.IGNORECASE)
        return cleaned or header.strip()

    def _extract_graduation_date(self, text: str) -> Optional[str]:
        match = re.search(r"(20\d{2}(?:[./-]\d{1,2})?)", text)
        return match.group(1) if match else None
