"""Interview preparation generator using AI."""

import json
from pathlib import Path
from typing import Optional

import anthropic
import structlog

from config.prompts import PROMPTS
from config.settings import settings, DATA_DIR
from src.models import Job

logger = structlog.get_logger()


class InterviewPrepGenerator:
    """Generate interview preparation materials using AI."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: Optional[str] = None,
        master_cv_path: Optional[Path] = None,
    ):
        """
        Initialize interview prep generator.

        Args:
            api_key: Anthropic API key
            model: Claude model to use
            master_cv_path: Path to master CV JSON
        """
        self.api_key = api_key or settings.anthropic_api_key
        self.model = model or settings.claude_model
        self.client = anthropic.Anthropic(api_key=self.api_key)

        # Load master CV
        self.master_cv_path = master_cv_path or DATA_DIR / "master_cv.json"
        self.master_cv = self._load_master_cv()
        self.candidate_summary = self._create_candidate_summary()

    def _load_master_cv(self) -> dict:
        """Load master CV from JSON file."""
        if self.master_cv_path.exists():
            with open(self.master_cv_path) as f:
                return json.load(f)
        return {}

    def _create_candidate_summary(self) -> str:
        """Create candidate summary for prompts."""
        if not self.master_cv:
            return "Solution Architect with 3+ years experience at Allianz Global Investors."

        summary_parts = []

        if self.master_cv.get("profiles"):
            summary_parts.append(self.master_cv["profiles"].get("default", ""))

        if self.master_cv.get("experience"):
            summary_parts.append("\nKey Achievements:")
            for exp in self.master_cv["experience"][:2]:
                if exp.get("bullets"):
                    for bullet in exp["bullets"][:3]:
                        text = bullet.get("text", bullet) if isinstance(bullet, dict) else bullet
                        summary_parts.append(f"- {text}")

        return "\n".join(summary_parts)

    async def research_company(self, company: str) -> str:
        """
        Generate company research summary.

        Args:
            company: Company name

        Returns:
            Company research text
        """
        logger.info(f"Researching company: {company}")

        prompt = PROMPTS["company_research"].format(
            company=company,
            job_title="",  # Generic research
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )

            return response.content[0].text

        except Exception as e:
            logger.error(f"Company research failed: {e}")
            return f"Research on {company} is pending."

    async def generate_questions(self, job: Job) -> str:
        """
        Generate likely interview questions.

        Args:
            job: Job to prepare for

        Returns:
            Interview questions text
        """
        logger.info(
            "Generating interview questions",
            title=job.title,
            company=job.company,
        )

        prompt = PROMPTS["interview_questions"].format(
            job_title=job.title,
            company=job.company,
            job_description=job.description[:4000],
            candidate_summary=self.candidate_summary,
        )

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2500,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )

            return response.content[0].text

        except Exception as e:
            logger.error(f"Question generation failed: {e}")
            return "Interview questions pending generation."

    async def generate_talking_points(self, job: Job) -> str:
        """
        Generate personalised talking points.

        Args:
            job: Job to prepare for

        Returns:
            Talking points text
        """
        logger.info("Generating talking points")

        prompt = f"""Based on the following job and candidate profile, generate personalised talking points for an interview.

Job Title: {job.title}
Company: {job.company}
Job Description: {job.description[:3000]}

Candidate Profile:
{self.candidate_summary}

Generate:
1. 3-5 key stories/examples from the candidate's experience that align with job requirements
2. How to address potential concerns (e.g., experience level, skill gaps)
3. Questions the candidate should ask to demonstrate genuine interest
4. Key points to emphasise about fit with this specific role

Format as clear, actionable talking points."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=2000,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )

            return response.content[0].text

        except Exception as e:
            logger.error(f"Talking points generation failed: {e}")
            return "Talking points pending generation."

    async def research_interviewer(self, name: str, company: str) -> str:
        """
        Research an interviewer.

        Args:
            name: Interviewer's name
            company: Company name

        Returns:
            Interviewer research text
        """
        logger.info(f"Researching interviewer: {name} at {company}")

        prompt = f"""Research the following person for interview preparation:

Name: {name}
Company: {company}

Provide (if findable):
1. Current role and tenure
2. Career background and progression
3. Areas of expertise or focus
4. Any published content, talks, or notable achievements
5. Potential shared interests or connections
6. Suggested conversation topics

Note: This is for interview preparation purposes only. Focus on publicly available professional information."""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1500,
                messages=[
                    {"role": "user", "content": prompt}
                ],
            )

            return response.content[0].text

        except Exception as e:
            logger.error(f"Interviewer research failed: {e}")
            return f"Research on {name} is pending."

    async def generate_full_prep(self, job: Job) -> dict:
        """
        Generate complete interview preparation.

        Args:
            job: Job to prepare for

        Returns:
            Dict with all prep materials
        """
        logger.info(
            "Generating full interview prep",
            title=job.title,
            company=job.company,
        )

        company_research = await self.research_company(job.company)
        questions = await self.generate_questions(job)
        talking_points = await self.generate_talking_points(job)

        return {
            "company_research": company_research,
            "likely_questions": questions,
            "talking_points": talking_points,
            "job_title": job.title,
            "company": job.company,
        }
