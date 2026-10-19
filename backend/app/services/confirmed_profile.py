from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from typing import List
import re


def _paragraph_key(text: str) -> str:
    lines = [re.sub(r"^\s*(?:[-•●▪‣]\s+|\d+[.)、]\s+)", "", line).strip()
             for line in (text or "").splitlines()]
    text = " ".join(lines)
    return "".join(char for index, char in enumerate(text)
                   if char.isalnum() or char == "_" or char in "%+/#@-"
                   or (char == "." and index > 0 and index + 1 < len(text)
                       and text[index - 1].isalnum() and text[index + 1].isalnum()))


def is_unassigned_review_fact(card: FactCard) -> bool:
    return (card.source_span.startswith(("follow_up.", "user_added"))
            and card.category in {"work_bullet", "project_bullet", "achievement", "general"})


def align_confirmed_profile(candidate_profile: CandidateProfile, fact_cards: List[FactCard]) -> None:
    """Keep editable profile sections aligned with the user-confirmed fact set."""
    for experience in candidate_profile.work_experiences:
        prefix = "work_experiences.{0}.bullets.".format(experience.id)
        experience.bullets = [card.text for card in fact_cards if card.source_span.startswith(prefix)]
        experience.achievements = [
            bullet for bullet in experience.bullets if any(character.isdigit() for character in bullet)
        ]
        if experience.review_paragraph is not None and _paragraph_key(experience.review_paragraph) != _paragraph_key(" ".join(experience.bullets)):
            experience.review_paragraph = None

    for project in candidate_profile.projects:
        prefix = "projects.{0}.bullets.".format(project.id)
        project.bullets = [card.text for card in fact_cards if card.source_span.startswith(prefix)]
        if project.review_paragraph is not None and _paragraph_key(project.review_paragraph) != _paragraph_key(" ".join(project.bullets)):
            project.review_paragraph = None

    confirmed_skills = [card.text for card in fact_cards if card.category == "skill"]
    # A single editor displays every skill, but the profile retains its categories.
    categories = ("tools", "languages", "soft_skills", "hard_skills")
    original_categories = {
        skill.strip().casefold(): category
        for category in reversed(categories)
        for skill in getattr(candidate_profile.skills, category)
    }
    grouped_skills = {category: [] for category in categories}
    seen_skills = set()
    for skill in confirmed_skills:
        key = skill.strip().casefold()
        if not key or key in seen_skills:
            continue
        seen_skills.add(key)
        grouped_skills[original_categories.get(key, "hard_skills")].append(skill)
    for category, skills in grouped_skills.items():
        setattr(candidate_profile.skills, category, skills)
    candidate_profile.certifications = [
        card.text for card in fact_cards if card.category == "certification"
    ]

    # Unassigned supplemental material stays in fact_cards until the user chooses
    # an experience. Never infer ownership from list position.
