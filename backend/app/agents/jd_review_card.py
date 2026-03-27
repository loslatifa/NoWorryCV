from typing import List

from backend.app.agents.base import BaseAgent
from backend.app.agents.base import _NO_FALLBACK
from backend.app.schemas.jd import JDProfile, KnowledgeReviewCard, KnowledgeReviewCardDeck
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.review_cards import build_review_cards
from backend.app.services.scoring.heuristics import canonicalize_skills, normalize_token, unique_preserve_order


class JDReviewCardAgent(BaseAgent):
    name = "jd_review_card"

    def run(self, jd_profile: JDProfile, jd_text: str, force_fallback: bool = False) -> List[KnowledgeReviewCard]:
        fallback = self._run_fallback(jd_profile, jd_text)
        fallback_result = self.maybe_use_fallback(fallback, force_fallback=force_fallback)
        if fallback_result is not _NO_FALLBACK:
            return fallback_result

        try:
            deck = self.invoke_structured(
                context={
                    "jd_profile": jd_profile,
                    "jd_text": jd_text,
                    "max_cards": 5,
                },
                response_model=KnowledgeReviewCardDeck,
            )
            cards = self._normalize_cards(deck.review_cards or [])
            if not cards:
                raise StructuredLLMError("JDReviewCardAgent returned no review cards.")
            return cards
        except StructuredLLMError as exc:
            return self.fallback_on_error(exc, fallback)

    def _run_fallback(self, jd_profile: JDProfile, jd_text: str) -> List[KnowledgeReviewCard]:
        return build_review_cards(jd_profile, jd_text)

    def _normalize_cards(self, cards: List[KnowledgeReviewCard]) -> List[KnowledgeReviewCard]:
        normalized_cards: List[KnowledgeReviewCard] = []
        for index, card in enumerate(cards[:5], start=1):
            title = (card.title or "").strip()
            if not title:
                continue
            keywords = self._normalize_keywords(card.keywords or [title])
            normalized_cards.append(
                KnowledgeReviewCard(
                    id=(card.id or "review_{0}".format(index)).strip() or "review_{0}".format(index),
                    title=title,
                    focus_area=(card.focus_area or "岗位知识点").strip(),
                    why_it_matters=(card.why_it_matters or "").strip(),
                    review_tip=(card.review_tip or "").strip(),
                    sample_question=(card.sample_question or "").strip(),
                    keywords=keywords[:4],
                )
            )
        return normalized_cards

    def _normalize_keywords(self, keywords: List[str]) -> List[str]:
        cleaned = []
        for keyword in keywords:
            value = (keyword or "").strip()
            normalized = normalize_token(value)
            if not normalized or normalized.isdigit():
                continue
            cleaned.append(value)
        return unique_preserve_order(canonicalize_skills(cleaned))
