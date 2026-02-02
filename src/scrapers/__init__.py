"""Job scrapers for various job boards."""

from src.scrapers.base import BaseScraper
from src.scrapers.career_site import CareerSiteScraper
from src.scrapers.indeed import IndeedScraper
from src.scrapers.linkedin import LinkedInScraper
from src.scrapers.wtfj import WelcomeToTheJungleScraper

__all__ = [
    "BaseScraper",
    "CareerSiteScraper",
    "IndeedScraper",
    "LinkedInScraper",
    "WelcomeToTheJungleScraper",
]
