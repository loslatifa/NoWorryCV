import re
from typing import Iterable, List, Set


SKILL_CANONICAL_MAP = {
    "python": "Python",
    "sql": "SQL",
    "excel": "Excel",
    "tableau": "Tableau",
    "power bi": "Power BI",
    "powerbi": "Power BI",
    "java": "Java",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "react": "React",
    "next.js": "Next.js",
    "fastapi": "FastAPI",
    "django": "Django",
    "flask": "Flask",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "aws": "AWS",
    "gcp": "GCP",
    "azure": "Azure",
    "git": "Git",
    "ab testing": "A/B Testing",
    "a/b testing": "A/B Testing",
    "user research": "User Research",
    "roadmap": "Roadmap",
    "growth": "增长",
    "seo": "SEO",
    "sem": "SEM",
    "ga4": "GA4",
    "google ads": "Google Ads",
    "meta ads": "Meta Ads",
    "crm": "CRM",
    "salesforce": "Salesforce",
    "etl": "ETL",
    "machine learning": "Machine Learning",
    "data analysis": "数据分析",
    "product management": "产品管理",
    "stakeholder management": "跨团队协作",
    "figma": "Figma",
    "spark": "Spark",
    "hadoop": "Hadoop",
    "运营": "运营",
    "增长": "增长",
    "数据分析": "数据分析",
    "用户研究": "用户研究",
    "产品规划": "产品规划",
    "跨团队协作": "跨团队协作",
    "项目管理": "项目管理",
    "简历优化": "简历优化",
}

KNOWN_SKILLS = set(SKILL_CANONICAL_MAP)


def normalize_token(token: str) -> str:
    token = token.strip().lower()
    token = re.sub(r"[\s_/]+", " ", token)
    return token.strip(" ,.;:()[]{}")


def unique_preserve_order(items: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    values: List[str] = []
    for item in items:
        normalized = normalize_token(item)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        values.append(item.strip())
    return values


def canonicalize_skill(skill: str) -> str:
    raw = (skill or "").strip()
    if not raw:
        return ""
    return SKILL_CANONICAL_MAP.get(normalize_token(raw), raw)


def canonicalize_skills(skills: Iterable[str]) -> List[str]:
    return unique_preserve_order(canonicalize_skill(skill) for skill in skills if (skill or "").strip())


def extract_known_skills(text: str) -> List[str]:
    lower_text = text.lower()
    matches = [SKILL_CANONICAL_MAP.get(skill, skill) for skill in KNOWN_SKILLS if skill in lower_text]
    return unique_preserve_order(matches)


def split_inline_items(text: str) -> List[str]:
    return [item.strip() for item in re.split(r"[，,、;；|]+", text or "") if item.strip()]


def extract_tokens(text: str) -> List[str]:
    raw_tokens = re.findall(r"[A-Za-z0-9\+\#\.\-]{2,}|[\u4e00-\u9fff]{2,}", text)
    return unique_preserve_order(raw_tokens)


def score_keyword_overlap(candidate_tokens: Iterable[str], target_tokens: Iterable[str]) -> float:
    candidate_set = {normalize_token(token) for token in candidate_tokens if normalize_token(token)}
    target_set = {normalize_token(token) for token in target_tokens if normalize_token(token)}
    if not target_set:
        return 0.0
    overlap = len(candidate_set & target_set)
    return overlap / float(len(target_set))
