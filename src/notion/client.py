"""Notion API client wrapper."""

import json
from datetime import datetime
from typing import Any, Optional

import structlog
from notion_client import Client
from tenacity import retry, stop_after_attempt, wait_exponential

from config.settings import settings
from src.models import Job, JobStatus, JobSource, Company, SearchCriteria

logger = structlog.get_logger()


class NotionClient:
    """Wrapper for Notion API operations."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        jobs_db_id: Optional[str] = None,
        companies_db_id: Optional[str] = None,
        criteria_db_id: Optional[str] = None,
        interview_prep_db_id: Optional[str] = None,
    ):
        """
        Initialize Notion client.

        Args:
            api_key: Notion API key
            jobs_db_id: Jobs database ID
            companies_db_id: Companies watchlist database ID
            criteria_db_id: Search criteria database ID
            interview_prep_db_id: Interview prep database ID
        """
        self.api_key = api_key or settings.notion_api_key
        self.jobs_db_id = jobs_db_id or settings.notion_jobs_db_id
        self.companies_db_id = companies_db_id or settings.notion_companies_db_id
        self.criteria_db_id = criteria_db_id or settings.notion_criteria_db_id
        self.interview_prep_db_id = interview_prep_db_id or settings.notion_interview_prep_db_id

        self.client = Client(auth=self.api_key)

    # ==================== Jobs Database ====================

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def create_job(self, job: Job) -> str:
        """
        Create a job entry in Notion.

        Args:
            job: Job object to create

        Returns:
            Notion page ID of created job
        """
        properties = self._job_to_properties(job)

        response = self.client.pages.create(
            parent={"database_id": self.jobs_db_id},
            properties=properties,
        )

        page_id = response["id"]
        logger.info(
            "Created job in Notion",
            title=job.title,
            company=job.company,
            page_id=page_id,
        )

        return page_id

    def _job_to_properties(self, job: Job) -> dict[str, Any]:
        """Convert Job object to Notion properties."""
        properties = {
            "Title": {"title": [{"text": {"content": job.title}}]},
            "Company": {"select": {"name": job.company}},
            "Location": {"select": {"name": job.location}},
            "Score": {"number": job.score},
            "Status": {"select": {"name": job.status.value}},
            "Source": {"select": {"name": job.source.value}},
            "URL": {"url": job.url},
            "Discovered Date": {"date": {"start": job.discovered_date.isoformat()}},
        }

        # Optional fields
        if job.posted_date:
            properties["Posted Date"] = {"date": {"start": job.posted_date.isoformat()}}

        if job.salary:
            properties["Salary"] = {"rich_text": [{"text": {"content": job.salary}}]}

        if job.score_breakdown:
            properties["Score Breakdown"] = {
                "rich_text": [{"text": {"content": json.dumps(job.score_breakdown.to_dict())}}]
            }

        if job.ai_analysis:
            properties["AI Analysis"] = {
                "rich_text": [{"text": {"content": job.ai_analysis[:2000]}}]  # Notion limit
            }

        if job.tailored_cv_url:
            properties["Tailored CV"] = {"url": job.tailored_cv_url}

        if job.cover_letter_url:
            properties["Cover Letter"] = {"url": job.cover_letter_url}

        if job.notes:
            properties["Notes"] = {"rich_text": [{"text": {"content": job.notes}}]}

        return properties

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    def update_job(self, page_id: str, job: Job) -> None:
        """
        Update an existing job in Notion.

        Args:
            page_id: Notion page ID
            job: Job object with updated data
        """
        properties = self._job_to_properties(job)

        self.client.pages.update(
            page_id=page_id,
            properties=properties,
        )

        logger.info(
            "Updated job in Notion",
            title=job.title,
            page_id=page_id,
        )

    def get_job_by_url(self, url: str) -> Optional[dict]:
        """
        Check if a job with this URL already exists.

        Args:
            url: Job URL to search for

        Returns:
            Notion page data if found, None otherwise
        """
        response = self.client.databases.query(
            database_id=self.jobs_db_id,
            filter={"property": "URL", "url": {"equals": url}},
        )

        if response["results"]:
            return response["results"][0]
        return None

    def job_exists(self, url: str) -> bool:
        """Check if a job with this URL already exists."""
        return self.get_job_by_url(url) is not None

    def get_jobs_by_status(self, status: JobStatus) -> list[dict]:
        """
        Get all jobs with a specific status.

        Args:
            status: Job status to filter by

        Returns:
            List of Notion page data
        """
        response = self.client.databases.query(
            database_id=self.jobs_db_id,
            filter={"property": "Status", "select": {"equals": status.value}},
        )

        return response["results"]

    def get_jobs_to_apply(self) -> list[dict]:
        """Get jobs with status 'Apply'."""
        return self.get_jobs_by_status(JobStatus.APPLY)

    def get_jobs_for_interview(self) -> list[dict]:
        """Get jobs with status 'Interview'."""
        return self.get_jobs_by_status(JobStatus.INTERVIEW)

    def get_recent_jobs(self, days: int = 7) -> list[dict]:
        """
        Get jobs discovered in the last N days.

        Args:
            days: Number of days to look back

        Returns:
            List of Notion page data
        """
        from datetime import timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        response = self.client.databases.query(
            database_id=self.jobs_db_id,
            filter={
                "property": "Discovered Date",
                "date": {"on_or_after": cutoff},
            },
            sorts=[{"property": "Score", "direction": "descending"}],
        )

        return response["results"]

    # ==================== Companies Watchlist ====================

    def get_companies_to_check(self) -> list[Company]:
        """
        Get companies with 'Check Daily' enabled.

        Returns:
            List of Company objects
        """
        response = self.client.databases.query(
            database_id=self.companies_db_id,
            filter={"property": "Check Daily", "checkbox": {"equals": True}},
        )

        companies = []
        for page in response["results"]:
            try:
                company = self._page_to_company(page)
                companies.append(company)
            except Exception as e:
                logger.warning(f"Failed to parse company: {e}")

        return companies

    def _page_to_company(self, page: dict) -> Company:
        """Convert Notion page to Company object."""
        props = page["properties"]

        name = ""
        if props.get("Name", {}).get("title"):
            name = props["Name"]["title"][0]["text"]["content"]

        careers_url = props.get("Careers URL", {}).get("url", "")

        priority = "Medium"
        if props.get("Priority", {}).get("select"):
            priority = props["Priority"]["select"]["name"]

        locations = []
        if props.get("Locations", {}).get("multi_select"):
            locations = [loc["name"] for loc in props["Locations"]["multi_select"]]

        check_daily = props.get("Check Daily", {}).get("checkbox", True)

        last_checked = None
        if props.get("Last Checked", {}).get("date"):
            last_checked = datetime.fromisoformat(
                props["Last Checked"]["date"]["start"]
            )

        notes = ""
        if props.get("Notes", {}).get("rich_text"):
            notes = props["Notes"]["rich_text"][0]["text"]["content"]

        return Company(
            name=name,
            careers_url=careers_url,
            priority=priority,
            locations=locations,
            check_daily=check_daily,
            last_checked=last_checked,
            notes=notes,
        )

    def update_company_last_checked(self, page_id: str) -> None:
        """Update the 'Last Checked' date for a company."""
        self.client.pages.update(
            page_id=page_id,
            properties={
                "Last Checked": {"date": {"start": datetime.now().isoformat()}}
            },
        )

    # ==================== Search Criteria ====================

    def get_active_search_criteria(self) -> list[SearchCriteria]:
        """
        Get all active search criteria sets.

        Returns:
            List of SearchCriteria objects
        """
        response = self.client.databases.query(
            database_id=self.criteria_db_id,
            filter={"property": "Active", "checkbox": {"equals": True}},
        )

        criteria_list = []
        for page in response["results"]:
            try:
                criteria = self._page_to_criteria(page)
                criteria_list.append(criteria)
            except Exception as e:
                logger.warning(f"Failed to parse search criteria: {e}")

        return criteria_list

    def _page_to_criteria(self, page: dict) -> SearchCriteria:
        """Convert Notion page to SearchCriteria object."""
        props = page["properties"]

        name = ""
        if props.get("Name", {}).get("title"):
            name = props["Name"]["title"][0]["text"]["content"]

        keywords = []
        if props.get("Keywords", {}).get("multi_select"):
            keywords = [kw["name"] for kw in props["Keywords"]["multi_select"]]

        locations = []
        if props.get("Locations", {}).get("multi_select"):
            locations = [loc["name"] for loc in props["Locations"]["multi_select"]]

        active = props.get("Active", {}).get("checkbox", True)

        min_score = props.get("Min Score", {}).get("number", 60)

        excluded_companies = []
        if props.get("Excluded Companies", {}).get("multi_select"):
            excluded_companies = [
                c["name"] for c in props["Excluded Companies"]["multi_select"]
            ]

        return SearchCriteria(
            name=name,
            keywords=keywords,
            locations=locations,
            active=active,
            min_score=min_score,
            excluded_companies=excluded_companies,
        )

    # ==================== Interview Prep ====================

    def create_interview_prep(
        self,
        job_page_id: str,
        company_research: str,
        likely_questions: str,
        talking_points: str,
    ) -> str:
        """
        Create an interview prep entry.

        Args:
            job_page_id: Related job page ID
            company_research: Company research text
            likely_questions: Generated interview questions
            talking_points: Suggested talking points

        Returns:
            Notion page ID
        """
        properties = {
            "Job": {"relation": [{"id": job_page_id}]},
            "Company Research": {
                "rich_text": [{"text": {"content": company_research[:2000]}}]
            },
            "Likely Questions": {
                "rich_text": [{"text": {"content": likely_questions[:2000]}}]
            },
            "My Talking Points": {
                "rich_text": [{"text": {"content": talking_points[:2000]}}]
            },
        }

        response = self.client.pages.create(
            parent={"database_id": self.interview_prep_db_id},
            properties=properties,
        )

        return response["id"]

    # ==================== Utility Methods ====================

    def get_all_job_urls(self) -> set[str]:
        """
        Get all job URLs in the database for deduplication.

        Returns:
            Set of job URLs
        """
        urls = set()
        has_more = True
        next_cursor = None

        while has_more:
            response = self.client.databases.query(
                database_id=self.jobs_db_id,
                start_cursor=next_cursor,
            )

            for page in response["results"]:
                url = page["properties"].get("URL", {}).get("url")
                if url:
                    urls.add(url)

            has_more = response.get("has_more", False)
            next_cursor = response.get("next_cursor")

        logger.info(f"Found {len(urls)} existing job URLs in Notion")
        return urls

    def page_to_job(self, page: dict) -> Job:
        """
        Convert a Notion page to a Job object.

        Args:
            page: Notion page data

        Returns:
            Job object
        """
        props = page["properties"]

        title = ""
        if props.get("Title", {}).get("title"):
            title = props["Title"]["title"][0]["text"]["content"]

        company = ""
        if props.get("Company", {}).get("select"):
            company = props["Company"]["select"]["name"]

        location = ""
        if props.get("Location", {}).get("select"):
            location = props["Location"]["select"]["name"]

        url = props.get("URL", {}).get("url", "")

        source = JobSource.INDEED
        if props.get("Source", {}).get("select"):
            source_name = props["Source"]["select"]["name"]
            for s in JobSource:
                if s.value == source_name:
                    source = s
                    break

        status = JobStatus.NEW
        if props.get("Status", {}).get("select"):
            status_name = props["Status"]["select"]["name"]
            for s in JobStatus:
                if s.value == status_name:
                    status = s
                    break

        score = props.get("Score", {}).get("number", 0)

        posted_date = None
        if props.get("Posted Date", {}).get("date"):
            posted_date = datetime.fromisoformat(
                props["Posted Date"]["date"]["start"]
            )

        discovered_date = datetime.now()
        if props.get("Discovered Date", {}).get("date"):
            discovered_date = datetime.fromisoformat(
                props["Discovered Date"]["date"]["start"]
            )

        salary = ""
        if props.get("Salary", {}).get("rich_text"):
            salary = props["Salary"]["rich_text"][0]["text"]["content"]

        ai_analysis = ""
        if props.get("AI Analysis", {}).get("rich_text"):
            ai_analysis = props["AI Analysis"]["rich_text"][0]["text"]["content"]

        tailored_cv_url = props.get("Tailored CV", {}).get("url")
        cover_letter_url = props.get("Cover Letter", {}).get("url")

        notes = ""
        if props.get("Notes", {}).get("rich_text"):
            notes = props["Notes"]["rich_text"][0]["text"]["content"]

        return Job(
            title=title,
            company=company,
            location=location,
            description="",  # Not stored in Notion
            url=url,
            source=source,
            status=status,
            score=score,
            posted_date=posted_date,
            discovered_date=discovered_date,
            salary=salary,
            ai_analysis=ai_analysis,
            tailored_cv_url=tailored_cv_url,
            cover_letter_url=cover_letter_url,
            notes=notes,
            notion_page_id=page["id"],
        )
