"""AI-powered job scoring using Claude API."""

import json
from pathlib import Path
from typing import Optional

import anthropic
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential

from config.prompts import PROMPTS
from config.settings import settings, DATA_DIR
from src.models import Job, ScoreBreakdown

logger = structlog.get_logger()


class APIUnavailableError(Exception):
    """Raised when the Anthropic API is unavailable due to credits or auth issues."""

    pass


class AIScorer:
    """Score jobs using Claude AI."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        master_cv_path: Optional[Path] = None,
    ):
        """
        Initialize the AI scorer.

        Args:
            api_key: Anthropic API key (uses settings if not provided)
            model: Claude model to use (uses settings if not provided)
            master_cv_path: Path to master CV JSON file
        """
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.claude_model
        self.client = anthropic.Anthropic(api_key=self.api_key)

        # Load master CV
        self.master_cv_path = master_cv_path or DATA_DIR / "master_cv.json"
        self.master_cv = self._load_master_cv()
        self.master_cv_summary = self._create_cv_summary()

    def _load_master_cv(self) -> dict:
        """Load master CV from JSON file."""
        if self.master_cv_path.exists():
            with open(self.master_cv_path) as f:
                return json.load(f)
        else:
            logger.warning(
                "Master CV not found, using default summary",
                path=str(self.master_cv_path),
            )
            return {}

    def _create_cv_summary(self) -> str:
        """Create a summary of the master CV for prompts."""
        if not self.master_cv:
            # Default summary based on PRD
            return """
Solution Architect at Allianz Global Investors with 3+ years experience.
Key skills: Python, SQL, Power BI, Azure, Databricks, MSCI BarraOne
Domain expertise: Fixed Income, Performance Attribution, Financial Modeling
Achievements:
- Led MSCI BarraOne implementation for global Fixed Income teams
- Engineered custom performance attribution models saving £25K+ per report
- Automated reconciliation processes saving £200K+ annually
- Pioneered AI adoption with 50+ use cases identified
Education: BSc Natural Sciences (Physics & Mathematics), UCL - 2:1
Languages: English (Native), French (Proficient)
"""

        # Build summary from master CV JSON
        summary_parts = []

        if "personal" in self.master_cv:
            personal = self.master_cv["personal"]
            summary_parts.append(f"Name: {personal.get('name', 'N/A')}")

        if "profiles" in self.master_cv:
            default_profile = self.master_cv["profiles"].get("default", "")
            if default_profile:
                summary_parts.append(f"\nProfile: {default_profile}")

        if "experience" in self.master_cv:
            summary_parts.append("\nExperience:")
            for exp in self.master_cv["experience"][:3]:  # Top 3 roles
                summary_parts.append(
                    f"- {exp.get('title', 'N/A')} at {exp.get('company', 'N/A')} "
                    f"({exp.get('start_date', 'N/A')} - {exp.get('end_date', 'Present')})"
                )
                if "bullets" in exp:
                    for bullet in exp["bullets"][:2]:  # Top 2 bullets
                        text = bullet.get("text", bullet) if isinstance(bullet, dict) else bullet
                        summary_parts.append(f"  • {text[:100]}...")

        if "skills" in self.master_cv:
            skills = self.master_cv["skills"]
            if isinstance(skills, dict):
                all_skills = []
                for category, skill_list in skills.items():
                    if isinstance(skill_list, list):
                        all_skills.extend(skill_list)
                summary_parts.append(f"\nSkills: {', '.join(all_skills[:15])}")
            elif isinstance(skills, list):
                summary_parts.append(f"\nSkills: {', '.join(skills[:15])}")

        if "education" in self.master_cv:
            summary_parts.append("\nEducation:")
            for edu in self.master_cv["education"]:
                summary_parts.append(
                    f"- {edu.get('degree', 'N/A')} from {edu.get('institution', 'N/A')}"
                )

        return "\n".join(summary_parts)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
    )
    async def score_job(self, job: Job) -> Job:
        """
        Score a job using AI analysis.

        Args:
            job: Job object to score

        Returns:
            Job object with score and analysis populated
        """
        logger.info(
            "Scoring job",
            title=job.title,
            company=job.company,
        )

        prompt = PROMPTS["job_scoring"].format(
            master_cv_summary=self.master_cv_summary,
            job_title=job.title,
            company=job.company,
            location=job.location,
            job_description=job.description[:8000],  # Limit description length
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                messages=[
                    {
                        "role": "user",
                        "content": prompt,
                    }
                ],
            )

            # Parse the response
            response_text = response.content[0].text

            # Try to extract JSON from response
            result = self._parse_scoring_response(response_text)

            if result:
                # Update job with scoring results
                scores = result.get("scores", {})

                job.score_breakdown = ScoreBreakdown(
                    location=scores.get("location", {}).get("score", 0),
                    role_alignment=scores.get("role_alignment", {}).get("score", 0),
                    industry_fit=scores.get("industry_fit", {}).get("score", 0),
                    seniority=scores.get("seniority", {}).get("score", 0),
                    skills_match=scores.get("skills_match", {}).get("score", 0),
                    impact_potential=scores.get("impact_potential", {}).get("score", 0),
                )

                job.score = result.get("total_score", job.score_breakdown.total)
                job.ai_analysis = result.get("summary", "")
                job.key_requirements = result.get("key_requirements", [])
                job.potential_concerns = result.get("potential_concerns", [])

                logger.info(
                    "Job scored",
                    title=job.title,
                    score=job.score,
                )
            else:
                logger.warning(
                    "Failed to parse scoring response",
                    title=job.title,
                )

        except anthropic.BadRequestError as e:
            error_msg = str(e)
            # Check for credit/billing related errors
            if "credit balance" in error_msg.lower() or "billing" in error_msg.lower():
                logger.error(
                    "API unavailable - insufficient credits",
                    title=job.title,
                    error=error_msg,
                )
                raise APIUnavailableError(f"Anthropic API credits exhausted: {error_msg}")
            else:
                logger.error(
                    "AI scoring failed",
                    title=job.title,
                    error=error_msg,
                )

        except anthropic.AuthenticationError as e:
            logger.error(
                "API unavailable - authentication failed",
                error=str(e),
            )
            raise APIUnavailableError(f"Anthropic API authentication failed: {e}")

        except Exception as e:
            logger.error(
                "AI scoring failed",
                title=job.title,
                error=str(e),
            )

        return job

    def _parse_scoring_response(self, response_text: str) -> Optional[dict]:
        """
        Parse the JSON response from Claude.

        Args:
            response_text: Raw response text

        Returns:
            Parsed JSON dict or None
        """
        # Try to find JSON in the response
        try:
            # First try direct JSON parsing
            return json.loads(response_text)
        except json.JSONDecodeError:
            pass

        # Try to extract JSON from markdown code blocks
        import re
        json_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", response_text)
        if json_match:
            try:
                return json.loads(json_match.group(1))
            except json.JSONDecodeError:
                pass

        # Try to find JSON object in text
        json_match = re.search(r"\{[\s\S]*\}", response_text)
        if json_match:
            try:
                return json.loads(json_match.group(0))
            except json.JSONDecodeError:
                pass

        return None

    async def score_jobs(self, jobs: list[Job]) -> list[Job]:
        """
        Score multiple jobs.

        Args:
            jobs: List of jobs to score

        Returns:
            List of jobs with scores
        """
        scored_jobs = []

        for job in jobs:
            scored_job = await self.score_job(job)
            scored_jobs.append(scored_job)

        return scored_jobs

    def filter_by_score(
        self,
        jobs: list[Job],
        min_score: Optional[int] = None,
    ) -> list[Job]:
        """
        Filter jobs by minimum score.

        Args:
            jobs: List of scored jobs
            min_score: Minimum score threshold (uses settings if not provided)

        Returns:
            Filtered list of jobs
        """
        threshold = min_score or settings.min_score_threshold

        filtered = [job for job in jobs if job.score >= threshold]

        logger.info(
            "Filtered jobs by score",
            threshold=threshold,
            original_count=len(jobs),
            filtered_count=len(filtered),
        )

        return filtered

    def get_strong_matches(
        self,
        jobs: list[Job],
        threshold: Optional[int] = None,
    ) -> list[Job]:
        """
        Get jobs that are strong matches.

        Args:
            jobs: List of scored jobs
            threshold: Strong match threshold (uses settings if not provided)

        Returns:
            List of strong match jobs
        """
        threshold = threshold or settings.strong_match_threshold
        return [job for job in jobs if job.score >= threshold]
