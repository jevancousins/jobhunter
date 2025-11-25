#!/usr/bin/env python3
"""
Daily job discovery script.

This script:
1. Loads search criteria from Notion (or uses defaults)
2. Scrapes jobs from multiple sources
3. Scores jobs using AI
4. Pushes qualified jobs to Notion

Run manually: python scripts/daily_discover.py
Scheduled: GitHub Actions at 07:00 UTC daily
"""

import asyncio
import sys
from datetime import datetime
from pathlib import Path

import structlog

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings, TARGET_ROLE_KEYWORDS, TARGET_LOCATIONS
from src.scrapers import IndeedScraper, LinkedInScraper, WelcomeToTheJungleScraper
from src.scoring import AIScorer
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


async def scrape_all_sources(
    keywords: list[str],
    locations: list[str],
) -> list[Job]:
    """
    Scrape jobs from all configured sources.

    Args:
        keywords: Job title keywords to search
        locations: Locations to search

    Returns:
        Combined list of jobs from all sources
    """
    all_jobs = []

    # Indeed
    logger.info("Starting Indeed scrape")
    try:
        async with IndeedScraper(
            delay_seconds=settings.scrape_delay_seconds,
            max_jobs=settings.max_jobs_per_source,
        ) as scraper:
            jobs = await scraper.scrape(keywords, locations)
            all_jobs.extend(jobs)
            logger.info(f"Indeed: found {len(jobs)} jobs")
    except Exception as e:
        logger.error(f"Indeed scrape failed: {e}")

    # LinkedIn
    logger.info("Starting LinkedIn scrape")
    try:
        async with LinkedInScraper(
            delay_seconds=settings.scrape_delay_seconds,
            max_jobs=settings.max_jobs_per_source,
        ) as scraper:
            jobs = await scraper.scrape(keywords, locations)
            all_jobs.extend(jobs)
            logger.info(f"LinkedIn: found {len(jobs)} jobs")
    except Exception as e:
        logger.error(f"LinkedIn scrape failed: {e}")

    # Welcome to the Jungle (France-focused)
    logger.info("Starting Welcome to the Jungle scrape")
    try:
        async with WelcomeToTheJungleScraper(
            delay_seconds=settings.scrape_delay_seconds,
            max_jobs=settings.max_jobs_per_source,
        ) as scraper:
            # WTFJ only supports French locations
            french_locations = [loc for loc in locations if is_french_location(loc)]
            if french_locations:
                jobs = await scraper.scrape(keywords, french_locations)
                all_jobs.extend(jobs)
                logger.info(f"WTFJ: found {len(jobs)} jobs")
            else:
                logger.info("WTFJ: skipped (no French locations in search)")
    except Exception as e:
        logger.error(f"WTFJ scrape failed: {e}")

    return all_jobs


def is_french_location(location: str) -> bool:
    """Check if location is in France."""
    french_keywords = ["paris", "lyon", "france", "marseille", "bordeaux", "lille", "remote"]
    return any(kw in location.lower() for kw in french_keywords)


def deduplicate_jobs(jobs: list[Job]) -> list[Job]:
    """
    Remove duplicate jobs based on URL.

    Args:
        jobs: List of jobs

    Returns:
        Deduplicated list
    """
    seen_urls = set()
    unique_jobs = []

    for job in jobs:
        if job.url not in seen_urls:
            seen_urls.add(job.url)
            unique_jobs.append(job)

    logger.info(
        "Deduplicated jobs",
        original=len(jobs),
        unique=len(unique_jobs),
    )

    return unique_jobs


async def main():
    """Main entry point for daily discovery."""
    start_time = datetime.now()
    logger.info("Starting daily job discovery", time=start_time.isoformat())

    # Get search criteria
    keywords = TARGET_ROLE_KEYWORDS
    locations = TARGET_LOCATIONS

    # Try to load from Notion if configured
    if settings.notion_api_key and settings.notion_criteria_db_id:
        try:
            notion_client = NotionClient()
            criteria_list = notion_client.get_active_search_criteria()
            if criteria_list:
                # Combine all active criteria
                keywords = []
                locations = []
                for criteria in criteria_list:
                    keywords.extend(criteria.keywords)
                    locations.extend(criteria.locations)
                keywords = list(set(keywords))  # Dedupe
                locations = list(set(locations))
                logger.info(
                    "Loaded search criteria from Notion",
                    keywords_count=len(keywords),
                    locations_count=len(locations),
                )
        except Exception as e:
            logger.warning(f"Failed to load criteria from Notion, using defaults: {e}")

    # Scrape all sources
    logger.info(
        "Search parameters",
        keywords=keywords[:5],  # Log first 5
        locations=locations,
    )

    jobs = await scrape_all_sources(keywords, locations)
    logger.info(f"Total jobs scraped: {len(jobs)}")

    if not jobs:
        logger.warning("No jobs found, exiting")
        return

    # Deduplicate
    jobs = deduplicate_jobs(jobs)

    # Score jobs with AI
    if settings.anthropic_api_key:
        logger.info("Scoring jobs with AI")
        scorer = AIScorer()

        scored_jobs = []
        for i, job in enumerate(jobs):
            try:
                scored_job = await scorer.score_job(job)
                scored_jobs.append(scored_job)
                logger.info(
                    f"Scored job {i+1}/{len(jobs)}",
                    title=job.title,
                    score=scored_job.score,
                )
            except Exception as e:
                logger.error(f"Failed to score job: {e}")
                # Still include the job with score 0
                scored_jobs.append(job)

        jobs = scored_jobs

        # Filter by score
        qualified_jobs = scorer.filter_by_score(jobs)
        strong_matches = scorer.get_strong_matches(jobs)

        logger.info(
            "Scoring complete",
            total_scored=len(jobs),
            qualified=len(qualified_jobs),
            strong_matches=len(strong_matches),
        )
    else:
        logger.warning("No Anthropic API key, skipping AI scoring")
        qualified_jobs = jobs

    # Push to Notion
    if settings.notion_api_key and settings.notion_jobs_db_id:
        logger.info("Pushing jobs to Notion")
        sync = NotionSync()
        added, skipped = sync.push_jobs(qualified_jobs)

        # Log daily summary
        summary = sync.get_daily_summary()
        logger.info(
            "Daily summary",
            discovered=summary["total_discovered"],
            strong_matches=summary["strong_matches"],
            by_source=summary["by_source"],
            by_location=summary["by_location"],
        )
    else:
        logger.warning("Notion not configured, skipping push")
        added = 0
        skipped = len(qualified_jobs)

    # Final summary
    elapsed = datetime.now() - start_time
    logger.info(
        "Daily discovery complete",
        elapsed_seconds=elapsed.total_seconds(),
        jobs_scraped=len(jobs),
        jobs_added=added,
        jobs_skipped=skipped,
    )


if __name__ == "__main__":
    asyncio.run(main())
