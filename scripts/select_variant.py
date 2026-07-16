"""Deterministic CV variant selector for the auto-apply pipeline.

Maps a job title (and optional JD description for context detection) to one of
the CV variants in cv/variants/. Matching rules are data-driven: they live in
cv/variants/variants.json (generated during onboarding; see
cv/templates/variants.example.json for the schema). Title patterns are
evaluated in order; first match wins.

variants.json schema:
  {
    "default_variant": "general",
    "rules": [
      {"variant": "data-analyst",
       "title_patterns": ["\\bdata\\s+analyst\\b"],
       "reason": "Data Analyst title"}
    ],
    "swaps": {
      "context_patterns": ["\\bhedge\\s+fund\\b"],
      "variant_map": {"data-engineer": "data-engineer-buyside"},
      "label": "buy-side context"
    }
  }

The default variant resolution order is:
  1. variants.json "default_variant"
  2. search_config.json cv.default_variant
  3. "general"

Also returns the candidate's max-claimable years for the matched variant,
sourced from cv/variants/seniority_caps.json. Downstream scoring
(quick_filter, ai_scorer) and CV tailoring use this cap to avoid
over-claiming experience.

Usage:
  python scripts/select_variant.py --title "Senior Data Engineer"
  python scripts/select_variant.py --title "Data Engineer" --description "..."

Output (JSON on stdout):
  {
    "variant": "data-engineer",
    "pdf_path": "cv/output/data-engineer.pdf",
    "tex_path": "cv/variants/data-engineer.tex",
    "max_years": 3,
    "cap_rationale": "...",
    "reason": "matched /\\bdata\\s+engineer\\b/ -> Data Engineer"
  }
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PDF_DIR = PROJECT_ROOT / "cv" / "output"
TEX_DIR = PROJECT_ROOT / "cv" / "variants"
CAPS_PATH = TEX_DIR / "seniority_caps.json"
RULES_PATH = TEX_DIR / "variants.json"

FALLBACK_VARIANT = "general"

INTELLIGENCE_PATH = PROJECT_ROOT / "data" / "apply-intelligence.json"

_intelligence_cache: dict | None = None


@lru_cache(maxsize=1)
def _load_rules() -> dict:
    """Load cv/variants/variants.json. Returns {} if missing or invalid."""
    if not RULES_PATH.exists():
        return {}
    try:
        with RULES_PATH.open() as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


@lru_cache(maxsize=1)
def get_default_variant() -> str:
    """Resolve the default CV variant.

    Order: variants.json default_variant, then search_config.json
    cv.default_variant, then "general".
    """
    rules = _load_rules()
    if rules.get("default_variant"):
        return str(rules["default_variant"])
    try:
        from user_config import load_search_config
        configured = load_search_config().get("cv", {}).get("default_variant")
        if configured:
            return str(configured)
    except SystemExit:
        pass  # config missing; fall through to the generic default
    except Exception:
        pass
    return FALLBACK_VARIANT


def _variant_rules() -> list[tuple[str, str, str]]:
    """Return the ordered (pattern, variant, reason) list from variants.json."""
    out: list[tuple[str, str, str]] = []
    for rule in _load_rules().get("rules") or []:
        if not isinstance(rule, dict):
            continue
        variant = rule.get("variant")
        if not variant:
            continue
        reason = rule.get("reason") or variant
        for pattern in rule.get("title_patterns") or []:
            out.append((pattern, variant, reason))
    return out


def _swaps() -> dict:
    swaps = _load_rules().get("swaps")
    return swaps if isinstance(swaps, dict) else {}


def _load_intelligence() -> dict:
    """Load the intelligence file (cached for the process lifetime)."""
    global _intelligence_cache
    if _intelligence_cache is not None:
        return _intelligence_cache
    if not INTELLIGENCE_PATH.exists():
        _intelligence_cache = {}
        return _intelligence_cache
    try:
        with INTELLIGENCE_PATH.open() as f:
            _intelligence_cache = json.load(f)
    except (json.JSONDecodeError, OSError):
        _intelligence_cache = {}
    return _intelligence_cache


def _load_caps() -> dict:
    """Load seniority caps. Returns empty dict if file missing (cap will be None)."""
    if not CAPS_PATH.exists():
        return {}
    with CAPS_PATH.open() as f:
        return json.load(f)


def _matches_swap_context(description: str | None) -> bool:
    if not description:
        return False
    for pat in _swaps().get("context_patterns") or []:
        try:
            if re.search(pat, description, flags=re.IGNORECASE):
                return True
        except re.error:
            continue
    return False


def _apply_intelligence_boost(
    variant: str, reason: str, title: str, description: str | None,
) -> tuple[str, str]:
    """Check intelligence data for a better variant based on outcome evidence.

    Only swaps when: (a) the current variant has a measured response rate below
    10% with at least 5 resolved outcomes, AND (b) a boost candidate exists with
    at least 2 submissions and a response rate above 20%.
    """
    intel = _load_intelligence()
    if not intel:
        return variant, reason

    outcomes = intel.get("variant_outcomes", {})
    current_stats = outcomes.get(variant, {})
    current_rate = current_stats.get("response_rate")
    current_resolved = (current_stats.get("positive", 0) + current_stats.get("rejected", 0))

    if current_rate is not None and current_rate >= 0.10:
        return variant, reason
    if current_resolved < 5:
        return variant, reason

    boosts = intel.get("variant_boosts", [])
    if not boosts:
        return variant, reason

    for boost in boosts:
        candidate = boost.get("preferred_variant", "")
        candidate_rate = boost.get("response_rate", 0)
        candidate_n = boost.get("sample_size", 0)
        if candidate_rate >= 0.20 and candidate_n >= 2:
            tex_path = TEX_DIR / f"{candidate}.tex"
            pdf_path = PDF_DIR / f"{candidate}.pdf"
            if tex_path.exists() or pdf_path.exists():
                boosted_reason = (
                    f"{reason} -> intelligence boost to {candidate} "
                    f"({boost.get('evidence', 'outcome data')})"
                )
                return candidate, boosted_reason

    return variant, reason


def _build_result(variant: str, reason: str, caps: dict) -> dict:
    cap_entry = caps.get(variant, {})
    return {
        "variant": variant,
        "pdf_path": str((PDF_DIR / f"{variant}.pdf").relative_to(PROJECT_ROOT)),
        "tex_path": str((TEX_DIR / f"{variant}.tex").relative_to(PROJECT_ROOT)),
        "max_years": cap_entry.get("max_years"),
        "cap_rationale": cap_entry.get("rationale"),
        "reason": reason,
    }


def select_variant(title: str, description: str | None = None) -> dict:
    """Return the best CV variant for the given job title, with seniority cap.

    Args:
        title: job title string (required)
        description: optional JD body for context-swap detection
    """
    caps = _load_caps()
    default_variant = get_default_variant()

    if not _load_rules():
        return _build_result(
            default_variant,
            "cv/variants/variants.json not found; using default variant "
            "(run /onboard to generate matching rules)",
            caps,
        )

    if not title:
        return _build_result(default_variant, "empty title; using default", caps)

    matched_variant: str | None = None
    matched_reason = f"no title pattern matched, defaulting to {default_variant}"

    for pattern, variant, reason in _variant_rules():
        try:
            if re.search(pattern, title, flags=re.IGNORECASE):
                matched_variant = variant
                matched_reason = f"matched /{pattern}/ -> {reason}"
                break
        except re.error:
            continue

    if matched_variant is None:
        matched_variant = default_variant

    # Context swap: if the JD matches the swap context patterns and the
    # matched variant has a mapped alternative, prefer the alternative.
    variant_map = _swaps().get("variant_map") or {}
    if matched_variant in variant_map and _matches_swap_context(description):
        swapped = variant_map[matched_variant]
        label = _swaps().get("label", "swap context")
        matched_reason = f"{matched_reason} + {label} -> swapped to {swapped}"
        matched_variant = swapped

    # Intelligence-based boost: if the matched variant has a poor response rate
    # and a better variant exists for this type of role, swap to it.
    matched_variant, matched_reason = _apply_intelligence_boost(
        matched_variant, matched_reason, title, description,
    )

    return _build_result(matched_variant, matched_reason, caps)


def lookup_cap(variant: str) -> dict:
    """Look up just the cap entry for a known variant. Returns {} if unknown."""
    return _load_caps().get(variant, {})


def cmd_select(args) -> int:
    result = select_variant(args.title, args.description)
    print(json.dumps(result, indent=2))
    pdf = PROJECT_ROOT / result["pdf_path"]
    if not pdf.exists():
        print(f"WARNING: variant PDF does not exist at {pdf}", file=sys.stderr)
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Select CV variant from job title")
    parser.add_argument("--title", required=True)
    parser.add_argument("--description", default=None,
                        help="Optional JD body for context-swap detection")
    parser.set_defaults(func=cmd_select)
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
