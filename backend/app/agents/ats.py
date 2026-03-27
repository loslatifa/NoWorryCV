from backend.app.agents.base import BaseAgent
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.review import ATSReport
from backend.app.schemas.strategy import ResumeDraft
from backend.app.services.scoring.heuristics import normalize_token


class ATSScoringAgent(BaseAgent):
    name = "ats"

    def run(self, draft: ResumeDraft, jd_profile: JDProfile) -> ATSReport:
        text = draft.markdown
        matched = []
        missing = []
        lower_text = normalize_token(text)
        for keyword in jd_profile.keywords:
            if normalize_token(keyword) in lower_text:
                matched.append(keyword)
            else:
                missing.append(keyword)

        keyword_coverage = 0.0
        if jd_profile.keywords:
            keyword_coverage = len(matched) / float(len(jd_profile.keywords))

        section_presence = {
            "summary": bool(draft.summary),
            "skills": bool(draft.skills_section),
            "experience": bool(draft.experience_section),
            "education": bool(draft.education_section),
        }

        format_warnings = []
        if not section_presence["skills"]:
            format_warnings.append("缺少技能模块，ATS 关键词承载能力会下降。")
        if keyword_coverage < 0.4:
            format_warnings.append("JD 关键词覆盖率偏低，可能影响首轮筛选。")
        if len(text) > 6000:
            format_warnings.append("内容偏长，建议控制在 1 到 2 页可读范围内。")

        structure_bonus = sum(1 for present in section_presence.values() if present) * 4
        score = min(100, int(50 + keyword_coverage * 35 + structure_bonus - len(format_warnings) * 5))

        return ATSReport(
            score=score,
            keyword_coverage=round(keyword_coverage, 2),
            matched_keywords=matched,
            missing_keywords=missing,
            format_warnings=format_warnings,
            section_presence=section_presence,
        )

