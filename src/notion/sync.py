"""Notion synchronization operations."""

import structlog

from config.settings import settings
from src.models import Job, JobStatus
from src.notion.client import NotionClient

logger = structlog.get_logger()


class NotionSync:
    """Handle synchronization between JobHunter and Notion."""

    def __init__(self, client: NotionClient = None):
        """
        Initialize sync handler.

        Args:
            client: NotionClient instance (creates new one if not provided)
        """
        self.client = client or NotionClient()
        self._existing_urls: set[str] = set()

    def load_existing_urls(self) -> None:
        """Load all existing job URLs from Notion for deduplication."""
        self._existing_urls = self.client.get_all_job_urls()

    def is_duplicate(self, job: Job) -> bool:
        """
        Check if a job is a duplicate.

        Args:
            job: Job to check

        Returns:
            True if job URL already exists in Notion
        """
        return job.url in self._existing_urls

    def push_jobs(self, jobs: list[Job]) -> tuple[int, int]:
        """
        Push jobs to Notion, skipping duplicates.

        Args:
            jobs: List of jobs to push

        Returns:
            Tuple of (jobs_added, jobs_skipped)
        """
        # Ensure we have loaded existing URLs
        if not self._existing_urls:
            self.load_existing_urls()

        added = 0
        skipped = 0

        for job in jobs:
            # Skip if duplicate
            if self.is_duplicate(job):
                logger.debug(
                    "Skipping duplicate job",
                    title=job.title,
                    company=job.company,
                )
                skipped += 1
                continue

            # Skip if below score threshold
            if job.score < settings.min_score_threshold:
                logger.debug(
                    "Skipping low-score job",
                    title=job.title,
                    score=job.score,
                )
                skipped += 1
                continue

            try:
                # Create job in Notion
                page_id = self.client.create_job(job)
                job.notion_page_id = page_id

                # Add to existing URLs to prevent duplicates in same batch
                self._existing_urls.add(job.url)

                added += 1

            except Exception as e:
                logger.error(
                    "Failed to push job to Notion",
                    title=job.title,
                    error=str(e),
                )
                skipped += 1

        logger.info(
            "Push complete",
            added=added,
            skipped=skipped,
        )

        return added, skipped

    def get_status_changes(self) -> dict[str, list[Job]]:
        """
        Get jobs that need action based on status.

        Returns:
            Dict mapping action to list of jobs
        """
        changes = {
            "apply": [],  # Jobs to generate materials for
            "interview": [],  # Jobs to generate interview prep for
        }

        # Get jobs with "Apply" status
        apply_pages = self.client.get_jobs_to_apply()
        for page in apply_pages:
            job = self.client.page_to_job(page)
            # Only include if materials not yet generated
            if not job.tailored_cv_url:
                changes["apply"].append(job)

        # Get jobs with "Interview" status
        interview_pages = self.client.get_jobs_for_interview()
        for page in interview_pages:
            job = self.client.page_to_job(page)
            changes["interview"].append(job)

        logger.info(
            "Status changes detected",
            apply_count=len(changes["apply"]),
            interview_count=len(changes["interview"]),
        )

        return changes

    def update_job_with_materials(
        self,
        job: Job,
        cv_url: str = None,
        cover_letter_url: str = None,
    ) -> None:
        """
        Update a job with generated material URLs.

        Args:
            job: Job to update
            cv_url: URL to tailored CV
            cover_letter_url: URL to cover letter
        """
        if cv_url:
            job.tailored_cv_url = cv_url
        if cover_letter_url:
            job.cover_letter_url = cover_letter_url

        if job.notion_page_id:
            self.client.update_job(job.notion_page_id, job)

    def get_daily_summary(self) -> dict:
        """
        Get summary statistics for daily report.

        Returns:
            Dict with summary statistics
        """
        recent_jobs = self.client.get_recent_jobs(days=1)

        total = len(recent_jobs)
        strong_matches = sum(
            1 for j in recent_jobs
            if j["properties"].get("Score", {}).get("number", 0) >= settings.strong_match_threshold
        )

        # Group by source
        by_source = {}
        for job in recent_jobs:
            source = job["properties"].get("Source", {}).get("select", {}).get("name", "Unknown")
            by_source[source] = by_source.get(source, 0) + 1

        # Group by location
        by_location = {}
        for job in recent_jobs:
            location = job["properties"].get("Location", {}).get("select", {}).get("name", "Unknown")
            by_location[location] = by_location.get(location, 0) + 1

        return {
            "total_discovered": total,
            "strong_matches": strong_matches,
            "by_source": by_source,
            "by_location": by_location,
        }
