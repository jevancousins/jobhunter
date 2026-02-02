"""Tests for career site scraper with AI extraction."""

import json
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.models import Company, Job, JobSource
from src.scrapers.career_site import (
    CareerSiteScraper,
    BLOCKING_INDICATORS,
    MAX_HTML_LENGTH,
)


class TestCareerSiteScraperInit:
    """Tests for CareerSiteScraper initialization."""

    def test_default_initialization(self):
        """Test scraper initializes with correct defaults."""
        scraper = CareerSiteScraper()

        assert scraper.delay_seconds == 3.0
        assert scraper.max_jobs == 50
        assert scraper.max_pagination_pages == 2
        assert scraper.model == "claude-haiku-3-5-latest"
        assert scraper.use_playwright is True
        assert scraper.source == JobSource.COMPANY_PAGE

    def test_custom_initialization(self):
        """Test scraper accepts custom parameters."""
        scraper = CareerSiteScraper(
            delay_seconds=5.0,
            max_jobs=100,
            max_pagination_pages=3,
            model="claude-sonnet-4-20250514",
        )

        assert scraper.delay_seconds == 5.0
        assert scraper.max_jobs == 100
        assert scraper.max_pagination_pages == 3
        assert scraper.model == "claude-sonnet-4-20250514"


class TestHTMLCleaning:
    """Tests for HTML cleaning functionality."""

    def test_removes_script_tags(self):
        """Test that script tags and content are removed."""
        scraper = CareerSiteScraper()
        html = '<div>Hello</div><script>alert("bad")</script><p>World</p>'

        cleaned = scraper._clean_html(html)

        assert "<script" not in cleaned
        assert "alert" not in cleaned
        assert "Hello" in cleaned
        assert "World" in cleaned

    def test_removes_style_tags(self):
        """Test that style tags and content are removed."""
        scraper = CareerSiteScraper()
        html = '<div>Hello</div><style>.foo { color: red; }</style><p>World</p>'

        cleaned = scraper._clean_html(html)

        assert "<style" not in cleaned
        assert "color: red" not in cleaned
        assert "Hello" in cleaned

    def test_removes_html_comments(self):
        """Test that HTML comments are removed."""
        scraper = CareerSiteScraper()
        html = '<div>Hello</div><!-- This is a comment --><p>World</p>'

        cleaned = scraper._clean_html(html)

        assert "<!--" not in cleaned
        assert "comment" not in cleaned

    def test_removes_svg_content(self):
        """Test that SVG content is removed."""
        scraper = CareerSiteScraper()
        html = '<div>Hello</div><svg><path d="M0 0"/></svg><p>World</p>'

        cleaned = scraper._clean_html(html)

        assert "<svg" not in cleaned
        assert "<path" not in cleaned

    def test_removes_inline_styles(self):
        """Test that inline styles are removed."""
        scraper = CareerSiteScraper()
        html = '<div style="color: red; font-size: 14px;">Hello</div>'

        cleaned = scraper._clean_html(html)

        assert 'style="' not in cleaned
        assert "Hello" in cleaned

    def test_collapses_whitespace(self):
        """Test that multiple whitespace characters are collapsed."""
        scraper = CareerSiteScraper()
        html = "<div>Hello    \n\n\t   World</div>"

        cleaned = scraper._clean_html(html)

        assert "    " not in cleaned
        assert "\n" not in cleaned

    def test_truncates_long_html(self):
        """Test that HTML is truncated to MAX_HTML_LENGTH."""
        scraper = CareerSiteScraper()
        html = "a" * (MAX_HTML_LENGTH + 1000)

        cleaned = scraper._clean_html(html)

        assert len(cleaned) <= MAX_HTML_LENGTH + 50  # Allow for truncation message
        assert "truncated" in cleaned.lower()


class TestBlockingDetection:
    """Tests for blocking indicator detection."""

    def test_detects_captcha(self):
        """Test that CAPTCHA pages are detected."""
        scraper = CareerSiteScraper()
        html = "<div>Please complete the CAPTCHA to continue</div>"

        assert scraper._is_blocked(html) is True

    def test_detects_access_denied(self):
        """Test that access denied pages are detected."""
        scraper = CareerSiteScraper()
        html = "<h1>Access Denied</h1><p>You don't have permission</p>"

        assert scraper._is_blocked(html) is True

    def test_detects_cloudflare(self):
        """Test that Cloudflare challenge pages are detected."""
        scraper = CareerSiteScraper()
        html = "<div>Checking your browser before accessing... Cloudflare</div>"

        assert scraper._is_blocked(html) is True

    def test_normal_page_not_blocked(self):
        """Test that normal career pages are not flagged."""
        scraper = CareerSiteScraper()
        html = """
        <div class="jobs-list">
            <a href="/job/123">Software Engineer</a>
            <a href="/job/456">Data Scientist</a>
        </div>
        """

        assert scraper._is_blocked(html) is False

    def test_case_insensitive_detection(self):
        """Test that blocking detection is case insensitive."""
        scraper = CareerSiteScraper()
        html = "<div>PLEASE VERIFY you are human</div>"

        assert scraper._is_blocked(html) is True


class TestJobCreation:
    """Tests for job object creation from extraction."""

    def test_creates_job_from_valid_data(self):
        """Test creating a job from valid extraction data."""
        scraper = CareerSiteScraper()
        job_data = {
            "title": "Data Scientist",
            "location": "Paris, France",
            "url": "/careers/job/123",
            "department": "Data",
            "posted_date": "2024-01-15",
        }

        job = scraper._create_job_from_extraction(
            job_data,
            "Mistral AI",
            "https://mistral.ai",
        )

        assert job is not None
        assert job.title == "Data Scientist"
        assert job.company == "Mistral AI"
        assert job.location == "Paris, France"
        assert job.url == "https://mistral.ai/careers/job/123"
        assert job.source == JobSource.COMPANY_PAGE

    def test_resolves_relative_url(self):
        """Test that relative URLs are resolved to absolute."""
        scraper = CareerSiteScraper()
        job_data = {
            "title": "Engineer",
            "location": "London",
            "url": "/jobs/engineer",
        }

        job = scraper._create_job_from_extraction(
            job_data,
            "Company",
            "https://company.com",
        )

        assert job.url == "https://company.com/jobs/engineer"

    def test_handles_absolute_url(self):
        """Test that absolute URLs are preserved."""
        scraper = CareerSiteScraper()
        job_data = {
            "title": "Engineer",
            "location": "London",
            "url": "https://jobs.company.com/engineer",
        }

        job = scraper._create_job_from_extraction(
            job_data,
            "Company",
            "https://company.com",
        )

        assert job.url == "https://jobs.company.com/engineer"

    def test_returns_none_for_missing_title(self):
        """Test that missing title returns None."""
        scraper = CareerSiteScraper()
        job_data = {
            "location": "Paris",
            "url": "/job/123",
        }

        job = scraper._create_job_from_extraction(
            job_data,
            "Company",
            "https://company.com",
        )

        assert job is None

    def test_returns_none_for_missing_url(self):
        """Test that missing URL returns None."""
        scraper = CareerSiteScraper()
        job_data = {
            "title": "Engineer",
            "location": "Paris",
        }

        job = scraper._create_job_from_extraction(
            job_data,
            "Company",
            "https://company.com",
        )

        assert job is None

    def test_handles_null_location(self):
        """Test that null location is handled."""
        scraper = CareerSiteScraper()
        job_data = {
            "title": "Engineer",
            "url": "/job/123",
            "location": None,
        }

        job = scraper._create_job_from_extraction(
            job_data,
            "Company",
            "https://company.com",
        )

        assert job is not None
        assert job.location == "Not specified"

    def test_parses_posted_date(self):
        """Test that posted date is parsed correctly."""
        scraper = CareerSiteScraper()
        job_data = {
            "title": "Engineer",
            "url": "/job/123",
            "location": "Paris",
            "posted_date": "2024-01-15",
        }

        job = scraper._create_job_from_extraction(
            job_data,
            "Company",
            "https://company.com",
        )

        assert job.posted_date is not None
        assert job.posted_date.year == 2024
        assert job.posted_date.month == 1
        assert job.posted_date.day == 15


class TestAIExtraction:
    """Tests for AI extraction functionality."""

    @pytest.mark.asyncio
    async def test_extraction_returns_jobs(self):
        """Test that AI extraction returns parsed jobs."""
        scraper = CareerSiteScraper()

        # Mock the Anthropic client
        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps({
                    "jobs": [
                        {
                            "title": "Data Scientist",
                            "location": "Paris",
                            "url": "/job/ds",
                            "department": "AI",
                            "posted_date": "2024-01-10",
                        }
                    ],
                    "pagination": {"has_more_pages": False, "next_page_url": None},
                    "blocked": False,
                    "blocked_reason": None,
                    "extraction_confidence": "high",
                })
            )
        ]

        scraper._anthropic_client = MagicMock()
        scraper._anthropic_client.messages.create.return_value = mock_response

        result = await scraper._extract_jobs_with_ai(
            "<div>Jobs here</div>",
            "Mistral AI",
            "https://mistral.ai",
        )

        assert result is not None
        assert len(result["jobs"]) == 1
        assert result["jobs"][0]["title"] == "Data Scientist"
        assert result["extraction_confidence"] == "high"

    @pytest.mark.asyncio
    async def test_extraction_handles_blocked_page(self):
        """Test that extraction correctly identifies blocked pages."""
        scraper = CareerSiteScraper()

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text=json.dumps({
                    "jobs": [],
                    "pagination": {"has_more_pages": False, "next_page_url": None},
                    "blocked": True,
                    "blocked_reason": "CAPTCHA detected",
                    "extraction_confidence": "low",
                })
            )
        ]

        scraper._anthropic_client = MagicMock()
        scraper._anthropic_client.messages.create.return_value = mock_response

        result = await scraper._extract_jobs_with_ai(
            "<div>CAPTCHA</div>",
            "Company",
            "https://company.com",
        )

        assert result is not None
        assert result["blocked"] is True
        assert result["blocked_reason"] == "CAPTCHA detected"

    @pytest.mark.asyncio
    async def test_extraction_handles_json_in_code_block(self):
        """Test that JSON wrapped in code blocks is handled."""
        scraper = CareerSiteScraper()

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(
                text='```json\n{"jobs": [], "blocked": false, "extraction_confidence": "high"}\n```'
            )
        ]

        scraper._anthropic_client = MagicMock()
        scraper._anthropic_client.messages.create.return_value = mock_response

        result = await scraper._extract_jobs_with_ai(
            "<div>Empty</div>",
            "Company",
            "https://company.com",
        )

        assert result is not None
        assert result["jobs"] == []

    @pytest.mark.asyncio
    async def test_extraction_returns_none_on_invalid_json(self):
        """Test that invalid JSON returns None."""
        scraper = CareerSiteScraper()

        mock_response = MagicMock()
        mock_response.content = [
            MagicMock(text="This is not valid JSON at all")
        ]

        scraper._anthropic_client = MagicMock()
        scraper._anthropic_client.messages.create.return_value = mock_response

        result = await scraper._extract_jobs_with_ai(
            "<div>Test</div>",
            "Company",
            "https://company.com",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_extraction_returns_none_without_client(self):
        """Test that extraction returns None when client not initialized."""
        scraper = CareerSiteScraper()
        scraper._anthropic_client = None

        result = await scraper._extract_jobs_with_ai(
            "<div>Test</div>",
            "Company",
            "https://company.com",
        )

        assert result is None


class TestCompanyScraping:
    """Tests for company career page scraping."""

    @pytest.mark.asyncio
    async def test_scrape_company_with_no_url(self):
        """Test that companies without careers URL return empty list."""
        scraper = CareerSiteScraper()
        company = Company(
            name="Test Company",
            careers_url="",
        )

        # Don't need browser for this test
        jobs = await scraper.scrape_company(company)

        assert jobs == []

    @pytest.mark.asyncio
    async def test_search_raises_not_implemented(self):
        """Test that search() raises NotImplementedError."""
        scraper = CareerSiteScraper()

        with pytest.raises(NotImplementedError):
            await scraper.search(["engineer"], ["Paris"])


class TestDeduplication:
    """Tests for job deduplication in daily_discover."""

    def test_deduplicate_by_url(self):
        """Test deduplication by URL."""
        from scripts.daily_discover import deduplicate_jobs

        jobs = [
            Job(
                title="Engineer",
                company="Company A",
                location="Paris",
                description="",
                url="https://example.com/job/1",
                source=JobSource.LINKEDIN,
            ),
            Job(
                title="Engineer",
                company="Company A",
                location="Paris",
                description="",
                url="https://example.com/job/1",  # Same URL
                source=JobSource.INDEED,
            ),
        ]

        result = deduplicate_jobs(jobs)

        assert len(result) == 1

    def test_deduplicate_by_company_title(self):
        """Test deduplication by company+title."""
        from scripts.daily_discover import deduplicate_jobs

        jobs = [
            Job(
                title="Data Scientist",
                company="Mistral AI",
                location="Paris",
                description="",
                url="https://linkedin.com/job/123",
                source=JobSource.LINKEDIN,
            ),
            Job(
                title="Data Scientist",
                company="Mistral AI",
                location="Paris",
                description="",
                url="https://mistral.ai/careers/ds",  # Different URL
                source=JobSource.COMPANY_PAGE,
            ),
        ]

        result = deduplicate_jobs(jobs)

        assert len(result) == 1

    def test_keeps_different_jobs(self):
        """Test that different jobs are kept."""
        from scripts.daily_discover import deduplicate_jobs

        jobs = [
            Job(
                title="Data Scientist",
                company="Mistral AI",
                location="Paris",
                description="",
                url="https://example.com/job/1",
                source=JobSource.LINKEDIN,
            ),
            Job(
                title="ML Engineer",
                company="Mistral AI",
                location="Paris",
                description="",
                url="https://example.com/job/2",
                source=JobSource.COMPANY_PAGE,
            ),
        ]

        result = deduplicate_jobs(jobs)

        assert len(result) == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
