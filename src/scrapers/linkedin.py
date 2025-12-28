"""LinkedIn job scraper."""

import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus, urlencode

import structlog
from bs4 import BeautifulSoup

from src.models import Job, JobSource
from src.scrapers.base import BaseScraper

logger = structlog.get_logger()


class LinkedInScraper(BaseScraper):
    """Scraper for LinkedIn job postings (public/guest access)."""

    source = JobSource.LINKEDIN
    base_url = "https://www.linkedin.com"

    # LinkedIn location IDs (geoId)
    LOCATION_IDS = {
        "Paris": "105015875",
        "France": "105015875",
        "Lyon": "105015875",
        "London": "102257491",
        "UK": "101165590",
        "United Kingdom": "101165590",
        "Remote": "",  # Use f_WT=2 for remote filter
        "New York": "102571732",
        "San Francisco": "102277331",
        "Boston": "102380872",
        "Los Angeles": "102448103",
        "San Diego": "103806194",
        "Toronto": "100025096",
        "Montreal": "103366113",
        "Switzerland": "106693272",
        "Zurich": "106693272",
        "Geneva": "106693272",
        "Luxembourg": "104042105",
        "Tokyo": "102257019",
    }

    def __init__(self, **kwargs):
        """Initialize LinkedIn scraper with Playwright for JS rendering."""
        super().__init__(use_playwright=True, **kwargs)

    def _build_search_url(
        self,
        keyword: str,
        location: str,
        start: int = 0,
    ) -> str:
        """
        Build LinkedIn job search URL.

        Args:
            keyword: Job title keyword
            location: Location to search
            start: Pagination offset

        Returns:
            Search URL
        """
        params = {
            "keywords": keyword,
            "location": location,
            "sortBy": "DD",  # Sort by date
            "f_TPR": "r604800",  # Past week
            "start": start,
        }

        # Add geoId if we have it
        geo_id = self._get_geo_id(location)
        if geo_id:
            params["geoId"] = geo_id

        # Handle remote filter
        if location.lower() == "remote":
            params["f_WT"] = "2"  # Remote filter

        return f"{self.base_url}/jobs/search?{urlencode(params)}"

    def _get_geo_id(self, location: str) -> Optional[str]:
        """Get LinkedIn geoId for a location."""
        for key, geo_id in self.LOCATION_IDS.items():
            if key.lower() in location.lower():
                return geo_id
        return None

    async def search(
        self,
        keywords: list[str],
        locations: list[str],
    ) -> list[Job]:
        """
        Search LinkedIn for jobs.

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
                        "Searching LinkedIn",
                        keyword=keyword,
                        location=location,
                        url=url,
                    )

                    html = await self._fetch_html(url)
                    page_jobs = self._parse_search_results(html, location)

                    # Deduplicate by URL
                    for job in page_jobs:
                        if job.url not in seen_urls:
                            seen_urls.add(job.url)
                            jobs.append(job)

                    await self._delay()

                    if len(jobs) >= self.max_jobs:
                        break

                except Exception as e:
                    logger.error(
                        "LinkedIn search failed",
                        keyword=keyword,
                        location=location,
                        error=str(e),
                    )

            if len(jobs) >= self.max_jobs:
                break

        return jobs

    def _parse_search_results(self, html: str, location: str) -> list[Job]:
        """
        Parse LinkedIn search results HTML.

        Args:
            html: Raw HTML content
            location: Location searched

        Returns:
            List of Job objects
        """
        jobs = []
        soup = BeautifulSoup(html, "lxml")

        # LinkedIn job cards
        job_cards = soup.select("div.base-card") or soup.select("li.jobs-search-results__list-item")

        for card in job_cards:
            try:
                job = self._parse_job_card(card, location)
                if job:
                    jobs.append(job)
            except Exception as e:
                logger.debug(f"Failed to parse LinkedIn job card: {e}")
                continue

        return jobs

    def _parse_job_card(self, card, location: str) -> Optional[Job]:
        """
        Parse a single job card from search results.

        Args:
            card: BeautifulSoup element
            location: Location searched

        Returns:
            Job object or None
        """
        # Extract job title
        title_elem = card.select_one("h3.base-search-card__title") or card.select_one("a.job-card-list__title")
        if not title_elem:
            return None

        title = self._clean_text(title_elem.get_text())

        # Extract job URL
        link_elem = card.select_one("a.base-card__full-link") or card.select_one("a.job-card-container__link")
        if not link_elem:
            return None

        job_url = link_elem.get("href", "")
        if not job_url:
            return None

        # Clean up URL (remove tracking params)
        job_url = job_url.split("?")[0]
        if not job_url.startswith("http"):
            job_url = f"{self.base_url}{job_url}"

        # Extract company name
        company_elem = card.select_one("h4.base-search-card__subtitle") or card.select_one("a.job-card-container__company-name")
        company = self._clean_text(company_elem.get_text()) if company_elem else "Unknown"

        # Extract location
        location_elem = card.select_one("span.job-search-card__location") or card.select_one("li.job-card-container__metadata-item")
        job_location = self._clean_text(location_elem.get_text()) if location_elem else location

        # Extract posted date
        date_elem = card.select_one("time.job-search-card__listdate") or card.select_one("time")
        posted_date = None
        if date_elem:
            datetime_attr = date_elem.get("datetime")
            if datetime_attr:
                posted_date = self._parse_date(datetime_attr)
            else:
                posted_date = self._parse_relative_date(date_elem.get_text())

        # LinkedIn doesn't show salary in search results typically
        # Check for salary info if present
        salary = None
        salary_elem = card.select_one("span.job-search-card__salary-info")
        if salary_elem:
            salary = self._clean_text(salary_elem.get_text())

        return Job(
            title=title,
            company=company,
            location=job_location,
            description="",  # Will be filled in get_job_details
            url=job_url,
            source=self.source,
            salary=salary,
            posted_date=posted_date,
        )

    def _parse_relative_date(self, date_str: str) -> Optional[datetime]:
        """Parse relative date strings like '2 weeks ago'."""
        if not date_str:
            return None

        date_str = date_str.lower().strip()
        now = datetime.now()

        if "just now" in date_str or "today" in date_str:
            return now

        # Extract number and unit
        match = re.search(r"(\d+)\s*(minute|hour|day|week|month)", date_str)
        if match:
            num = int(match.group(1))
            unit = match.group(2)

            if "minute" in unit:
                return now - timedelta(minutes=num)
            elif "hour" in unit:
                return now - timedelta(hours=num)
            elif "day" in unit:
                return now - timedelta(days=num)
            elif "week" in unit:
                return now - timedelta(weeks=num)
            elif "month" in unit:
                return now - timedelta(days=num * 30)

        return None

    async def get_job_details(self, job: Job) -> Job:
        """
        Fetch full job details from LinkedIn.

        Args:
            job: Job object with URL

        Returns:
            Job object with full details
        """
        try:
            html = await self._fetch_html(job.url)
            soup = BeautifulSoup(html, "lxml")

            # Extract full job description
            desc_selectors = [
                "div.show-more-less-html__markup",
                "div.description__text",
                "section.description",
                "div.job-description",
            ]

            for selector in desc_selectors:
                desc_elem = soup.select_one(selector)
                if desc_elem:
                    job.description = self._clean_text(desc_elem.get_text(separator="\n"))
                    break

            # Try to get criteria (employment type, seniority, etc.)
            criteria_items = soup.select("li.description__job-criteria-item")
            criteria_text = []
            for item in criteria_items:
                header = item.select_one("h3")
                value = item.select_one("span")
                if header and value:
                    criteria_text.append(
                        f"{self._clean_text(header.get_text())}: {self._clean_text(value.get_text())}"
                    )

            if criteria_text:
                job.description = "\n".join(criteria_text) + "\n\n" + job.description

            # Extract salary if shown
            salary_elem = soup.select_one("div.salary-main-rail__content")
            if salary_elem and not job.salary:
                job.salary = self._clean_text(salary_elem.get_text())

        except Exception as e:
            logger.warning(
                "Failed to fetch LinkedIn job details, using listing data only",
                url=job.url,
                error=str(e),
            )
            # Job will still be returned with listing data (title, company, location)
            # Description will be empty but job can still be reviewed

        return job
