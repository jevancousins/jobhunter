"""Welcome to the Jungle (WTFJ) job scraper."""

import re
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import quote_plus, urlencode

import structlog
from bs4 import BeautifulSoup

from src.models import Job, JobSource
from src.scrapers.base import BaseScraper

logger = structlog.get_logger()


class WelcomeToTheJungleScraper(BaseScraper):
    """Scraper for Welcome to the Jungle job postings (France-focused)."""

    source = JobSource.WTFJ
    base_url = "https://www.welcometothejungle.com"

    # WTFJ uses different URL paths for different languages
    LANGUAGE_PATHS = {
        "fr": "/fr",
        "en": "/en",
    }

    def __init__(self, language: str = "en", **kwargs):
        """
        Initialize WTFJ scraper.

        Args:
            language: Language for job listings ('en' or 'fr')
        """
        super().__init__(use_playwright=True, **kwargs)
        self.language = language
        self.lang_path = self.LANGUAGE_PATHS.get(language, "/en")

    def _build_search_url(
        self,
        keyword: str,
        location: str,
        page: int = 1,
    ) -> str:
        """
        Build WTFJ search URL.

        Args:
            keyword: Job title keyword
            location: Location/city
            page: Page number

        Returns:
            Search URL
        """
        # WTFJ has a specific URL structure
        # https://www.welcometothejungle.com/en/jobs?query=data%20analyst&refinementList%5Boffices.city%5D%5B%5D=Paris

        params = {
            "query": keyword,
            "page": page,
        }

        # Map locations to WTFJ city format
        city_param = self._get_city_param(location)
        if city_param:
            params["refinementList[offices.city][]"] = city_param

        # Add remote filter if needed
        if location.lower() == "remote":
            params["refinementList[remote][]"] = "fulltime"

        return f"{self.base_url}{self.lang_path}/jobs?{urlencode(params, safe='[]')}"

    def _get_city_param(self, location: str) -> Optional[str]:
        """Map location to WTFJ city parameter."""
        location_lower = location.lower()

        # Direct city mappings
        city_map = {
            "paris": "Paris",
            "lyon": "Lyon",
            "london": "London",
            "bordeaux": "Bordeaux",
            "marseille": "Marseille",
            "lille": "Lille",
            "nantes": "Nantes",
            "toulouse": "Toulouse",
        }

        for key, value in city_map.items():
            if key in location_lower:
                return value

        # For France-wide, return None (no city filter)
        if "france" in location_lower:
            return None

        return location.title()

    async def search(
        self,
        keywords: list[str],
        locations: list[str],
    ) -> list[Job]:
        """
        Search WTFJ for jobs.

        Args:
            keywords: List of job title keywords
            locations: List of locations

        Returns:
            List of Job objects
        """
        jobs = []
        seen_urls = set()

        # WTFJ is France-focused, prioritize French locations
        french_locations = [loc for loc in locations if self._is_french_location(loc)]
        if not french_locations:
            french_locations = ["Paris", "Remote"]

        for location in french_locations:
            for keyword in keywords:
                try:
                    url = self._build_search_url(keyword, location)
                    logger.info(
                        "Searching WTFJ",
                        keyword=keyword,
                        location=location,
                        url=url,
                    )

                    html = await self._fetch_html(url)
                    page_jobs = self._parse_search_results(html, location)

                    for job in page_jobs:
                        if job.url not in seen_urls:
                            seen_urls.add(job.url)
                            jobs.append(job)

                    await self._delay()

                    if len(jobs) >= self.max_jobs:
                        break

                except Exception as e:
                    logger.error(
                        "WTFJ search failed",
                        keyword=keyword,
                        location=location,
                        error=str(e),
                    )

            if len(jobs) >= self.max_jobs:
                break

        return jobs

    def _is_french_location(self, location: str) -> bool:
        """Check if location is in France."""
        french_cities = [
            "paris", "lyon", "marseille", "bordeaux", "lille",
            "nantes", "toulouse", "nice", "strasbourg", "montpellier",
            "france", "remote"
        ]
        return any(city in location.lower() for city in french_cities)

    def _parse_search_results(self, html: str, location: str) -> list[Job]:
        """
        Parse WTFJ search results HTML.

        Args:
            html: Raw HTML content
            location: Location searched

        Returns:
            List of Job objects
        """
        jobs = []
        soup = BeautifulSoup(html, "lxml")

        # WTFJ job cards
        job_cards = soup.select("article[data-testid='search-results-list-item-wrapper']") or \
                   soup.select("div[data-testid='job-card']") or \
                   soup.select("li.ais-Hits-item")

        for card in job_cards:
            try:
                job = self._parse_job_card(card, location)
                if job:
                    jobs.append(job)
            except Exception as e:
                logger.debug(f"Failed to parse WTFJ job card: {e}")
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
        # Extract job title and URL
        link_elem = card.select_one("a[href*='/jobs/']") or card.select_one("a.sc-")
        if not link_elem:
            return None

        job_url = link_elem.get("href", "")
        if not job_url:
            return None

        if not job_url.startswith("http"):
            job_url = f"{self.base_url}{job_url}"

        # Extract title
        title_elem = card.select_one("h4") or card.select_one("span[role='heading']") or link_elem
        title = self._clean_text(title_elem.get_text()) if title_elem else ""

        if not title:
            return None

        # Extract company name
        company_elem = card.select_one("span[data-testid='job-card-company-name']") or \
                      card.select_one("a[href*='/companies/'] span")
        company = self._clean_text(company_elem.get_text()) if company_elem else "Unknown"

        # Extract location from card
        location_elem = card.select_one("span[data-testid='job-card-location']") or \
                       card.select_one("i.fa-map-marker-alt")
        if location_elem:
            # Get parent or sibling text for location
            parent = location_elem.parent
            job_location = self._clean_text(parent.get_text()) if parent else location
        else:
            job_location = location

        # Extract contract type if available
        contract_elem = card.select_one("span[data-testid='job-card-contract-type']")
        contract_type = self._clean_text(contract_elem.get_text()) if contract_elem else None

        # WTFJ shows dates like "Publiée il y a 2 jours" or "Published 2 days ago"
        date_elem = card.select_one("time") or card.select_one("span[data-testid='job-card-published-date']")
        posted_date = None
        if date_elem:
            datetime_attr = date_elem.get("datetime")
            if datetime_attr:
                posted_date = self._parse_date(datetime_attr)
            else:
                posted_date = self._parse_relative_date(date_elem.get_text())

        # Build initial description from available info
        description_parts = []
        if contract_type:
            description_parts.append(f"Contract: {contract_type}")

        return Job(
            title=title,
            company=company,
            location=job_location,
            description="\n".join(description_parts),
            url=job_url,
            source=self.source,
            posted_date=posted_date,
        )

    def _parse_relative_date(self, date_str: str) -> Optional[datetime]:
        """Parse relative date strings in English or French."""
        if not date_str:
            return None

        date_str = date_str.lower().strip()
        now = datetime.now()

        # French patterns
        if "aujourd'hui" in date_str or "today" in date_str:
            return now

        if "hier" in date_str or "yesterday" in date_str:
            return now - timedelta(days=1)

        # "il y a X jours" or "X days ago"
        match = re.search(r"(\d+)\s*(jour|day|semaine|week|mois|month|heure|hour)", date_str)
        if match:
            num = int(match.group(1))
            unit = match.group(2)

            if "jour" in unit or "day" in unit:
                return now - timedelta(days=num)
            elif "semaine" in unit or "week" in unit:
                return now - timedelta(weeks=num)
            elif "mois" in unit or "month" in unit:
                return now - timedelta(days=num * 30)
            elif "heure" in unit or "hour" in unit:
                return now - timedelta(hours=num)

        return None

    async def get_job_details(self, job: Job) -> Job:
        """
        Fetch full job details from WTFJ.

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
                "div[data-testid='job-section-description']",
                "div.sc-job-description",
                "section.job-description",
                "div[class*='JobDescription']",
            ]

            description_parts = [job.description] if job.description else []

            for selector in desc_selectors:
                desc_elem = soup.select_one(selector)
                if desc_elem:
                    description_parts.append(self._clean_text(desc_elem.get_text(separator="\n")))
                    break

            # Extract profile/requirements section
            profile_elem = soup.select_one("div[data-testid='job-section-profile']")
            if profile_elem:
                description_parts.append("\n\nRequired Profile:\n" + self._clean_text(profile_elem.get_text(separator="\n")))

            # Extract benefits if available
            benefits_elem = soup.select_one("div[data-testid='job-section-benefits']")
            if benefits_elem:
                description_parts.append("\n\nBenefits:\n" + self._clean_text(benefits_elem.get_text(separator="\n")))

            job.description = "\n".join(description_parts)

            # Try to get salary
            salary_elem = soup.select_one("span[data-testid='job-salary']") or \
                         soup.select_one("div[class*='salary']")
            if salary_elem and not job.salary:
                job.salary = self._clean_text(salary_elem.get_text())

            # Get company info
            company_elem = soup.select_one("a[data-testid='job-company-link']")
            if company_elem:
                company_name = self._clean_text(company_elem.get_text())
                if company_name and job.company == "Unknown":
                    job.company = company_name

        except Exception as e:
            logger.warning(
                "Failed to fetch WTFJ job details",
                url=job.url,
                error=str(e),
            )

        return job
