from backend.app.schemas.candidate import CandidateProfile
from backend.app.schemas.common import FactCard
from typing import List


def align_confirmed_profile(candidate_profile: CandidateProfile, fact_cards: List[FactCard]) -> None:
    """Keep editable profile sections aligned with the user-confirmed fact set."""
    for experience in candidate_profile.work_experiences:
        prefix = "work_experiences.{0}.bullets.".format(experience.id)
        experience.bullets = [card.text for card in fact_cards if card.source_span.startswith(prefix)]
        experience.achievements = [
            bullet for bullet in experience.bullets if any(character.isdigit() for character in bullet)
        ]

    for project in candidate_profile.projects:
        prefix = "projects.{0}.bullets.".format(project.id)
        project.bullets = [card.text for card in fact_cards if card.source_span.startswith(prefix)]

    confirmed_skills = [card.text for card in fact_cards if card.category == "skill"]
    original_tools = {tool.strip().lower() for tool in candidate_profile.skills.tools}
    candidate_profile.skills.tools = [skill for skill in confirmed_skills if skill.strip().lower() in original_tools]
    candidate_profile.skills.hard_skills = [
        skill for skill in confirmed_skills if skill.strip().lower() not in original_tools
    ]
    candidate_profile.certifications = [
        card.text for card in fact_cards if card.category == "certification"
    ]

    supplemental_facts = [
        card
        for card in fact_cards
        if card.source_type == "user"
        and card.source_span.startswith(("follow_up.", "user_added"))
    ]
    for card in supplemental_facts:
        if card.category == "project_bullet" and candidate_profile.projects:
            candidate_profile.projects[0].bullets.append(card.text)
        elif card.category in {"work_bullet", "achievement"} and candidate_profile.work_experiences:
            candidate_profile.work_experiences[0].bullets.append(card.text)
        elif card.category == "general":
            if candidate_profile.work_experiences:
                candidate_profile.work_experiences[0].bullets.append(card.text)
            elif candidate_profile.projects:
                candidate_profile.projects[0].bullets.append(card.text)
