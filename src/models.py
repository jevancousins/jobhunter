"""Data models for JobHunter AI."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class JobStatus(Enum):
    """Status of a job in the pipeline."""
    NEW = "New"
    REVIEWING = "Reviewing"
    APPLY = "Apply"
    APPLIED = "Applied"
    INTERVIEW = "Interview"
    OFFER = "Offer"
    REJECTED = "Rejected"
    PASS = "Pass"


class JobSource(Enum):
    """Source where the job was discovered."""
    LINKEDIN = "LinkedIn"
    INDEED = "Indeed"
    WTFJ = "Welcome to the Jungle"
    COMPANY_PAGE = "Company Page"
    GLASSDOOR = "Glassdoor"


@dataclass
class ScoreBreakdown:
    """Breakdown of job suitability score by factor."""
    location: float = 0.0  # 0-25
    role_alignment: float = 0.0  # 0-25
    industry_fit: float = 0.0  # 0-15
    seniority: float = 0.0  # 0-10
    skills_match: float = 0.0  # 0-15
    impact_potential: float = 0.0  # 0-10

    @property
    def total(self) -> float:
        """Calculate total score from all factors."""
        return (
            self.location
            + self.role_alignment
            + self.industry_fit
            + self.seniority
            + self.skills_match
            + self.impact_potential
        )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "location": self.location,
            "role_alignment": self.role_alignment,
            "industry_fit": self.industry_fit,
            "seniority": self.seniority,
            "skills_match": self.skills_match,
            "impact_potential": self.impact_potential,
            "total": self.total,
        }


@dataclass
class Job:
    """Represents a job posting."""
    title: str
    company: str
    location: str
    description: str
    url: str
    source: JobSource

    # Optional fields
    id: str = ""
    posted_date: Optional[datetime] = None
    discovered_date: datetime = field(default_factory=datetime.now)
    salary: Optional[str] = None

    # Scoring (populated after AI analysis)
    score: float = 0.0
    score_breakdown: Optional[ScoreBreakdown] = None
    ai_analysis: str = ""
    key_requirements: list[str] = field(default_factory=list)
    potential_concerns: list[str] = field(default_factory=list)

    # Application tracking
    status: JobStatus = JobStatus.NEW
    tailored_cv_url: Optional[str] = None
    cover_letter_url: Optional[str] = None
    notes: Optional[str] = None

    # Notion integration
    notion_page_id: Optional[str] = None

    def __post_init__(self):
        """Generate ID if not provided."""
        if not self.id:
            # Create a unique ID from company, title, and URL hash
            import hashlib
            hash_input = f"{self.company}_{self.title}_{self.url}"
            self.id = hashlib.md5(hash_input.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        """Convert to dictionary for serialization."""
        return {
            "id": self.id,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "description": self.description,
            "url": self.url,
            "source": self.source.value,
            "posted_date": self.posted_date.isoformat() if self.posted_date else None,
            "discovered_date": self.discovered_date.isoformat(),
            "salary": self.salary,
            "score": self.score,
            "score_breakdown": self.score_breakdown.to_dict() if self.score_breakdown else None,
            "ai_analysis": self.ai_analysis,
            "key_requirements": self.key_requirements,
            "potential_concerns": self.potential_concerns,
            "status": self.status.value,
            "tailored_cv_url": self.tailored_cv_url,
            "cover_letter_url": self.cover_letter_url,
            "notes": self.notes,
            "notion_page_id": self.notion_page_id,
        }


@dataclass
class SearchCriteria:
    """Search criteria for job discovery."""
    name: str
    keywords: list[str]
    locations: list[str]
    active: bool = True
    min_score: int = 60
    excluded_companies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "keywords": self.keywords,
            "locations": self.locations,
            "active": self.active,
            "min_score": self.min_score,
            "excluded_companies": self.excluded_companies,
        }


@dataclass
class Company:
    """A company in the watchlist."""
    name: str
    careers_url: str
    priority: str = "Medium"  # High, Medium, Low
    locations: list[str] = field(default_factory=list)
    check_daily: bool = True
    last_checked: Optional[datetime] = None
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "name": self.name,
            "careers_url": self.careers_url,
            "priority": self.priority,
            "locations": self.locations,
            "check_daily": self.check_daily,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
            "notes": self.notes,
        }
