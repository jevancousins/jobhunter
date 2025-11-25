#!/usr/bin/env python3
"""
Process status changes script.

This script:
1. Polls Notion for jobs with status changes
2. Generates materials for jobs with "Apply" status
3. Creates interview prep for jobs with "Interview" status

Run manually: python scripts/process_status.py
Scheduled: GitHub Actions every 15 minutes
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings
from src.notion import NotionClient, NotionSync
from src.models import Job

# Configure logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()


async def generate_application_materials(job: Job) -> tuple[str, str]:
    """
    Generate tailored CV and cover letter for a job.

    Args:
        job: Job to generate materials for

    Returns:
        Tuple of (cv_url, cover_letter_url)
    """
    # Import here to avoid circular imports
    from src.generation.cv_tailor import CVTailor
    from src.generation.cover_letter import CoverLetterGenerator
    from src.storage.gdrive import GoogleDriveStorage

    logger.info(
        "Generating application materials",
        title=job.title,
        company=job.company,
    )

    try:
        # Generate tailored CV
        cv_tailor = CVTailor()
        cv_content = await cv_tailor.tailor_cv(job)

        # Generate cover letter
        cl_generator = CoverLetterGenerator()
        cover_letter = await cl_generator.generate(job)

        # Upload to Google Drive
        storage = GoogleDriveStorage()
        cv_url = storage.upload_cv(cv_content, job)
        cl_url = storage.upload_cover_letter(cover_letter, job)

        logger.info(
            "Materials generated and uploaded",
            cv_url=cv_url,
            cover_letter_url=cl_url,
        )

        return cv_url, cl_url

    except Exception as e:
        logger.error(f"Failed to generate materials: {e}")
        return None, None


async def generate_interview_prep(job: Job, notion_client: NotionClient) -> None:
    """
    Generate interview preparation materials.

    Args:
        job: Job to prepare for
        notion_client: Notion client for creating prep entry
    """
    from src.generation.interview_prep import InterviewPrepGenerator

    logger.info(
        "Generating interview prep",
        title=job.title,
        company=job.company,
    )

    try:
        prep_generator = InterviewPrepGenerator()

        # Generate research and questions
        company_research = await prep_generator.research_company(job.company)
        likely_questions = await prep_generator.generate_questions(job)
        talking_points = await prep_generator.generate_talking_points(job)

        # Create interview prep entry in Notion
        if job.notion_page_id:
            notion_client.create_interview_prep(
                job_page_id=job.notion_page_id,
                company_research=company_research,
                likely_questions=likely_questions,
                talking_points=talking_points,
            )

        logger.info("Interview prep created")

    except Exception as e:
        logger.error(f"Failed to generate interview prep: {e}")


async def main():
    """Main entry point for status processing."""
    start_time = datetime.now()
    logger.info("Processing status changes", time=start_time.isoformat())

    if not settings.notion_api_key:
        logger.error("Notion API key not configured")
        return

    # Initialize clients
    notion_client = NotionClient()
    sync = NotionSync(notion_client)

    # Get status changes
    changes = sync.get_status_changes()

    # Process "Apply" status - generate materials
    for job in changes["apply"]:
        try:
            cv_url, cl_url = await generate_application_materials(job)
            if cv_url or cl_url:
                sync.update_job_with_materials(job, cv_url, cl_url)
        except Exception as e:
            logger.error(
                "Failed to process Apply job",
                title=job.title,
                error=str(e),
            )

    # Process "Interview" status - generate prep
    for job in changes["interview"]:
        try:
            await generate_interview_prep(job, notion_client)
        except Exception as e:
            logger.error(
                "Failed to process Interview job",
                title=job.title,
                error=str(e),
            )

    # Summary
    elapsed = datetime.now() - start_time
    logger.info(
        "Status processing complete",
        elapsed_seconds=elapsed.total_seconds(),
        apply_processed=len(changes["apply"]),
        interview_processed=len(changes["interview"]),
    )


if __name__ == "__main__":
    asyncio.run(main())
