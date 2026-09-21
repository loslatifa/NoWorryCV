from typing import List, Optional

from backend.app.agents.base import BaseAgent
from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.review import (
    ATSKeywordDetail,
    ATSReport,
    ATSScoreReason,
    ComplianceReport,
)
from backend.app.schemas.strategy import ResumeDraft, ResumeSectionItem
from backend.app.services.scoring.heuristics import canonicalize_skill, normalize_token, unique_preserve_order


class ATSScoringAgent(BaseAgent):
    name = "ats"

    def run(
        self,
        draft: ResumeDraft,
        jd_profile: JDProfile,
        compliance_report: Optional[ComplianceReport] = None,
    ) -> ATSReport:
        text = self._draft_search_text(draft)
        lower_text = normalize_token(text)
        core_keywords = self._core_keywords(jd_profile)
        optional_keywords = self._optional_keywords(jd_profile, core_keywords)
        all_keywords = unique_preserve_order(core_keywords + optional_keywords)

        matched_core = [keyword for keyword in core_keywords if self._matches_keyword(keyword, lower_text)]
        missing_core = [keyword for keyword in core_keywords if keyword not in matched_core]
        matched_optional = [keyword for keyword in optional_keywords if self._matches_keyword(keyword, lower_text)]
        missing_optional = [keyword for keyword in optional_keywords if keyword not in matched_optional]
        matched = unique_preserve_order(matched_core + matched_optional)
        missing = unique_preserve_order(missing_core + missing_optional)

        core_coverage = self._coverage(core_keywords, lower_text) if core_keywords else 1.0
        optional_coverage = self._coverage(optional_keywords, lower_text) if optional_keywords else 1.0
        keyword_coverage = round(
            min(1.0, (core_coverage * 0.8) + (optional_coverage * 0.2)),
            2,
        )

        section_presence = {
            "summary": bool(draft.summary),
            "skills": bool(draft.skills_section),
            "experience": bool(draft.experience_section),
            "education": bool(draft.education_section),
            "projects": bool(draft.project_section),
        }

        structure_score, structure_warnings = self._structure_score(section_presence, jd_profile)
        format_warnings = list(structure_warnings)
        if core_keywords and core_coverage < 0.5:
            format_warnings.append("JD 核心技能覆盖率偏低，核心要求在简历文本中覆盖不足。")
        if not core_keywords:
            format_warnings.append("当前 JD 未提取出可评分的核心关键词，关键词维度参考价值有限。")
        if len(text) > 6000:
            format_warnings.append("内容偏长，建议控制在 1 到 2 页可读范围内。")
        format_warnings = unique_preserve_order(format_warnings)

        core_keyword_score = round(core_coverage * 100)
        optional_keyword_score = round(optional_coverage * 100)
        truthfulness_score = self._truthfulness_score(compliance_report)
        component_impacts = {
            "core_keywords": round(core_keyword_score * 0.5),
            "optional_keywords": round(optional_keyword_score * 0.1),
            "structure": round(structure_score * 0.2),
            "truthfulness": round(truthfulness_score * 0.2),
        }
        score = min(100, max(0, sum(component_impacts.values())))
        keyword_details = [
            ATSKeywordDetail(
                keyword=keyword,
                category="core" if keyword in core_keywords else "optional",
                matched=keyword in matched,
                locations=self._keyword_locations(draft, keyword),
            )
            for keyword in all_keywords
        ]
        deductions = ["核心关键词未覆盖：{0}".format(keyword) for keyword in missing_core]
        deductions.extend("可选关键词未覆盖：{0}".format(keyword) for keyword in missing_optional)
        deductions.extend(format_warnings)
        deductions.extend(self._compliance_deductions(compliance_report))
        score_reasons = self._score_reasons(
            core_keywords,
            matched_core,
            optional_keywords,
            matched_optional,
            section_presence,
            structure_score,
            compliance_report,
            truthfulness_score,
            component_impacts,
        )

        return ATSReport(
            score=score,
            keyword_coverage=keyword_coverage,
            core_keyword_score=core_keyword_score,
            optional_keyword_score=optional_keyword_score,
            structure_score=structure_score,
            truthfulness_score=truthfulness_score,
            matched_keywords=matched,
            missing_keywords=missing,
            matched_core_keywords=matched_core,
            missing_core_keywords=missing_core,
            matched_optional_keywords=matched_optional,
            missing_optional_keywords=missing_optional,
            keyword_details=keyword_details,
            format_warnings=format_warnings,
            deductions=unique_preserve_order(deductions),
            score_reasons=score_reasons,
            section_presence=section_presence,
        )

    def run_candidate(self, candidate: CandidateProfile, jd_profile: JDProfile) -> ATSReport:
        return self.run(
            self._candidate_draft(candidate),
            jd_profile,
            ComplianceReport(risk_level="low"),
        )

    def _structure_score(self, section_presence, jd_profile: JDProfile):
        if jd_profile.hiring_track == "experienced":
            weights = {"summary": 20, "skills": 25, "experience": 35, "education": 10, "projects": 10}
        elif jd_profile.hiring_track in {"campus", "intern"}:
            weights = {"summary": 15, "skills": 20, "experience": 20, "education": 20, "projects": 25}
        else:
            weights = {"summary": 20, "skills": 25, "experience": 25, "education": 15, "projects": 15}
        score = sum(weight for section, weight in weights.items() if section_presence[section])
        labels = {
            "summary": "个人摘要",
            "skills": "技能",
            "experience": "工作经历",
            "education": "教育背景",
            "projects": "项目经历",
        }
        warnings = [
            "缺少{0}模块，结构维度扣 {1} 分。".format(labels[section], weight)
            for section, weight in weights.items()
            if not section_presence[section]
        ]
        return score, warnings

    def _truthfulness_score(self, compliance_report: Optional[ComplianceReport]) -> int:
        if compliance_report is None or compliance_report.risk_level == "low":
            return 100
        if compliance_report.risk_level == "medium":
            return 70
        return 30

    def _compliance_deductions(self, compliance_report: Optional[ComplianceReport]) -> List[str]:
        if compliance_report is None:
            return []
        items = []
        items.extend("缺少事实溯源：{0}".format(value) for value in compliance_report.unsupported_claims)
        items.extend("真实性提醒：{0}".format(value) for value in compliance_report.exaggeration_warnings)
        items.extend("资历表述提醒：{0}".format(value) for value in compliance_report.seniority_mismatches)
        items.extend("关键词堆叠提醒：{0}".format(value) for value in compliance_report.keyword_stuffing_warnings)
        items.extend("禁用表述：{0}".format(value) for value in compliance_report.blocked_phrases)
        return items

    def _score_reasons(
        self,
        core_keywords,
        matched_core,
        optional_keywords,
        matched_optional,
        section_presence,
        structure_score,
        compliance_report,
        truthfulness_score,
        impacts,
    ) -> List[ATSScoreReason]:
        present_sections = sum(section_presence.values())
        risk_level = compliance_report.risk_level if compliance_report is not None else "low"
        risk_label = {"low": "低", "medium": "中", "high": "高"}.get(risk_level, risk_level)
        return [
            ATSScoreReason(
                category="core_keywords",
                impact=impacts["core_keywords"],
                message=(
                    "核心关键词命中 {0}/{1}，按 50% 权重计入总分。".format(
                        len(matched_core),
                        len(core_keywords),
                    )
                    if core_keywords
                    else "JD 未提取出独立核心关键词，此维度不扣分。"
                ),
                location="标题、摘要、技能与经历",
            ),
            ATSScoreReason(
                category="optional_keywords",
                impact=impacts["optional_keywords"],
                message=(
                    "可选关键词命中 {0}/{1}，按 10% 权重计入总分。".format(
                        len(matched_optional),
                        len(optional_keywords),
                    )
                    if optional_keywords
                    else "JD 未列出独立可选关键词，此维度不扣分。"
                ),
                location="技能与经历",
            ),
            ATSScoreReason(
                category="structure",
                impact=impacts["structure"],
                message="检测到 {0}/5 个核心模块，结构维度得分 {1}/100。".format(
                    present_sections,
                    structure_score,
                ),
                location="简历模块结构",
            ),
            ATSScoreReason(
                category="truthfulness",
                impact=impacts["truthfulness"],
                message="真实性风险为{0}，真实性维度得分 {1}/100。".format(
                    risk_label,
                    truthfulness_score,
                ),
                location="事实卡与经历溯源",
            ),
        ]

    def _keyword_locations(self, draft: ResumeDraft, keyword: str) -> List[str]:
        locations = []
        if self._matches_keyword(keyword, normalize_token(draft.headline)):
            locations.append("标题")
        if self._matches_keyword(keyword, normalize_token(draft.summary)):
            locations.append("个人摘要")
        for skill in draft.skills_section:
            if self._matches_keyword(keyword, normalize_token(skill)):
                locations.append("技能 · {0}".format(skill))
        for section_label, sections in (
            ("工作经历", draft.experience_section),
            ("项目经历", draft.project_section),
        ):
            for section in sections:
                for index, bullet in enumerate(section.bullets, start=1):
                    if self._matches_keyword(keyword, normalize_token(bullet)):
                        locations.append(
                            "{0} · {1} · 第 {2} 条".format(
                                section_label,
                                section.heading,
                                index,
                            )
                        )
        for index, education in enumerate(draft.education_section, start=1):
            if self._matches_keyword(keyword, normalize_token(education)):
                locations.append("教育背景 · 第 {0} 条".format(index))
        return unique_preserve_order(locations)[:4]

    def _draft_search_text(self, draft: ResumeDraft) -> str:
        values = [draft.headline, draft.summary]
        values.extend(draft.skills_section)
        for section in draft.experience_section + draft.project_section:
            values.extend([section.heading, section.subheading or ""])
            values.extend(section.bullets)
        values.extend(draft.education_section)
        structured_text = "\n".join(value for value in values if value)
        return structured_text or draft.markdown

    def _candidate_draft(self, candidate: CandidateProfile) -> ResumeDraft:
        basics = candidate.basics
        headline = " | ".join(
            value for value in [(basics.name or "").strip(), *basics.target_roles] if value
        )
        skills = unique_preserve_order(
            candidate.skills.hard_skills
            + candidate.skills.tools
            + candidate.skills.soft_skills
            + candidate.skills.languages
        )
        experience = []
        for item in candidate.work_experiences:
            dates = " - ".join(value for value in (item.start_date, item.end_date) if value)
            subheading = " | ".join(value for value in (item.company, dates) if value)
            experience.append(
                ResumeSectionItem(
                    heading=item.title or item.company or "工作经历",
                    subheading=subheading or None,
                    bullets=unique_preserve_order(item.bullets + item.achievements),
                )
            )
        projects = [
            ResumeSectionItem(
                heading=item.name,
                subheading=item.role,
                bullets=item.bullets,
            )
            for item in candidate.projects
        ]
        education = [
            " | ".join(
                value
                for value in (
                    item.school,
                    item.degree,
                    item.field_of_study,
                    item.graduation_date,
                )
                if value
            )
            for item in candidate.education
        ]
        draft = ResumeDraft(
            headline=headline,
            summary=candidate.summary,
            skills_section=skills,
            experience_section=experience,
            project_section=projects,
            education_section=education,
        )
        draft.markdown = self._draft_search_text(draft)
        return draft

    def _coverage(self, keywords, lower_text: str) -> float:
        if not keywords:
            return 0.0
        matched = sum(1 for keyword in keywords if self._matches_keyword(keyword, lower_text))
        return matched / float(len(keywords))

    def _core_keywords(self, jd_profile: JDProfile):
        return self._normalize_target_keywords(
            jd_profile.must_have_skills
            + jd_profile.domain_signals[:2]
            + jd_profile.keywords[:4]
        )

    def _optional_keywords(self, jd_profile: JDProfile, core_keywords):
        core_normalized = {normalize_token(keyword) for keyword in core_keywords}
        optional = []
        for keyword in self._normalize_target_keywords(jd_profile.nice_to_have_skills + jd_profile.keywords[4:]):
            if normalize_token(keyword) not in core_normalized:
                optional.append(keyword)
        return optional

    def _matches_keyword(self, keyword: str, lower_text: str) -> bool:
        normalized_keyword = normalize_token(keyword)
        if not normalized_keyword:
            return False
        if normalized_keyword in lower_text:
            return True
        for alias in self._keyword_aliases(keyword):
            if alias in lower_text:
                return True
        if self._looks_like_chinese_phrase(normalized_keyword):
            chunks = [normalized_keyword[index : index + 2] for index in range(0, len(normalized_keyword), 2)]
            chunks = [chunk for chunk in chunks if len(chunk) == 2]
            if chunks and all(chunk in lower_text for chunk in chunks):
                return True
            if normalized_keyword == "漏斗分析" and "漏斗" in lower_text and any(token in lower_text for token in ("分析", "复盘", "优化")):
                return True
        return False

    def _looks_like_chinese_phrase(self, text: str) -> bool:
        return all("\u4e00" <= char <= "\u9fff" for char in text) and len(text) >= 4

    def _normalize_target_keywords(self, keywords):
        normalized = []
        for keyword in keywords:
            cleaned = self._normalize_target_keyword(keyword)
            if cleaned:
                normalized.append(cleaned)
        return unique_preserve_order(normalized)

    def _normalize_target_keyword(self, keyword: str) -> str:
        value = canonicalize_skill((keyword or "").strip())
        if not value:
            return ""
        for suffix in ("经验者优先", "相关经验", "经验", "能力要求", "能力"):
            if value.endswith(suffix) and len(value) > len(suffix) + 1:
                value = value[: -len(suffix)]
                break
        if any(marker in value for marker in ("基于", "能够", "负责", "完成", "推动")) and len(value) >= 8:
            return ""
        return value.strip()

    def _keyword_aliases(self, keyword: str):
        normalized = normalize_token(keyword)
        aliases = set()
        if normalized == "a b testing":
            aliases.update({"a b 测试", "ab 测试", "ab testing"})
        return aliases
