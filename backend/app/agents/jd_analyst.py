import re
from typing import List

from backend.app.agents.base import BaseAgent
from backend.app.agents.base import _NO_FALLBACK
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.schemas.jd import JDProfile
from backend.app.services.parsers.file_parser import detect_language, first_non_empty_line
from backend.app.services.scoring.heuristics import canonicalize_skills, extract_known_skills, extract_tokens, normalize_token, split_inline_items, unique_preserve_order


class JDAnalystAgent(BaseAgent):
    name = "jd_analyst"
    RESPONSIBILITY_LABELS = [
        "职责",
        "岗位职责",
        "responsibilities",
        "what you'll do",
        "you will",
    ]
    MUST_HAVE_LABELS = [
        "任职要求",
        "要求",
        "requirements",
        "must have",
        "required",
        "qualification",
        "qualifications",
    ]
    NICE_TO_HAVE_LABELS = [
        "加分项",
        "preferred",
        "plus",
        "bonus",
        "优先",
    ]
    LABEL_PREFIXES = [
        "职责：",
        "职责:",
        "岗位职责：",
        "岗位职责:",
        "任职要求：",
        "任职要求:",
        "要求：",
        "要求:",
        "加分项：",
        "加分项:",
        "preferred:",
        "preferred qualifications:",
        "requirements:",
        "responsibilities:",
    ]
    NOISE_KEYWORDS = {
        "职责",
        "要求",
        "任职要求",
        "岗位职责",
        "加分项",
        "岗位",
        "我们希望你",
        "我们需要你",
        "what you'll do",
        "responsibilities",
        "requirements",
        "preferred",
        "bonus",
        "2025",
        "2026",
        "2027",
        "熟悉",
        "掌握",
        "具备",
        "了解",
        "2025届",
        "2026届",
        "2027届",
        "校招",
        "校园招聘",
        "应届毕业生",
    }

    def run(self, jd_text: str, force_fallback: bool = False) -> JDProfile:
        fallback = self._run_fallback(jd_text)
        fallback_result = self.maybe_use_fallback(fallback, force_fallback=force_fallback)
        if fallback_result is not _NO_FALLBACK:
            return fallback_result

        try:
            profile = self.invoke_structured(
                context={"jd_text": jd_text},
                response_model=JDProfile,
            )
            profile.job_title = self._clean_job_title(profile.job_title or first_non_empty_line(jd_text) or "")
            if not profile.language or profile.language == "auto":
                profile.language = detect_language(jd_text, fallback="en")
            profile.responsibilities = self._normalize_sentences(profile.responsibilities) or fallback.responsibilities
            profile.must_have_skills = self._normalize_skill_items(profile.must_have_skills) or fallback.must_have_skills
            profile.nice_to_have_skills = self._normalize_skill_items(profile.nice_to_have_skills) or fallback.nice_to_have_skills
            profile.keywords = self._clean_keywords(profile.keywords or fallback.keywords, profile.job_title)
            return profile
        except StructuredLLMError as exc:
            return self.fallback_on_error(exc, fallback)

    def _run_fallback(self, jd_text: str) -> JDProfile:
        lines = [line.strip() for line in jd_text.splitlines() if line.strip()]
        title_line = first_non_empty_line(jd_text) or ""
        section_lines = self._extract_section_lines(lines[1:] if lines and lines[0] == title_line else lines)
        responsibilities = self._normalize_sentences(section_lines["responsibilities"])
        must_have = self._normalize_skill_items(section_lines["must_have"])
        nice_to_have = self._normalize_skill_items(section_lines["nice_to_have"])

        detected_skills = canonicalize_skills(extract_known_skills(jd_text))
        job_title = self._clean_job_title(title_line)
        keywords = self._clean_keywords(
            must_have
            + nice_to_have
            + detected_skills
            + extract_tokens(" ".join(responsibilities[:6] + must_have[:6] + nice_to_have[:4])),
            job_title,
        )
        must_have_skills = unique_preserve_order(must_have + [skill for skill in detected_skills if skill not in nice_to_have])
        nice_to_have_skills = unique_preserve_order(nice_to_have)

        profile = JDProfile(
            job_title=job_title,
            department=self._detect_department(jd_text),
            seniority=self._detect_seniority(jd_text),
            hiring_track=self._detect_hiring_track(jd_text),
            responsibilities=responsibilities[:12],
            must_have_skills=must_have_skills[:12],
            nice_to_have_skills=nice_to_have_skills[:8],
            keywords=keywords[:20],
            domain_signals=self._detect_domain_signals(jd_text),
            language=detect_language(jd_text, fallback="en"),
        )
        return profile

    def _strip_bullet(self, line: str) -> str:
        return re.sub(r"^[-*•\d\.\)]\s*", "", line).strip()

    def _remove_label_prefix(self, line: str) -> str:
        value = line.strip()
        lower = value.lower()
        for prefix in self.LABEL_PREFIXES:
            prefix_lower = prefix.lower()
            if lower.startswith(prefix_lower):
                return value[len(prefix) :].strip()
        return value

    def _looks_like_responsibility(self, line: str) -> bool:
        lower = line.lower()
        markers = ["responsibilities", "职责", "负责", "you will", "what you'll do"]
        return line.startswith(("-", "*", "•")) or any(marker in lower for marker in markers)

    def _looks_like_must_have(self, line: str) -> bool:
        lower = line.lower()
        markers = ["must", "required", "requirements", "要求", "熟悉", "需要", "掌握"]
        return any(marker in lower for marker in markers)

    def _looks_like_nice_to_have(self, line: str) -> bool:
        lower = line.lower()
        markers = ["preferred", "plus", "bonus", "加分", "优先"]
        return any(marker in lower for marker in markers)

    def _extract_requirement_items(self, line: str) -> List[str]:
        stripped = self._remove_label_prefix(self._strip_bullet(line))
        normalized = (
            stripped.replace(" and ", "、")
            .replace("以及", "、")
            .replace("及", "、")
            .replace("并且", "、")
            .replace("并", "、")
            .replace("以及具备", "、")
        )
        items: List[str] = []
        for chunk in split_inline_items(normalized):
            items.extend(self._split_requirement_phrase(chunk))
        cleaned_items = [self._clean_requirement_item(item) for item in items if self._clean_requirement_item(item)]
        return [item for item in cleaned_items if self._is_requirement_item_worthy(item)]

    def _detect_seniority(self, text: str) -> str:
        lower = text.lower()
        if "intern" in lower or "实习" in text:
            return "intern"
        if "senior" in lower or "高级" in text:
            return "senior"
        if "lead" in lower or "负责人" in text or "主管" in text:
            return "lead"
        if "director" in lower or "总监" in text:
            return "director"
        if "junior" in lower or "初级" in text:
            return "junior"
        return "mid"

    def _detect_department(self, text: str) -> str:
        lower = text.lower()
        if "product" in lower or "产品" in text:
            return "product"
        if "marketing" in lower or "市场" in text or "增长" in text:
            return "marketing"
        if "data" in lower or "分析" in text:
            return "data"
        if "sales" in lower or "销售" in text:
            return "sales"
        if "engineer" in lower or "开发" in text:
            return "engineering"
        return "general"

    def _detect_domain_signals(self, text: str) -> List[str]:
        signals: List[str] = []
        lower = text.lower()
        if "saas" in lower:
            signals.append("saas")
        if "b2b" in lower:
            signals.append("b2b")
        if "b2c" in lower:
            signals.append("b2c")
        if "e-commerce" in lower or "电商" in text:
            signals.append("e-commerce")
        if "growth" in lower or "增长" in text:
            signals.append("growth")
        return signals

    def _detect_hiring_track(self, text: str) -> str:
        lower = text.lower()
        if "实习" in text or "intern" in lower or "internship" in lower:
            return "intern"
        campus_markers = [
            "校招",
            "校园",
            "应届",
            "毕业生",
            "管培生",
            "new grad",
            "newgrad",
            "graduate",
            "campus",
        ]
        if any(marker in lower or marker in text for marker in campus_markers):
            return "campus"
        if "社招" in text or "experienced" in lower:
            return "experienced"
        if re.search(r"\d+\s*\+?\s*年", text) or re.search(r"\d+\+?\s*years?", lower):
            return "experienced"
        if self._detect_seniority(text) in {"senior", "lead", "director"}:
            return "experienced"
        return "unknown"

    def _clean_job_title(self, title: str) -> str:
        value = (title or "").strip()
        value = re.sub(r"^(20\d{2}(届)?\s*)", "", value)
        value = re.sub(r"\b(20\d{2})\b", "", value)
        value = re.sub(r"(校招|校园招聘|社招|实习生|实习|new grad|graduate|campus|internship|intern)", "", value, flags=re.IGNORECASE)
        value = re.sub(r"(面向应届毕业生|应届毕业生|应届|毕业生|管培生)", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s+", " ", value).strip(" -_|")
        return value or (title or "").strip()

    def _normalize_sentences(self, items: List[str]) -> List[str]:
        cleaned = []
        for item in items:
            value = self._remove_label_prefix(item).strip("。;； ")
            if value:
                cleaned.append(value)
        return unique_preserve_order(cleaned)

    def _normalize_skill_items(self, items: List[str]) -> List[str]:
        normalized = []
        for item in items:
            stripped = self._clean_requirement_item(item)
            if not stripped:
                continue
            normalized.append(stripped)
        return canonicalize_skills(normalized)

    def _clean_keywords(self, keywords: List[str], job_title: str) -> List[str]:
        normalized_job_title = re.sub(r"\s+", "", normalize_token(job_title))
        cleaned = []
        for keyword in keywords:
            candidate = self._remove_label_prefix((keyword or "").strip()).strip("。;；:： ")
            normalized = normalize_token(candidate)
            if not normalized:
                continue
            if normalized in self.NOISE_KEYWORDS or self._is_noise_keyword(normalized):
                continue
            if normalized.isdigit():
                continue
            compact = re.sub(r"\s+", "", normalized)
            if normalized_job_title and compact == normalized_job_title:
                continue
            if len(normalized) <= 1:
                continue
            cleaned.append(candidate)
        canonical = unique_preserve_order(canonicalize_skills(cleaned))
        filtered: List[str] = []
        normalized_candidates = [normalize_token(item) for item in canonical]
        for index, item in enumerate(canonical):
            normalized = normalized_candidates[index]
            if any(
                normalized != other
                and len(normalized) <= len(other)
                and normalized in other.split()
                for other in normalized_candidates
            ):
                continue
            filtered.append(item)
        return filtered

    def _clean_requirement_item(self, item: str) -> str:
        value = self._remove_label_prefix((item or "").strip()).strip("。;；:： ")
        value = re.sub(
            r"^(熟悉|掌握|了解|具备|有|能够|擅长|善于|可以独立|能够独立|具有|有较强的|有良好的|具备较强的|具备良好的)\s*",
            "",
            value,
        )
        value = re.sub(r"(优先|经验者优先|加分)$", "", value).strip()
        return value.strip()

    def _extract_section_lines(self, lines: List[str]) -> dict:
        sections = {"responsibilities": [], "must_have": [], "nice_to_have": []}
        current_section = ""
        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            detected = self._detect_section_heading(stripped)
            inline_payload = self._remove_label_prefix(self._strip_bullet(stripped))
            if detected and self._is_heading_only_line(stripped):
                current_section = detected
                continue
            target_section = detected or current_section or self._infer_section_from_line(stripped)
            if target_section == "responsibilities":
                sections["responsibilities"].append(inline_payload)
            elif target_section == "must_have":
                sections["must_have"].extend(self._extract_requirement_items(inline_payload))
            elif target_section == "nice_to_have":
                sections["nice_to_have"].extend(self._extract_requirement_items(inline_payload))
        return sections

    def _detect_section_heading(self, line: str) -> str:
        lowered = line.lower()
        if any(label in lowered or label in line for label in self.RESPONSIBILITY_LABELS):
            return "responsibilities"
        if any(label in lowered or label in line for label in self.NICE_TO_HAVE_LABELS):
            return "nice_to_have"
        if any(label in lowered or label in line for label in self.MUST_HAVE_LABELS):
            return "must_have"
        return ""

    def _infer_section_from_line(self, line: str) -> str:
        if self._looks_like_nice_to_have(line):
            return "nice_to_have"
        if self._looks_like_must_have(line):
            return "must_have"
        if self._looks_like_responsibility(line):
            return "responsibilities"
        return ""

    def _is_heading_only_line(self, line: str) -> bool:
        stripped = self._strip_bullet(line)
        payload = self._remove_label_prefix(stripped)
        normalized = normalize_token(payload)
        return not normalized or normalized in self.NOISE_KEYWORDS

    def _split_requirement_phrase(self, phrase: str) -> List[str]:
        value = (phrase or "").strip()
        if not value:
            return []
        split_parts = re.split(r"\s*(?:和|及|以及|且)\s*", value)
        return [part.strip() for part in split_parts if part.strip()]

    def _is_requirement_item_worthy(self, item: str) -> bool:
        normalized = normalize_token(item)
        if not normalized or normalized in self.NOISE_KEYWORDS:
            return False
        if len(normalized) <= 1:
            return False
        if self._is_noise_keyword(normalized):
            return False
        return True

    def _is_noise_keyword(self, normalized: str) -> bool:
        if re.search(r"20\d{2}", normalized):
            return True
        if re.fullmatch(r"(校招|校园招聘|社招|实习|实习生|应届|毕业生|new grad|graduate|campus|internship|intern)", normalized):
            return True
        if normalized.endswith("职责") or normalized.endswith("要求"):
            return True
        if normalized in {"面向应届毕业生", "届别"}:
            return True
        return False
