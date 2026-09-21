from typing import List

from backend.app.agents.base import BaseAgent, _NO_FALLBACK
from backend.app.schemas.agent_outputs import PartialRewriteOutput
from backend.app.schemas.common import FactCard
from backend.app.schemas.jd import JDProfile
from backend.app.schemas.run_state import PartialRewriteRequest
from backend.app.services.draft_editing import get_partial_target_value, trace_span_for_request
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.scoring.heuristics import normalize_token, unique_preserve_order


class PartialRewriteAgent(BaseAgent):
    name = "partial_rewrite"
    llm_metadata = {"max_tokens": 500}

    def run(
        self,
        request: PartialRewriteRequest,
        fact_cards: List[FactCard],
        jd_profile: JDProfile,
        force_fallback: bool = False,
    ) -> PartialRewriteOutput:
        current_value = get_partial_target_value(request)
        fallback = self._fallback_output(request, current_value, fact_cards, jd_profile)
        fallback_result = self.maybe_use_fallback(fallback, force_fallback=force_fallback)
        if fallback_result is not _NO_FALLBACK:
            return fallback_result

        try:
            output = self.invoke_structured(
                context={
                    "target_type": request.target_type,
                    "current_value": current_value,
                    "instruction": request.instruction.strip(),
                    "jd_profile": jd_profile,
                    "confirmed_fact_cards": [
                        {"id": card.id, "category": card.category, "text": card.text}
                        for card in fact_cards
                    ],
                },
                response_model=PartialRewriteOutput,
            )
            return self._normalize_output(request, output, fallback, fact_cards)
        except StructuredLLMError as exc:
            return self.fallback_on_error(exc, fallback)

    def _fallback_output(self, request, current_value, fact_cards, jd_profile) -> PartialRewriteOutput:
        if request.target_type == "skills":
            confirmed_skills = [card.text for card in fact_cards if card.category == "skill"]
            jd_tokens = {normalize_token(item) for item in jd_profile.must_have_skills + jd_profile.keywords}
            ordered = sorted(
                unique_preserve_order(confirmed_skills),
                key=lambda item: normalize_token(item) not in jd_tokens,
            )
            return PartialRewriteOutput(replacement_items=ordered or list(current_value))

        fact_ids = []
        if request.target_type in {"experience_bullet", "project_bullet"}:
            span = trace_span_for_request(request)
            record = next((item for item in request.draft.traceability if item.draft_span == span), None)
            fact_ids = list(record.fact_ids) if record else []
        return PartialRewriteOutput(replacement_text=str(current_value), fact_ids=fact_ids)

    def _normalize_output(self, request, output, fallback, fact_cards) -> PartialRewriteOutput:
        valid_fact_ids = {card.id for card in fact_cards}
        output.fact_ids = [fact_id for fact_id in output.fact_ids if fact_id in valid_fact_ids]
        if request.target_type == "skills":
            confirmed_skills = {normalize_token(card.text): card.text for card in fact_cards if card.category == "skill"}
            output.replacement_items = unique_preserve_order(
                confirmed_skills[normalize_token(item)]
                for item in output.replacement_items
                if normalize_token(item) in confirmed_skills
            )
            return output if output.replacement_items else fallback

        output.replacement_text = output.replacement_text.strip()
        if not output.replacement_text:
            return fallback
        if request.target_type in {"summary", "experience_bullet", "project_bullet"} and fact_cards and not output.fact_ids:
            return fallback
        return output
