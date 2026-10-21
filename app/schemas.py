"""Data shapes shared by the AI pipeline, the editor and the renderer."""
from typing import List

from pydantic import BaseModel, Field


class Header(BaseModel):
    name: str
    headline: str
    email: str
    phone: str
    linkedin: str
    location: str


class Education(BaseModel):
    degree: str
    institution: str
    dates: str
    grade: str = Field(description="CGPA or percentage if stated, else empty string")


# ---------- Step 1: fact bank built from the customer's resumes ----------

class Fact(BaseModel):
    id: str = Field(description="Short unique id such as F12")
    text: str = Field(description="One achievement or responsibility, wording and numbers kept exactly as in the source")


class Role(BaseModel):
    company: str
    location: str
    title: str
    start: str
    end: str
    company_context: str = Field(description="One line on what the company does, only if stated in a resume, else empty")
    facts: List[Fact]


class Profile(BaseModel):
    header: Header
    total_experience: str = Field(description="For example '8 years', computed from role dates")
    roles: List[Role] = Field(description="Most recent first; the same job from different resumes merged into one role")
    education: List[Education]
    certifications: List[str]
    awards: List[str]
    skills: List[str] = Field(description="Every skill, tool and domain the resumes mention")
    other_facts: List[Fact] = Field(description="Projects, publications, volunteering and anything else worth keeping")
    conflicts: List[str] = Field(description="Places where resumes disagree, such as different dates for the same job")


# ---------- Step 2 and 3: tailored resume ----------

class Bullet(BaseModel):
    text: str
    sources: List[str] = Field(description="Fact ids this bullet is based on")


class DraftJob(BaseModel):
    company: str
    location: str
    title: str
    dates: str
    context: str
    bullets: List[Bullet]


class Draft(BaseModel):
    target_role: str
    must_have_keywords: List[str]
    header: Header
    summary: str
    competencies: List[str]
    experience: List[DraftJob]
    education: List[Education]
    certifications: List[str]
    achievements: List[str]
    gap_notes: List[str] = Field(description="Job requirements the resumes give no evidence for, phrased as advice to the customer")


class Job(BaseModel):
    company: str
    location: str
    title: str
    dates: str
    context: str
    bullets: List[str]


class Resume(BaseModel):
    header: Header
    summary: str
    competencies: List[str]
    experience: List[Job]
    education: List[Education]
    certifications: List[str]
    achievements: List[str]


class Verified(BaseModel):
    resume: Resume
    corrections: List[str] = Field(description="Each change made during the check and why")
    gap_notes: List[str]
    keyword_coverage: List[str] = Field(description="Must-have keywords that now appear in the resume")


class CoverLetter(BaseModel):
    greeting: str = Field(description="For example 'Dear Hiring Manager,' or 'Dear Hiring Team at <Company>,'")
    paragraphs: List[str] = Field(description="3 or 4 paragraphs, plain text")
    closing: str = Field(description="For example 'Sincerely,'")
