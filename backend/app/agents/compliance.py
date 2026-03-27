import re
from typing import List

from backend.app.agents.base import BaseAgent
from backend.app.schemas.common import FactCard
from backend.app.schemas.review import ComplianceReport
from backend.app.schemas.strategy import ResumeDraft
from backend.app.services.scoring.heuristics import normalize_token


class TruthfulnessComplianceAgent(BaseAgent):
    name = "compliance"

    BLOCKED_PHRASES = ["world-class", "best-in-class", "top-tier", "leading expert", "顶尖", "世界级", "最强"]
    SENIORITY_PHRASES = ["资深", "专家", "senior", "lead", "director", "负责人", "多年经验", "丰富经验"]
    EXAGGERATION_PHRASES = ["全面负责", "独立主导全链路", "0到1全面搭建", "从零到一全面负责", "industry-leading", "best practice"]

    def run(self, draft: ResumeDraft, fact_cards: List[FactCard]) -> ComplianceReport:
        unsupported_claims: List[str] = []
        lower_markdown = draft.markdown.lower()
        blocked_phrases = [phrase for phrase in self.BLOCKED_PHRASES if phrase.lower() in lower_markdown]
        exaggeration_warnings = self._collect_phrase_matches(lower_markdown, self.EXAGGERATION_PHRASES)
        seniority_mismatches = self._collect_seniority_mismatches(draft, fact_cards)
        keyword_stuffing_warnings = self._collect_keyword_stuffing(draft, fact_cards)

        fact_id_set = {card.id for card in fact_cards}
        traceability_map = {record.draft_span: record.fact_ids for record in draft.traceability}

        for section_index, section in enumerate(draft.experience_section, start=1):
            for bullet_index, bullet in enumerate(section.bullets, start=1):
                span = "experience_section.{0}.bullets.{1}".format(section_index, bullet_index)
                fact_ids = [fact_id for fact_id in traceability_map.get(span, []) if fact_id in fact_id_set]
                if not fact_ids:
                    unsupported_claims.append(bullet)

        for section_index, section in enumerate(draft.project_section, start=1):
            for bullet_index, bullet in enumerate(section.bullets, start=1):
                span = "project_section.{0}.bullets.{1}".format(section_index, bullet_index)
                fact_ids = [fact_id for fact_id in traceability_map.get(span, []) if fact_id in fact_id_set]
                if not fact_ids:
                    unsupported_claims.append(bullet)

        risk_level = "low"
        if unsupported_claims:
            risk_level = "high"
        elif blocked_phrases or exaggeration_warnings or seniority_mismatches or keyword_stuffing_warnings:
            risk_level = "medium"

        return ComplianceReport(
            risk_level=risk_level,
            unsupported_claims=unsupported_claims,
            blocked_phrases=blocked_phrases,
            exaggeration_warnings=exaggeration_warnings,
            seniority_mismatches=seniority_mismatches,
            keyword_stuffing_warnings=keyword_stuffing_warnings,
        )

    def _collect_phrase_matches(self, lower_markdown: str, phrases: List[str]) -> List[str]:
        return [phrase for phrase in phrases if phrase.lower() in lower_markdown]

    def _collect_seniority_mismatches(self, draft: ResumeDraft, fact_cards: List[FactCard]) -> List[str]:
        source_text = normalize_token(" ".join(card.text for card in fact_cards))
        check_targets = [draft.headline, draft.summary]
        warnings: List[str] = []
        for phrase in self.SENIORITY_PHRASES:
            normalized_phrase = normalize_token(phrase)
            if any(normalized_phrase in normalize_token(target) for target in check_targets if target) and normalized_phrase not in source_text:
                warnings.append("检测到可能超出事实依据的资历表述：{0}".format(phrase))
        summary = draft.summary or ""
        numeric_mentions = re.findall(r"\d+\s*(?:年|years?)", summary, flags=re.IGNORECASE)
        for mention in numeric_mentions:
            if mention not in source_text and mention not in " ".join(card.text for card in fact_cards):
                warnings.append("summary 中出现可能无法追溯的资历时长：{0}".format(mention))
        return warnings

    def _collect_keyword_stuffing(self, draft: ResumeDraft, fact_cards: List[FactCard]) -> List[str]:
        warnings: List[str] = []
        fact_skills = {normalize_token(card.text) for card in fact_cards if card.category == "skill"}
        for skill in draft.skills_section:
            normalized_skill = normalize_token(skill)
            if normalized_skill and normalized_skill not in fact_skills:
                warnings.append("技能模块出现可能缺少事实卡支撑的词项：{0}".format(skill))
        summary = normalize_token(draft.summary)
        repeated_skills = [skill for skill in draft.skills_section if summary.count(normalize_token(skill)) > 1]
        if len(repeated_skills) >= 3:
            warnings.append("summary 中关键词堆砌偏多，建议减少重复技能词。")
        return warnings[:5]
