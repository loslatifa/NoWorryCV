import re
from typing import List

from backend.app.agents.base import BaseAgent
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.schemas.jd import JDProfile
from backend.app.services.parsers.file_parser import detect_language, first_non_empty_line
from backend.app.services.review_cards import build_review_cards
from backend.app.services.scoring.heuristics import canonicalize_skills, extract_known_skills, extract_tokens, normalize_token, split_inline_items, unique_preserve_order


class JDAnalystAgent(BaseAgent):
    name = "jd_analyst"
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
    }

    def run(self, jd_text: str, force_fallback: bool = False) -> JDProfile:
        fallback = self._run_fallback(jd_text)
        if force_fallback or not self.llm_service.is_available:
            return fallback

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
            profile.review_cards = build_review_cards(profile, jd_text)
            return profile
        except StructuredLLMError:
            return fallback

    def _run_fallback(self, jd_text: str) -> JDProfile:
        lines = [line.strip() for line in jd_text.splitlines() if line.strip()]
        responsibilities = self._normalize_sentences(
            [self._remove_label_prefix(self._strip_bullet(line)) for line in lines if self._looks_like_responsibility(line)]
        )
        must_have = self._normalize_skill_items(
            [item for line in lines if self._looks_like_must_have(line) for item in self._extract_requirement_items(line)]
        )
        nice_to_have = self._normalize_skill_items(
            [item for line in lines if self._looks_like_nice_to_have(line) for item in self._extract_requirement_items(line)]
        )

        detected_skills = canonicalize_skills(extract_known_skills(jd_text))
        job_title = self._clean_job_title(first_non_empty_line(jd_text) or "")
        keywords = self._clean_keywords(
            must_have + nice_to_have + detected_skills + extract_tokens(" ".join(responsibilities[:6] + lines[:6])),
            job_title,
        )
        must_have_skills = unique_preserve_order(must_have + detected_skills[:6])
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
        profile.review_cards = build_review_cards(profile, jd_text)
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
        normalized = stripped.replace(" and ", "、").replace("以及", "、").replace("及", "、")
        items = split_inline_items(normalized)
        return [self._clean_requirement_item(item) for item in items if self._clean_requirement_item(item)]

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
        value = re.sub(r"(校招|校园招聘|社招|实习生|实习|new grad|graduate|campus|internship|intern)", "", value, flags=re.IGNORECASE)
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
            if normalized in self.NOISE_KEYWORDS:
                continue
            if normalized.isdigit():
                continue
            compact = re.sub(r"\s+", "", normalized)
            if normalized_job_title and compact == normalized_job_title:
                continue
            if len(normalized) <= 1:
                continue
            cleaned.append(candidate)
        return unique_preserve_order(canonicalize_skills(cleaned))

    def _clean_requirement_item(self, item: str) -> str:
        value = self._remove_label_prefix((item or "").strip()).strip("。;；:： ")
        value = re.sub(r"^(熟悉|掌握|了解|具备|有|能够|擅长|善于)\s*", "", value)
        return value.strip()
