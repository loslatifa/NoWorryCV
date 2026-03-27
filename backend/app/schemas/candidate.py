from typing import List, Optional

from pydantic import BaseModel, Field


class CandidateBasics(BaseModel):
    name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    target_roles: List[str] = Field(default_factory=list)
    language: str = "auto"


class WorkExperience(BaseModel):
    id: str
    company: Optional[str] = None
    title: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)
    skills_used: List[str] = Field(default_factory=list)
    achievements: List[str] = Field(default_factory=list)
    raw_block: Optional[str] = None


class ProjectExperience(BaseModel):
    id: str
    name: str
    role: Optional[str] = None
    bullets: List[str] = Field(default_factory=list)
    skills_used: List[str] = Field(default_factory=list)


class EducationEntry(BaseModel):
    id: str
    school: str
    degree: Optional[str] = None
    field_of_study: Optional[str] = None
    graduation_date: Optional[str] = None


class SkillSet(BaseModel):
    hard_skills: List[str] = Field(default_factory=list)
    soft_skills: List[str] = Field(default_factory=list)
    tools: List[str] = Field(default_factory=list)
    languages: List[str] = Field(default_factory=list)


class CandidateProfile(BaseModel):
    basics: CandidateBasics = Field(default_factory=CandidateBasics)
    summary: str = ""
    work_experiences: List[WorkExperience] = Field(default_factory=list)
    projects: List[ProjectExperience] = Field(default_factory=list)
    education: List[EducationEntry] = Field(default_factory=list)
    skills: SkillSet = Field(default_factory=SkillSet)
    certifications: List[str] = Field(default_factory=list)

