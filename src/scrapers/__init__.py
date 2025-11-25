"""Job scrapers for various job boards."""

from src.scrapers.base import BaseScraper
from src.scrapers.indeed import IndeedScraper
from src.scrapers.linkedin import LinkedInScraper
from src.scrapers.wtfj import WelcomeToTheJungleScraper

__all__ = [
    "BaseScraper",
    "IndeedScraper",
    "LinkedInScraper",
    "WelcomeToTheJungleScraper",
]
