from typing import List, Optional

from backend.app.agents.base import BaseAgent
from backend.app.agents.base import _NO_FALLBACK
from backend.app.schemas.agent_outputs import CompactKnowledgeReviewCardDeck
from backend.app.schemas.jd import JDProfile, KnowledgeReviewCard, KnowledgeReviewCardDeck
from backend.app.services.llm.structured import StructuredLLMError
from backend.app.services.review_cards import build_review_cards
from backend.app.services.scoring.heuristics import canonicalize_skills, normalize_token, unique_preserve_order


class JDReviewCardAgent(BaseAgent):
    name = "jd_review_card"
    llm_metadata = {"max_tokens": 800}

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
                    "max_cards": 3,
                },
                response_model=KnowledgeReviewCardDeck,
            )
            cards = self._normalize_cards(deck.review_cards or [])
            if not cards and fallback:
                return fallback
            if not cards:
                raise StructuredLLMError("JDReviewCardAgent returned no review cards.")
            return cards
        except StructuredLLMError as exc:
            try:
                compact_cards = self._run_compact_llm(jd_profile, jd_text, fallback)
                if compact_cards:
                    return compact_cards
            except StructuredLLMError:
                pass
            if fallback:
                return fallback
            return self.fallback_on_error(exc, fallback)

    def _run_fallback(self, jd_profile: JDProfile, jd_text: str) -> List[KnowledgeReviewCard]:
        return build_review_cards(jd_profile, jd_text, max_cards=3)

    def _run_compact_llm(
        self,
        jd_profile: JDProfile,
        jd_text: str,
        fallback: List[KnowledgeReviewCard],
    ) -> List[KnowledgeReviewCard]:
        compact_deck = self.invoke_structured(
            context={
                "jd_profile": jd_profile,
                "jd_text": jd_text,
                "max_cards": 3,
                "compact_mode": True,
            },
            response_model=CompactKnowledgeReviewCardDeck,
        )
        compact_cards = compact_deck.review_cards or []
        if not compact_cards:
            raise StructuredLLMError("JDReviewCardAgent compact mode returned no review cards.")

        merged_cards: List[KnowledgeReviewCard] = []
        for index, compact_card in enumerate(compact_cards[:3], start=1):
            title = (compact_card.title or "").strip()
            keywords = self._normalize_keywords(compact_card.keywords or [title])
            if not title or not keywords:
                continue
            fallback_card = self._match_fallback_card(keywords, fallback)
            merged_cards.append(
                KnowledgeReviewCard(
                    id="review_{0}".format(index),
                    title=title,
                    focus_area=(compact_card.focus_area or (fallback_card.focus_area if fallback_card else "岗位知识点")).strip(),
                    why_it_matters=(fallback_card.why_it_matters if fallback_card else "").strip(),
                    review_tip=(fallback_card.review_tip if fallback_card else "").strip(),
                    sample_question=(fallback_card.sample_question if fallback_card else "").strip(),
                    keywords=keywords[:4],
                )
            )
        if not merged_cards:
            raise StructuredLLMError("JDReviewCardAgent compact mode produced no usable cards.")
        return self._normalize_cards(merged_cards)

    def _match_fallback_card(
        self,
        keywords: List[str],
        fallback_cards: List[KnowledgeReviewCard],
    ) -> Optional[KnowledgeReviewCard]:
        normalized_keywords = {normalize_token(keyword) for keyword in keywords if normalize_token(keyword)}
        for card in fallback_cards:
            fallback_tokens = {normalize_token(card.title), *(normalize_token(keyword) for keyword in card.keywords)}
            if normalized_keywords & fallback_tokens:
                return card
        return fallback_cards[0] if fallback_cards else None

    def _normalize_cards(self, cards: List[KnowledgeReviewCard]) -> List[KnowledgeReviewCard]:
        normalized_cards: List[KnowledgeReviewCard] = []
        for index, card in enumerate(cards[:3], start=1):
            title = (card.title or "").strip()
            if not title:
                continue
            keywords = self._normalize_keywords(card.keywords or [title])
            normalized_cards.append(
                KnowledgeReviewCard(
                    id=(card.id or "review_{0}".format(index)).strip() or "review_{0}".format(index),
                    title=title,
                    focus_area=(card.focus_area or "岗位知识点").strip(),
                    why_it_matters=self._trim_text(card.why_it_matters, 90),
                    review_tip=self._trim_text(card.review_tip, 90),
                    sample_question=self._trim_text(card.sample_question, 80),
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

    def _trim_text(self, text: str, limit: int) -> str:
        value = (text or "").strip()
        if len(value) <= limit:
            return value
        return value[: limit - 1].rstrip("，,、；;。.!?？") + "…"
