"""Translate user choices into generation constraints without creating candidate facts."""
from backend.app.schemas.preferences import ResumePreferences


FAMILY_FOCUS = {
    "engineering": ["技术实现", "系统设计", "测试", "可靠性", "Python", "Java", "API", "testing"],
    "data": ["数据分析", "统计", "建模", "实验", "SQL", "Python", "analytics", "statistics"],
    "product": ["用户需求", "产品设计", "指标", "跨团队协作"],
    "design": ["用户研究", "交互设计", "可用性"],
    "marketing": ["市场分析", "内容", "增长", "转化"],
    "operations": ["流程", "运营", "效率", "协作"],
    "finance": ["财务分析", "风险", "审计", "准确性"],
}


def paper_size(preferences):
    return "A4" if preferences.region in {"CN", "HK", "SG", "UK", "EU"} else "Letter"


def merge_preferences(saved, override):
    return saved.model_copy(update=override.model_dump(exclude_unset=True), deep=True) if override is not None else saved.model_copy(deep=True)


def export_preferences(preferences, language):
    return preferences.model_copy(update={"language": language if language in {"en", "zh"} else "auto"})


def target_pages(preferences):
    return int(preferences.page_count) if preferences.page_count != "auto" else 1


def effective_language(output_language, preferences, detected_language):
    # The pre-existing explicit language API remains authoritative.
    return next((value for value in (output_language, preferences.language, detected_language)
                 if value in {"zh", "en"}), "auto")


def apply_jd_preferences(jd, preferences):
    effective = jd.model_copy(deep=True)
    if preferences.hiring_track != "auto":
        effective.hiring_track = preferences.hiring_track
    if preferences.seniority != "auto":
        effective.seniority = preferences.seniority
    return effective


def apply_strategy_preferences(strategy, preferences):
    strategy.preferences = preferences.model_copy(deep=True)
    if preferences.hiring_track != "auto":
        strategy.audience_hint = preferences.hiring_track
    if preferences.job_family != "auto":
        focus = "、".join(FAMILY_FOCUS[preferences.job_family])
        instruction = "目标岗位族：{0}；优先选择与{1}有关的已确认事实，不补造技能。".format(preferences.job_family, focus)
        if instruction not in strategy.revision_notes:
            strategy.revision_notes.append(instruction)
    if preferences.seniority != "auto":
        instruction = "目标资历为 {0}，只调整表达重心，不把目标资历写成候选人的实际职级或领导经历。".format(preferences.seniority)
        if instruction not in strategy.tone_rules:
            strategy.tone_rules.append(instruction)
    tone = {
        "concise": "使用简短主动句，每条只表达一项有事实依据的行动或结果。",
        "formal": "使用正式、客观的书面表达，避免口语、夸张评价和宣传用语。",
    }.get(preferences.tone)
    if tone and tone not in strategy.tone_rules:
        strategy.tone_rules.append(tone)
    if preferences.page_count == "1":
        strategy.max_experiences = min(strategy.max_experiences, 3)
        strategy.max_bullets_per_experience = min(strategy.max_bullets_per_experience, 3)
        strategy.max_skills = min(strategy.max_skills, 10)
    elif preferences.page_count == "2":
        strategy.max_experiences = max(strategy.max_experiences, 5)
        strategy.max_bullets_per_experience = min(strategy.max_bullets_per_experience, 4)
    if preferences.tone == "concise":
        strategy.max_bullets_per_experience = min(strategy.max_bullets_per_experience, 2)
    return strategy
