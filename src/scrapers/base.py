"""Base scraper class for job boards."""

import asyncio
import random
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import httpx
import structlog
from playwright.async_api import async_playwright, Browser, Page

from src.models import Job, JobSource

logger = structlog.get_logger()


class BaseScraper(ABC):
    """Abstract base class for job scrapers."""

    source: JobSource
    base_url: str

    def __init__(
        self,
        delay_seconds: float = 2.0,
        max_jobs: int = 100,
        use_playwright: bool = False,
    ):
        """
        Initialize the scraper.

        Args:
            delay_seconds: Delay between requests to avoid rate limiting
            max_jobs: Maximum number of jobs to scrape per run
            use_playwright: Whether to use Playwright for JavaScript-rendered pages
        """
        self.delay_seconds = delay_seconds
        self.max_jobs = max_jobs
        self.use_playwright = use_playwright
        self._browser: Optional[Browser] = None
        self._http_client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Async context manager entry."""
        if self.use_playwright:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                ],
            )
        else:
            self._http_client = httpx.AsyncClient(
                headers={
                    "User-Agent": self._get_random_user_agent(),
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    "Accept-Language": "en-GB,en;q=0.9,fr;q=0.8",
                },
                timeout=30.0,
                follow_redirects=True,
            )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if self._browser:
            await self._browser.close()
            await self._playwright.stop()
        if self._http_client:
            await self._http_client.aclose()

    def _get_random_user_agent(self) -> str:
        """Return a random user agent string."""
        user_agents = [
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15",
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
        ]
        return random.choice(user_agents)

    async def _delay(self):
        """Add a random delay between requests."""
        delay = self.delay_seconds + random.uniform(0, 1)
        await asyncio.sleep(delay)

    async def _get_page(self) -> Page:
        """Get a new browser page with stealth settings."""
        if not self._browser:
            raise RuntimeError("Browser not initialized. Use async context manager.")

        page = await self._browser.new_page()

        # Set viewport to look like a real browser
        await page.set_viewport_size({"width": 1920, "height": 1080})

        # Stealth settings to avoid detection
        await page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
            Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
            Object.defineProperty(navigator, 'languages', {get: () => ['en-GB', 'en', 'fr']});
        """)

        return page

    async def _fetch_html(self, url: str) -> str:
        """
        Fetch HTML content from a URL.

        Args:
            url: The URL to fetch

        Returns:
            HTML content as string
        """
        if self.use_playwright:
            page = await self._get_page()
            try:
                await page.goto(url, wait_until="networkidle")
                html = await page.content()
                return html
            finally:
                await page.close()
        else:
            if not self._http_client:
                raise RuntimeError("HTTP client not initialized.")
            response = await self._http_client.get(url)
            response.raise_for_status()
            return response.text

    @abstractmethod
    async def search(
        self,
        keywords: list[str],
        locations: list[str],
    ) -> list[Job]:
        """
        Search for jobs matching the given criteria.

        Args:
            keywords: List of job title keywords to search for
            locations: List of locations to search in

        Returns:
            List of Job objects found
        """
        pass

    @abstractmethod
    async def get_job_details(self, job: Job) -> Job:
        """
        Fetch full details for a job posting.

        Args:
            job: Job object with URL

        Returns:
            Job object with full details populated
        """
        pass

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse a date string into a datetime object.

        Args:
            date_str: Date string to parse

        Returns:
            datetime object or None if parsing fails
        """
        from dateutil import parser

        try:
            return parser.parse(date_str)
        except (ValueError, TypeError):
            return None

    def _clean_text(self, text: str) -> str:
        """
        Clean and normalize text.

        Args:
            text: Raw text to clean

        Returns:
            Cleaned text
        """
        if not text:
            return ""
        # Remove extra whitespace
        import re
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    async def scrape(
        self,
        keywords: list[str],
        locations: list[str],
    ) -> list[Job]:
        """
        Main entry point for scraping jobs.

        Args:
            keywords: List of job title keywords
            locations: List of locations

        Returns:
            List of Job objects with full details
        """
        logger.info(
            "Starting scrape",
            source=self.source.value,
            keywords=keywords,
            locations=locations,
        )

        jobs = await self.search(keywords, locations)
        logger.info(f"Found {len(jobs)} jobs from {self.source.value}")

        # Limit to max_jobs
        jobs = jobs[: self.max_jobs]

        # Fetch full details for each job
        detailed_jobs = []
        for job in jobs:
            try:
                await self._delay()
                detailed_job = await self.get_job_details(job)
                detailed_jobs.append(detailed_job)
                logger.debug(
                    "Fetched job details",
                    title=detailed_job.title,
                    company=detailed_job.company,
                )
            except Exception as e:
                logger.warning(
                    "Failed to fetch job details",
                    job_url=job.url,
                    error=str(e),
                )
                # Still include the job with partial details
                detailed_jobs.append(job)

        logger.info(
            "Scrape complete",
            source=self.source.value,
            jobs_found=len(detailed_jobs),
        )

        return detailed_jobs
