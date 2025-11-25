"""Configuration settings for JobHunter AI."""

import os
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Load environment variables from .env file
load_dotenv()

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = PROJECT_ROOT / "src" / "generation" / "templates"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Notion API
    notion_api_key: str = Field(default="", alias="NOTION_API_KEY")
    notion_jobs_db_id: str = Field(default="", alias="NOTION_JOBS_DB_ID")
    notion_companies_db_id: str = Field(default="", alias="NOTION_COMPANIES_DB_ID")
    notion_criteria_db_id: str = Field(default="", alias="NOTION_CRITERIA_DB_ID")
    notion_interview_prep_db_id: str = Field(default="", alias="NOTION_INTERVIEW_PREP_DB_ID")

    # Anthropic Claude API
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    claude_model: str = Field(default="claude-sonnet-4-20250514", alias="CLAUDE_MODEL")

    # Google Drive
    google_drive_credentials: str = Field(default="", alias="GOOGLE_DRIVE_CREDENTIALS")
    google_drive_folder_id: str = Field(default="", alias="GOOGLE_DRIVE_FOLDER_ID")

    # LinkedIn (optional)
    linkedin_email: Optional[str] = Field(default=None, alias="LINKEDIN_EMAIL")
    linkedin_password: Optional[str] = Field(default=None, alias="LINKEDIN_PASSWORD")

    # Scoring thresholds
    min_score_threshold: int = Field(default=60, alias="MIN_SCORE_THRESHOLD")
    strong_match_threshold: int = Field(default=80, alias="STRONG_MATCH_THRESHOLD")

    # Rate limiting
    scrape_delay_seconds: float = Field(default=2.0, alias="SCRAPE_DELAY_SECONDS")
    max_jobs_per_source: int = Field(default=100, alias="MAX_JOBS_PER_SOURCE")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


# Location scoring weights (Paris is primary preference)
LOCATION_SCORES = {
    "Paris": 100,
    "Lyon": 95,
    "France": 90,
    "Remote": 75,
    "London": 80,
    "Switzerland": 70,
    "Zurich": 70,
    "Geneva": 70,
    "Luxembourg": 70,
    "Montreal": 70,
    "Toronto": 70,
    "New York": 70,
    "Boston": 70,
    "San Francisco": 70,
    "Los Angeles": 65,
    "San Diego": 65,
    "Tokyo": 65,
}
DEFAULT_LOCATION_SCORE = 30

# Target role keywords for search
TARGET_ROLE_KEYWORDS = [
    "quantitative analyst",
    "quant analyst",
    "portfolio analyst",
    "data analyst finance",
    "data scientist finance",
    "investment analyst",
    "research analyst",
    "solution architect",
    "technical architect",
    "product manager fintech",
    "software engineer trading",
    "automation engineer",
    "BI developer",
    "quantitative developer",
    "quant developer",
    "python developer finance",
    "fixed income analyst",
    "credit analyst",
    "risk analyst",
]

# Target locations for search
TARGET_LOCATIONS = [
    "Paris",
    "London",
    "Remote",
    "France",
    "Switzerland",
    "Luxembourg",
]

# Skill keywords for matching
SKILL_KEYWORDS = [
    "python",
    "sql",
    "power bi",
    "tableau",
    "data analysis",
    "machine learning",
    "fixed income",
    "portfolio management",
    "performance attribution",
    "financial modeling",
    "quantitative analysis",
    "automation",
    "api",
    "databricks",
    "azure",
    "aws",
    "pandas",
    "numpy",
]


# Create settings instance
settings = Settings()
