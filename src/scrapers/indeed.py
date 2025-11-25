"""Indeed job scraper."""

import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus, urlencode

import structlog
from bs4 import BeautifulSoup

from src.models import Job, JobSource
from src.scrapers.base import BaseScraper

logger = structlog.get_logger()


class IndeedScraper(BaseScraper):
    """Scraper for Indeed job postings."""

    source = JobSource.INDEED
    base_url = "https://www.indeed.com"

    # Indeed uses different domains for different countries
    DOMAIN_MAP = {
        "Paris": "https://fr.indeed.com",
        "Lyon": "https://fr.indeed.com",
        "France": "https://fr.indeed.com",
        "London": "https://uk.indeed.com",
        "UK": "https://uk.indeed.com",
        "Remote": "https://www.indeed.com",
        "New York": "https://www.indeed.com",
        "San Francisco": "https://www.indeed.com",
        "Boston": "https://www.indeed.com",
        "Los Angeles": "https://www.indeed.com",
        "San Diego": "https://www.indeed.com",
        "Toronto": "https://ca.indeed.com",
        "Montreal": "https://ca.indeed.com",
        "Switzerland": "https://ch.indeed.com",
        "Zurich": "https://ch.indeed.com",
        "Geneva": "https://ch.indeed.com",
        "Luxembourg": "https://lu.indeed.com",
        "Tokyo": "https://jp.indeed.com",
    }

    def __init__(self, **kwargs):
        """Initialize Indeed scraper with Playwright for JS rendering."""
        super().__init__(use_playwright=True, **kwargs)

    def _get_domain_for_location(self, location: str) -> str:
        """Get the appropriate Indeed domain for a location."""
        for key, domain in self.DOMAIN_MAP.items():
            if key.lower() in location.lower():
                return domain
        return "https://www.indeed.com"

    def _build_search_url(
        self,
        keyword: str,
        location: str,
        start: int = 0,
    ) -> str:
        """
        Build Indeed search URL.

        Args:
            keyword: Job title keyword
            location: Location to search
            start: Pagination offset

        Returns:
            Search URL
        """
        domain = self._get_domain_for_location(location)

        params = {
            "q": keyword,
            "l": location,
            "sort": "date",  # Sort by date to get newest first
            "fromage": "7",  # Last 7 days
            "start": start,
        }

        return f"{domain}/jobs?{urlencode(params)}"

    async def search(
        self,
        keywords: list[str],
        locations: list[str],
    ) -> list[Job]:
        """
        Search Indeed for jobs.

        Args:
            keywords: List of job title keywords
            locations: List of locations

        Returns:
            List of Job objects
        """
        jobs = []
        seen_urls = set()

        for location in locations:
            for keyword in keywords:
                try:
                    url = self._build_search_url(keyword, location)
                    logger.info(
                        "Searching Indeed",
                        keyword=keyword,
                        location=location,
                        url=url,
                    )

                    html = await self._fetch_html(url)
                    page_jobs = self._parse_search_results(html, location)

                    # Deduplicate
                    for job in page_jobs:
                        if job.url not in seen_urls:
                            seen_urls.add(job.url)
                            jobs.append(job)

                    await self._delay()

                    # Stop if we have enough jobs
                    if len(jobs) >= self.max_jobs:
                        break

                except Exception as e:
                    logger.error(
                        "Indeed search failed",
                        keyword=keyword,
                        location=location,
                        error=str(e),
                    )

            if len(jobs) >= self.max_jobs:
                break

        return jobs

    def _parse_search_results(self, html: str, location: str) -> list[Job]:
        """
        Parse Indeed search results HTML.

        Args:
            html: Raw HTML content
            location: Location searched

        Returns:
            List of Job objects
        """
        jobs = []
        soup = BeautifulSoup(html, "lxml")

        # Indeed uses various selectors for job cards
        job_cards = soup.select("div.job_seen_beacon") or soup.select("div.jobsearch-ResultsList > div")

        for card in job_cards:
            try:
                job = self._parse_job_card(card, location)
                if job:
                    jobs.append(job)
            except Exception as e:
                logger.debug(f"Failed to parse job card: {e}")
                continue

        return jobs

    def _parse_job_card(self, card, location: str) -> Optional[Job]:
        """
        Parse a single job card from search results.

        Args:
            card: BeautifulSoup element for job card
            location: Location searched

        Returns:
            Job object or None
        """
        # Extract job title
        title_elem = card.select_one("h2.jobTitle a") or card.select_one("a[data-jk]")
        if not title_elem:
            return None

        title = self._clean_text(title_elem.get_text())

        # Extract job URL
        job_key = title_elem.get("data-jk") or title_elem.get("href", "").split("jk=")[-1].split("&")[0]
        if not job_key:
            href = title_elem.get("href", "")
            if href:
                job_url = href if href.startswith("http") else f"{self.base_url}{href}"
            else:
                return None
        else:
            domain = self._get_domain_for_location(location)
            job_url = f"{domain}/viewjob?jk={job_key}"

        # Extract company name
        company_elem = card.select_one("span[data-testid='company-name']") or card.select_one("span.companyName")
        company = self._clean_text(company_elem.get_text()) if company_elem else "Unknown"

        # Extract location
        location_elem = card.select_one("div[data-testid='text-location']") or card.select_one("div.companyLocation")
        job_location = self._clean_text(location_elem.get_text()) if location_elem else location

        # Extract salary if available
        salary_elem = card.select_one("div.salary-snippet-container") or card.select_one("div.metadata.salary-snippet-container")
        salary = self._clean_text(salary_elem.get_text()) if salary_elem else None

        # Extract posted date
        date_elem = card.select_one("span.date") or card.select_one("span[data-testid='myJobsStateDate']")
        posted_date = self._parse_relative_date(date_elem.get_text()) if date_elem else None

        # Extract snippet/description
        snippet_elem = card.select_one("div.job-snippet") or card.select_one("div[class*='job-snippet']")
        description = self._clean_text(snippet_elem.get_text()) if snippet_elem else ""

        return Job(
            title=title,
            company=company,
            location=job_location,
            description=description,
            url=job_url,
            source=self.source,
            salary=salary,
            posted_date=posted_date,
        )

    def _parse_relative_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse relative date strings like 'Posted 3 days ago'.

        Args:
            date_str: Relative date string

        Returns:
            datetime object or None
        """
        if not date_str:
            return None

        date_str = date_str.lower().strip()
        now = datetime.now()

        # Handle "just posted" or "today"
        if "just" in date_str or "today" in date_str:
            return now

        # Handle "X days ago"
        days_match = re.search(r"(\d+)\s*day", date_str)
        if days_match:
            days = int(days_match.group(1))
            return now - timedelta(days=days)

        # Handle "X hours ago"
        hours_match = re.search(r"(\d+)\s*hour", date_str)
        if hours_match:
            hours = int(hours_match.group(1))
            return now - timedelta(hours=hours)

        # Handle "30+ days ago"
        if "30+" in date_str or "month" in date_str:
            return now - timedelta(days=30)

        return None

    async def get_job_details(self, job: Job) -> Job:
        """
        Fetch full job details from Indeed.

        Args:
            job: Job object with URL

        Returns:
            Job object with full details
        """
        try:
            html = await self._fetch_html(job.url)
            soup = BeautifulSoup(html, "lxml")

            # Extract full job description
            desc_elem = soup.select_one("div#jobDescriptionText") or soup.select_one("div.jobsearch-jobDescriptionText")
            if desc_elem:
                job.description = self._clean_text(desc_elem.get_text(separator="\n"))

            # Try to get more detailed salary info
            salary_elem = soup.select_one("div#salaryInfoAndJobType") or soup.select_one("span.icl-u-xs-mr--xs")
            if salary_elem and not job.salary:
                job.salary = self._clean_text(salary_elem.get_text())

            # Get job type if available
            job_type_elem = soup.select_one("div[data-testid='jobsearch-JobInfoHeader-jobType']")
            if job_type_elem:
                job_type = self._clean_text(job_type_elem.get_text())
                if job_type and job_type not in job.description:
                    job.description = f"Job Type: {job_type}\n\n{job.description}"

        except Exception as e:
            logger.warning(
                "Failed to fetch Indeed job details",
                url=job.url,
                error=str(e),
            )

        return job
