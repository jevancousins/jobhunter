"""Tests for AI scorer with unified scoring framework."""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

from src.models import ScoreBreakdown, Job, JobSource
from src.scoring.ai_scorer import AIScorer


class TestScoreBreakdown:
    """Tests for ScoreBreakdown dataclass."""

    def test_new_unified_dimensions_total(self):
        """Test total calculation with new unified dimensions."""
        breakdown = ScoreBreakdown(
            growth_potential=20,
            role_alignment=15,
            founder_relevance=18,
            location_fit=12,
            compensation_signal=8,
            industry_fit=7,
        )
        assert breakdown.total == 80

    def test_legacy_dimensions_total(self):
        """Test total calculation falls back to legacy when new dimensions are zero.

        Note: role_alignment and industry_fit are shared between both frameworks.
        Legacy fallback only triggers when ALL new-only dimensions are zero:
        growth_potential, founder_relevance, location_fit, compensation_signal.
        """
        breakdown = ScoreBreakdown(
            # Legacy-only fields
            location=20,
            seniority=8,
            skills_match=12,
            impact_potential=7,
            # Shared fields (will be used in legacy calc)
            role_alignment=0,
            industry_fit=0,
            # New-only fields must be 0 for legacy fallback
            growth_potential=0,
            founder_relevance=0,
            location_fit=0,
            compensation_signal=0,
        )
        # Legacy total = location + role_alignment + industry_fit + seniority + skills_match + impact_potential
        # = 20 + 0 + 0 + 8 + 12 + 7 = 47
        assert breakdown.total == 47

    def test_new_dimensions_take_precedence(self):
        """Test that new dimensions take precedence when populated."""
        breakdown = ScoreBreakdown(
            # New dimensions
            growth_potential=25,
            role_alignment=20,
            founder_relevance=20,
            location_fit=15,
            compensation_signal=10,
            industry_fit=10,
            # Legacy dimensions (should be ignored)
            location=5,
            seniority=5,
            skills_match=5,
            impact_potential=5,
        )
        # New total = 25 + 20 + 20 + 15 + 10 + 10 = 100
        assert breakdown.total == 100

    def test_to_dict_includes_all_fields(self):
        """Test to_dict includes both new and legacy fields."""
        breakdown = ScoreBreakdown(
            growth_potential=20,
            role_alignment=15,
            founder_relevance=18,
            location_fit=12,
            compensation_signal=8,
            industry_fit=7,
        )
        result = breakdown.to_dict()

        # New dimensions
        assert "growth_potential" in result
        assert "founder_relevance" in result
        assert "location_fit" in result
        assert "compensation_signal" in result

        # Legacy dimensions
        assert "location" in result
        assert "seniority" in result
        assert "skills_match" in result
        assert "impact_potential" in result

        # Total
        assert result["total"] == 80


class TestAIScorerInitialization:
    """Tests for AIScorer initialization."""

    @patch('src.scoring.ai_scorer.anthropic.Anthropic')
    def test_loads_job_goals(self, mock_anthropic):
        """Test that AIScorer loads job_goals.json."""
        scorer = AIScorer(api_key="test-key")

        # Should have loaded job goals
        assert scorer.job_goals is not None
        assert "career_vision" in scorer.job_goals
        assert "dealbreakers" in scorer.job_goals
        assert "scoring_weights" in scorer.job_goals

    @patch('src.scoring.ai_scorer.anthropic.Anthropic')
    def test_creates_goals_summary(self, mock_anthropic):
        """Test that goals summary is created from job_goals.json."""
        scorer = AIScorer(api_key="test-key")

        # Should have created a summary
        assert scorer.job_goals_summary is not None
        assert "Founder" in scorer.job_goals_summary or "5-Year Goal" in scorer.job_goals_summary

    @patch('src.scoring.ai_scorer.anthropic.Anthropic')
    def test_creates_dealbreakers_summary(self, mock_anthropic):
        """Test that dealbreakers summary is created."""
        scorer = AIScorer(api_key="test-key")

        # Should have created dealbreakers summary
        assert scorer.dealbreakers_summary is not None
        assert "Crypto" in scorer.dealbreakers_summary or "Dealbreaker" in scorer.dealbreakers_summary

    @patch('src.scoring.ai_scorer.anthropic.Anthropic')
    def test_handles_missing_job_goals_file(self, mock_anthropic):
        """Test graceful handling of missing job_goals.json."""
        scorer = AIScorer(
            api_key="test-key",
            job_goals_path=Path("/nonexistent/path/job_goals.json")
        )

        # Should fall back to defaults
        assert scorer.job_goals == {}
        assert scorer.job_goals_summary is not None  # Should use default


class TestAIScorerScoring:
    """Tests for AIScorer scoring logic."""

    @patch('src.scoring.ai_scorer.anthropic.Anthropic')
    def test_parses_unified_scoring_response(self, mock_anthropic):
        """Test parsing of new unified scoring response."""
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client

        scorer = AIScorer(api_key="test-key")

        # Mock response with new unified dimensions
        response_json = {
            "dealbreaker_triggered": None,
            "scores": {
                "growth_potential": {"score": 22, "reason": "Good learning opportunities"},
                "role_alignment": {"score": 18, "reason": "Strong skills match"},
                "founder_relevance": {"score": 16, "reason": "Product exposure"},
                "location_fit": {"score": 12, "reason": "Paris office"},
                "compensation_signal": {"score": 7, "reason": "Competitive salary"},
                "industry_fit": {"score": 8, "reason": "FinTech"},
            },
            "total_score": 83,
            "verdict": "Apply",
            "summary": "Strong match for ML role",
            "key_requirements": ["Python", "ML"],
            "potential_concerns": ["Fast pace"],
            "questions_to_ask": ["Team structure?"]
        }

        result = scorer._parse_scoring_response(json.dumps(response_json))

        assert result is not None
        assert result["total_score"] == 83
        assert result["verdict"] == "Apply"
        assert result["scores"]["growth_potential"]["score"] == 22

    @patch('src.scoring.ai_scorer.anthropic.Anthropic')
    def test_parses_dealbreaker_response(self, mock_anthropic):
        """Test parsing of dealbreaker response."""
        mock_client = MagicMock()
        mock_anthropic.return_value = mock_client

        scorer = AIScorer(api_key="test-key")

        # Mock response with dealbreaker triggered
        response_json = {
            "dealbreaker_triggered": "Crypto/Web3 industry",
            "scores": {},
            "total_score": 0,
            "verdict": "Skip",
            "summary": "Role is in dealbreaker industry.",
            "key_requirements": [],
            "potential_concerns": [],
            "questions_to_ask": []
        }

        result = scorer._parse_scoring_response(json.dumps(response_json))

        assert result is not None
        assert result["dealbreaker_triggered"] == "Crypto/Web3 industry"
        assert result["total_score"] == 0
        assert result["verdict"] == "Skip"


class TestJobGoalsJson:
    """Tests for job_goals.json structure."""

    def test_job_goals_file_exists(self):
        """Test that job_goals.json exists."""
        path = Path(__file__).parent.parent / "data" / "job_goals.json"
        assert path.exists(), f"job_goals.json not found at {path}"

    def test_job_goals_valid_json(self):
        """Test that job_goals.json is valid JSON."""
        path = Path(__file__).parent.parent / "data" / "job_goals.json"
        with open(path) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_job_goals_has_required_sections(self):
        """Test that job_goals.json has all required sections."""
        path = Path(__file__).parent.parent / "data" / "job_goals.json"
        with open(path) as f:
            data = json.load(f)

        required_sections = [
            "career_vision",
            "priorities",
            "location",
            "compensation",
            "target_roles",
            "target_industries",
            "dealbreakers",
            "scoring_weights",
        ]

        for section in required_sections:
            assert section in data, f"Missing section: {section}"

    def test_scoring_weights_sum_to_100(self):
        """Test that scoring weights sum to 100."""
        path = Path(__file__).parent.parent / "data" / "job_goals.json"
        with open(path) as f:
            data = json.load(f)

        weights = data["scoring_weights"]
        total = sum(weights.values())
        assert total == 100, f"Scoring weights sum to {total}, expected 100"

    def test_dealbreakers_has_industries_and_signals(self):
        """Test that dealbreakers has both industries and signals."""
        path = Path(__file__).parent.parent / "data" / "job_goals.json"
        with open(path) as f:
            data = json.load(f)

        dealbreakers = data["dealbreakers"]
        assert "industries" in dealbreakers
        assert "signals" in dealbreakers
        assert len(dealbreakers["industries"]) > 0
        assert len(dealbreakers["signals"]) > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
