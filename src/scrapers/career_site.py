"""AI-assisted career site scraper using Claude for job extraction."""

import json
import re
from datetime import datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import structlog
from anthropic import Anthropic

from config.prompts import CAREER_PAGE_EXTRACTION_PROMPT
from config.settings import settings
from src.models import Company, Job, JobSource
from src.scrapers.base import BaseScraper

logger = structlog.get_logger()

# Maximum HTML length to send to Claude (approx 50k chars)
MAX_HTML_LENGTH = 50_000

# Indicators that the page may be blocked
BLOCKING_INDICATORS = [
    "captcha",
    "access denied",
    "please verify",
    "cloudflare",
    "bot detected",
    "unusual traffic",
    "enable javascript",
    "browser check",
]


class CareerSiteScraper(BaseScraper):
    """
    Scrapes job listings from company career pages using AI extraction.

    Uses Playwright to fetch JavaScript-rendered pages, then sends cleaned
    HTML to Claude Haiku for structured job extraction.
    """

    source = JobSource.COMPANY_PAGE
    base_url = ""  # Set per-company

    def __init__(
        self,
        delay_seconds: float = 3.0,
        max_jobs: int = 50,
        max_pagination_pages: int = 2,
        model: str = "claude-haiku-3-5-latest",
    ):
        """
        Initialize the career site scraper.

        Args:
            delay_seconds: Delay between page fetches
            max_jobs: Maximum jobs to extract per company
            max_pagination_pages: Maximum extra pages to follow for pagination
            model: Claude model to use for extraction (default: Haiku for cost)
        """
        super().__init__(
            delay_seconds=delay_seconds,
            max_jobs=max_jobs,
            use_playwright=True,  # Career sites often need JS
        )
        self.max_pagination_pages = max_pagination_pages
        self.model = model
        self._anthropic_client: Optional[Anthropic] = None

    async def __aenter__(self):
        """Initialize Playwright browser and Anthropic client."""
        await super().__aenter__()
        if settings.anthropic_api_key:
            self._anthropic_client = Anthropic(api_key=settings.anthropic_api_key)
        return self

    async def search(
        self,
        keywords: list[str],
        locations: list[str],
    ) -> list[Job]:
        """
        Not used for career site scraping.

        Career sites are scraped by company, not by keyword search.
        Use scrape_company() instead.
        """
        raise NotImplementedError(
            "CareerSiteScraper uses scrape_company() instead of search()"
        )

    async def get_job_details(self, job: Job) -> Job:
        """
        Fetch full details for a job posting.

        For career sites, we typically already have the essential info
        from the listing page, but could fetch more details if needed.
        """
        # For now, return the job as-is
        # Could be extended to fetch individual job pages for descriptions
        return job

    async def scrape_company(self, company: Company) -> list[Job]:
        """
        Scrape jobs from a company's career page.

        Args:
            company: Company object with careers_url

        Returns:
            List of Job objects found on the career page
        """
        if not company.careers_url:
            logger.warning(
                "Company has no careers URL",
                company=company.name,
            )
            return []

        logger.info(
            "Scraping career page",
            company=company.name,
            url=company.careers_url,
        )

        all_jobs = []
        pages_scraped = 0
        current_url = company.careers_url

        while current_url and pages_scraped <= self.max_pagination_pages:
            try:
                # Fetch and extract jobs from this page
                jobs, next_page_url = await self._scrape_page(
                    current_url,
                    company.name,
                )
                all_jobs.extend(jobs)
                pages_scraped += 1

                logger.info(
                    "Extracted jobs from page",
                    company=company.name,
                    page=pages_scraped,
                    jobs_found=len(jobs),
                )

                # Check for pagination
                if next_page_url and pages_scraped < self.max_pagination_pages:
                    await self._delay()
                    current_url = next_page_url
                else:
                    current_url = None

            except Exception as e:
                logger.error(
                    "Failed to scrape career page",
                    company=company.name,
                    url=current_url,
                    error=str(e),
                )
                break

        # Limit total jobs
        all_jobs = all_jobs[: self.max_jobs]

        logger.info(
            "Career page scrape complete",
            company=company.name,
            total_jobs=len(all_jobs),
            pages_scraped=pages_scraped,
        )

        return all_jobs

    async def _scrape_page(
        self,
        url: str,
        company_name: str,
    ) -> tuple[list[Job], Optional[str]]:
        """
        Scrape a single career page.

        Args:
            url: URL of the career page
            company_name: Name of the company

        Returns:
            Tuple of (jobs list, next page URL or None)
        """
        # Fetch the page HTML
        html = await self._fetch_html(url)

        # Check for blocking indicators
        if self._is_blocked(html):
            logger.warning(
                "Career page appears blocked",
                company=company_name,
                url=url,
            )
            return [], None

        # Clean and truncate HTML
        cleaned_html = self._clean_html(html)

        # Extract base URL for resolving relative links
        parsed_url = urlparse(url)
        base_url = f"{parsed_url.scheme}://{parsed_url.netloc}"

        # Send to Claude for extraction
        extraction = await self._extract_jobs_with_ai(
            cleaned_html,
            company_name,
            base_url,
        )

        if not extraction:
            return [], None

        # Check if extraction indicates blocking
        if extraction.get("blocked"):
            logger.warning(
                "AI detected blocked page",
                company=company_name,
                reason=extraction.get("blocked_reason"),
            )
            return [], None

        # Convert extracted jobs to Job objects
        jobs = []
        for job_data in extraction.get("jobs", []):
            try:
                job = self._create_job_from_extraction(
                    job_data,
                    company_name,
                    base_url,
                )
                if job:
                    jobs.append(job)
            except Exception as e:
                logger.warning(
                    "Failed to create job from extraction",
                    error=str(e),
                    job_data=job_data,
                )

        # Get pagination info
        pagination = extraction.get("pagination", {})
        next_page_url = None
        if pagination.get("has_more_pages") and pagination.get("next_page_url"):
            next_page_url = pagination["next_page_url"]
            # Resolve relative URL
            if not next_page_url.startswith("http"):
                next_page_url = urljoin(base_url, next_page_url)

        return jobs, next_page_url

    def _is_blocked(self, html: str) -> bool:
        """Check if the page appears to be blocked."""
        html_lower = html.lower()
        return any(indicator in html_lower for indicator in BLOCKING_INDICATORS)

    def _clean_html(self, html: str) -> str:
        """
        Clean HTML by removing scripts, styles, and unnecessary whitespace.

        Args:
            html: Raw HTML content

        Returns:
            Cleaned and truncated HTML
        """
        # Remove script tags and content
        html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.I)

        # Remove style tags and content
        html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.I)

        # Remove HTML comments
        html = re.sub(r"<!--.*?-->", "", html, flags=re.DOTALL)

        # Remove SVG content (often large and not useful for extraction)
        html = re.sub(r"<svg[^>]*>.*?</svg>", "", html, flags=re.DOTALL | re.I)

        # Remove inline styles
        html = re.sub(r'\s+style="[^"]*"', "", html)

        # Collapse multiple whitespace
        html = re.sub(r"\s+", " ", html)

        # Truncate to max length
        if len(html) > MAX_HTML_LENGTH:
            html = html[:MAX_HTML_LENGTH] + "\n<!-- Content truncated -->"

        return html.strip()

    async def _extract_jobs_with_ai(
        self,
        html: str,
        company_name: str,
        base_url: str,
    ) -> Optional[dict]:
        """
        Send HTML to Claude for job extraction.

        Args:
            html: Cleaned HTML content
            company_name: Name of the company
            base_url: Base URL for resolving relative links

        Returns:
            Extraction result dict or None on failure
        """
        if not self._anthropic_client:
            logger.error("Anthropic client not initialized")
            return None

        prompt = CAREER_PAGE_EXTRACTION_PROMPT.format(
            company_name=company_name,
            base_url=base_url,
            html_content=html,
        )

        try:
            response = self._anthropic_client.messages.create(
                model=self.model,
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}],
            )

            content = response.content[0].text

            # Parse JSON response
            # Handle potential markdown code blocks
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0]
            elif "```" in content:
                content = content.split("```")[1].split("```")[0]

            extraction = json.loads(content.strip())

            logger.debug(
                "AI extraction complete",
                company=company_name,
                jobs_found=len(extraction.get("jobs", [])),
                confidence=extraction.get("extraction_confidence"),
            )

            return extraction

        except json.JSONDecodeError as e:
            logger.error(
                "Failed to parse AI extraction response",
                company=company_name,
                error=str(e),
            )
            return None
        except Exception as e:
            logger.error(
                "AI extraction failed",
                company=company_name,
                error=str(e),
            )
            return None

    def _create_job_from_extraction(
        self,
        job_data: dict,
        company_name: str,
        base_url: str,
    ) -> Optional[Job]:
        """
        Create a Job object from extracted data.

        Args:
            job_data: Dict with job info from AI extraction
            company_name: Company name
            base_url: Base URL for resolving relative links

        Returns:
            Job object or None if invalid
        """
        title = job_data.get("title")
        url = job_data.get("url")

        if not title or not url:
            return None

        # Resolve relative URL
        if not url.startswith("http"):
            url = urljoin(base_url, url)

        location = job_data.get("location") or "Not specified"

        # Parse posted date if available
        posted_date = None
        if job_data.get("posted_date"):
            posted_date = self._parse_date(job_data["posted_date"])

        return Job(
            title=title,
            company=company_name,
            location=location,
            description="",  # Will be fetched separately if needed
            url=url,
            source=JobSource.COMPANY_PAGE,
            posted_date=posted_date,
        )
