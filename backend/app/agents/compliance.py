from typing import List

from backend.app.agents.base import BaseAgent
from backend.app.schemas.common import FactCard
from backend.app.schemas.review import ComplianceReport
from backend.app.schemas.strategy import ResumeDraft


class TruthfulnessComplianceAgent(BaseAgent):
    name = "compliance"

    BLOCKED_PHRASES = ["world-class", "best-in-class", "top-tier", "leading expert", "顶尖", "世界级", "最强"]

    def run(self, draft: ResumeDraft, fact_cards: List[FactCard]) -> ComplianceReport:
        unsupported_claims: List[str] = []
        lower_markdown = draft.markdown.lower()
        blocked_phrases = [phrase for phrase in self.BLOCKED_PHRASES if phrase.lower() in lower_markdown]

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
        elif blocked_phrases:
            risk_level = "medium"

        return ComplianceReport(
            risk_level=risk_level,
            unsupported_claims=unsupported_claims,
            blocked_phrases=blocked_phrases,
        )
