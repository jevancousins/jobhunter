"""Quick deterministic filter for the auto-apply pipeline.

Replaces the LLM-driven /review-job pre-screen with a fast, mostly deterministic
APPLY/SKIP decision based on:

  1. Hard gates: industry dealbreakers, visa, education, years, language,
     contract type
  2. Title check: blacklist + light whitelist signal
  3. Competitiveness score: years gap + must-have skill overlap

All personal tuning comes from data/search_config.json (see
data/search_config.example.json and the /onboard skill):

  filters.title_blacklist        titles never to apply to
  filters.title_whitelist        positive title signal (scoring, not a gate)
  filters.industry_dealbreakers  industries never to apply to
  filters.skip_contract_types    contract types to skip (internship, stage, ...)
  filters.required_language_ok   languages the candidate can work in
  filters.home_location_patterns extra location substrings treated as home
                                 (city names, abbreviations like "UK")
  filters.lacking_skills         skills/languages the candidate lacks; JDs
                                 requiring 2+ years of one are skipped
  candidate.home_countries       countries with existing right to work
  candidate.needs_sponsorship_in countries needing a visa (scrutiny path)

Patterns in the config are case-insensitive substrings unless prefixed with
're:' for a raw regex.

Candidate facts (skills, education level, total experience years) come from
data/job_goals.json.

Designed to run in <100ms per role with no model calls. Use this in the
daily-watchlist-search and auto-apply skills.

Usage:
  python scripts/quick_filter.py check \
      --title "Senior Data Engineer" \
      --location "Toronto" \
      --description-file path/to/jd.txt
      [--threshold 10]

  python scripts/quick_filter.py check-json --input job.json

Output (JSON on stdout):
  {
    "verdict": "APPLY" | "SKIP",
    "reason": "...",
    "competitiveness": {"total": 14, "years": 4, "skills": 3},
    "hard_gates_triggered": [],
    "title_signals": {"blacklisted": false, "whitelisted": true, "matched_terms": [...]},
    "elapsed_ms": 12
  }

Exit codes:
  0 = APPLY
  1 = SKIP (any reason)
  2 = error / bad input
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from functools import lru_cache
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from user_config import load_search_config  # noqa: E402

PROJECT_ROOT = Path(__file__).resolve().parents[1]
GOALS_PATH = PROJECT_ROOT / "data" / "job_goals.json"


# ---------------------------------------------------------------------------
# Config-driven pattern banks
# ---------------------------------------------------------------------------

def _filters() -> dict:
    return load_search_config().get("filters", {})


def _candidate_cfg() -> dict:
    return load_search_config().get("candidate", {})


def _compile_pattern(raw: str) -> re.Pattern:
    """Compile one config pattern.

    Plain strings are case-insensitive substring matches; the 're:' prefix
    marks a raw regular expression.
    """
    if raw.startswith("re:"):
        return re.compile(raw[3:], re.IGNORECASE)
    return re.compile(re.escape(raw), re.IGNORECASE)


@lru_cache(maxsize=None)
def _filter_patterns(key: str) -> tuple[re.Pattern, ...]:
    """Compiled patterns for a filters.<key> list. Missing key -> empty tuple."""
    raw = _filters().get(key) or []
    return tuple(_compile_pattern(p) for p in raw)


@lru_cache(maxsize=1)
def _home_location_patterns() -> tuple[re.Pattern, ...]:
    """Patterns identifying a location inside a home country.

    Derived from candidate.home_countries (country names matched as whole
    words) plus any extra substrings in filters.home_location_patterns
    (city names, abbreviations such as "UK", "remote (uk)").
    """
    pats: list[re.Pattern] = []
    for country in _candidate_cfg().get("home_countries") or []:
        pats.append(re.compile(r"\b" + re.escape(country) + r"\b", re.IGNORECASE))
    for extra in _filters().get("home_location_patterns") or []:
        pats.append(_compile_pattern(extra))
    return tuple(pats)


# ---------------------------------------------------------------------------
# Generic pattern banks (not personal; kept in code)
# ---------------------------------------------------------------------------

# Description-level required-years gate for skills the candidate lacks
# (filters.lacking_skills). Triggers when the JD asks for X+ years of such a
# skill. Threshold is 2 years: 1-year mentions may be incidental; 2+ signals
# a core requirement.
_LACKING_SKILL_YEARS_THRESHOLD = 2


def _skill_token_regex(skill: str) -> str:
    """Whole-token regex for a skill name. Uses lookarounds instead of \\b so
    names ending in non-word characters (C++, C#) still anchor correctly."""
    return r"(?<![A-Za-z0-9])" + re.escape(skill) + r"(?![A-Za-z0-9])"


@lru_cache(maxsize=1)
def _lacking_skill_years_patterns() -> tuple[tuple[re.Pattern, str], ...]:
    out: list[tuple[re.Pattern, str]] = []
    for skill in _filters().get("lacking_skills") or []:
        pat = re.compile(
            r"\b(\d{1,2})\s*\+?\s*years?\s+(?:of\s+)?(?:experience\s+(?:with|in)\s+)?"
            + _skill_token_regex(skill),
            re.IGNORECASE,
        )
        out.append((pat, skill))
    return tuple(out)


# Education hard-gate triggers: JD requires a Master's/PhD as a MUST.
# Distinguish from "preferred" / "ideal" / "or equivalent experience".
# The wide-window patterns (degree word + up to 60 non-period chars + 'required')
# catch phrasings like "MSc in Computer Science required". Period boundary stops
# the regex from straddling sentences (e.g. "MSc preferred. Skills required.").
EDUCATION_REQUIRED_PATTERNS = [
    r"\b(msc|m\.sc\.|master'?s?\s+degree|master'?s?)\s+(degree\s+)?(is\s+)?required\b",
    r"\b(msc|m\.sc\.|master'?s?|phd|ph\.d\.|doctorate|advanced\s+degree)\b[^.]{0,60}\brequired\b",
    r"\brequires?\s+a?\s*master'?s?\b",
    r"\b(phd|ph\.d\.|doctorate|doctoral)\s+(degree\s+)?(is\s+)?required\b",
    r"\brequires?\s+a?\s*(phd|ph\.d\.|doctorate)\b",
    r"\b(must\s+have|need\s+to\s+have)\s+a?\s*(master'?s?|msc|phd)\b",
    r"\badvanced\s+degree\s+(is\s+)?required\b",
]

# Patterns that explicitly invalidate the education hard gate (JD says
# preferred / OK with bachelor).
EDUCATION_RELAXED_PATTERNS = [
    r"master'?s?\s+(or|degree)?\s*preferred\b",
    r"\bmsc\s+preferred\b",
    r"\bphd\s+(is\s+)?(a\s+)?(plus|preferred|nice\s+to\s+have)\b",
    r"\bor\s+equivalent\s+experience\b",
    r"\bbachelor'?s?\s+(degree\s+)?(is\s+)?required\b",
    r"\bbsc\s+required\b",
    r"\bbsc\s+acceptable\b",
]

# Years-required extraction. Captures 1-99. The hard gate is applied in
# check_years(); the incremental scorer uses the same value.
# Rules of thumb:
#   - Capture the UPPER end of ranges (e.g. "6-10 years" -> 10)
#   - Allow one optional adjective between "years" and "experience"
#     (e.g. "5 years relevant experience", "8 years industry experience")
#   - Allow "years of [skill] experience" (e.g. "10 years of Python experience")
YEARS_REQUIRED_PATTERNS = [
    # "X+ years" — simplest form
    r"\b(\d{1,2})\s*\+\s*years?\b",
    # Explicit minimum / at-least phrasings
    r"\bminimum\s+(?:of\s+)?(\d{1,2})\s+years?\b",
    r"\bat\s+least\s+(\d{1,2})\s+years?\b",
    r"\bbetween\s+\d{1,2}\s+and\s+(\d{1,2})\s+years?\b",
    # Upper end of dash/to ranges: "6-10 years", "6 to 10 years"
    r"\b\d{1,2}\s*[-–]\s*(\d{1,2})\s+years?\b",
    r"\b\d{1,2}\s+to\s+(\d{1,2})\s+years?\b",
    # "X years of experience" / "X years of [skill] experience"
    r"\b(\d{1,2})\s+years?\s+of\s+(?:\w+\s+)?(?:experience|exp)\b",
    # "X years [adjective] experience" — single qualifying word before experience
    r"\b(\d{1,2})\s+years?\s+(?:\w+\s+)?(?:experience|exp)\b",
]

# Language names recognised by the native/bilingual language hard gate.
# The gate fires when the JD requires native or bilingual command of a
# language that is NOT in filters.required_language_ok.
_LANGUAGE_VOCAB = [
    "english", "french", "german", "spanish", "italian", "portuguese",
    "dutch", "polish", "swedish", "danish", "norwegian", "finnish",
    "mandarin", "chinese", "cantonese", "japanese", "korean",
    "arabic", "russian", "hebrew", "hindi", "turkish", "greek", "czech",
]


@lru_cache(maxsize=1)
def _language_hard_gate_patterns() -> tuple[re.Pattern, ...]:
    ok = {lang.lower() for lang in _filters().get("required_language_ok") or []}
    gated = [lang for lang in _LANGUAGE_VOCAB if lang not in ok]
    if not gated:
        return tuple()
    alt = "|".join(gated)
    pats = [
        re.compile(rf"\b(near-)?native\s+({alt})\b", re.IGNORECASE),
        re.compile(rf"\b({alt})\s+(mother\s*tongue|mother-tongue|native\s+speaker)\b", re.IGNORECASE),
        re.compile(rf"\bbilingual\s+({alt})\b", re.IGNORECASE),
    ]
    # French JDs often state the requirement in French itself.
    if "french" not in ok:
        pats.append(re.compile(r"\bfran[cç]ais\s+langue\s+maternelle\b", re.IGNORECASE))
    return tuple(pats)


# Visa / sponsorship hard gate triggers (combined with a non-home location).
VISA_NO_SPONSORSHIP_PATTERNS = [
    r"\bno\s+(visa\s+)?sponsorship\b",
    r"\b(visa\s+)?sponsorship\s+(is\s+)?not\s+(available|provided|offered)\b",
    r"\bmust\s+have\s+(existing|the)\s+right\s+to\s+work\b",
    r"\bauthori[sz]ed\s+to\s+work\s+in\s+",
    r"\blocal\s+candidates\s+only\b",
]


def load_goals() -> dict:
    if not GOALS_PATH.exists():
        raise SystemExit(
            "data/job_goals.json not found. Run /onboard to generate it, or copy "
            "data/job_goals.example.json and fill it in."
        )
    with GOALS_PATH.open() as f:
        return json.load(f)


def _extract_required_years(description: str) -> int | None:
    """Extract the highest 'X+ years required' figure from the JD. Returns None if not found."""
    matches: list[int] = []
    for pat in YEARS_REQUIRED_PATTERNS:
        for m in re.finditer(pat, description, flags=re.IGNORECASE):
            for group in m.groups():
                if group and group.isdigit():
                    matches.append(int(group))
                    break
    if not matches:
        return None
    return max(matches)


def _candidate_total_years(profile: dict) -> int | None:
    """Total professional experience from job_goals.json (experience_years)."""
    years = profile.get("experience_years")
    if isinstance(years, (int, float)) and years > 0:
        return int(years)
    return None


def _candidate_degree_rank(profile: dict) -> int:
    """Rank the candidate's education level: 1=bachelor, 2=master, 3=phd.

    Parsed from job_goals.json candidate_profile.education.level. Defaults to
    bachelor when the level is missing or unrecognised (conservative: the
    Master's/PhD hard gate then applies).
    """
    level = str(
        profile.get("candidate_profile", {}).get("education", {}).get("level", "")
    ).lower()
    if re.search(r"phd|ph\.d|doctor", level):
        return 3
    if re.search(r"\bmsc\b|\bmba\b|master|postgrad", level):
        return 2
    return 1


def _is_home_location(location: str) -> bool:
    if not location:
        return False
    return any(p.search(location) for p in _home_location_patterns())


def check_industry_dealbreaker(text: str) -> str | None:
    for pat in _filter_patterns("industry_dealbreakers"):
        m = pat.search(text)
        if m:
            return f"industry dealbreaker: {m.group(0)!r}"
    return None


def check_contract_type(text: str) -> str | None:
    """Hard-gate contract types listed in filters.skip_contract_types
    (e.g. internship, apprenticeship, stage, alternance, VIE)."""
    for pat in _filter_patterns("skip_contract_types"):
        m = pat.search(text)
        if m:
            return f"skipped contract type: {m.group(0)!r}"
    return None


def check_lacking_skill_years(description: str) -> str | None:
    """Hard-gate when the JD requires 2+ years of a skill the candidate lacks
    (filters.lacking_skills)."""
    for pat, skill in _lacking_skill_years_patterns():
        for m in pat.finditer(description):
            for g in m.groups():
                if g and g.isdigit() and int(g) >= _LACKING_SKILL_YEARS_THRESHOLD:
                    return f"requires {g}+ years {skill} (candidate does not have {skill})"
    return None


def check_visa(description: str, location: str) -> str | None:
    """Sponsorship gate.

    A role located in one of candidate.home_countries needs no sponsorship,
    so the gate is skipped. Any other location (including the countries in
    candidate.needs_sponsorship_in) gets the visa scrutiny path: the role is
    skipped when the JD explicitly rules out sponsorship.
    """
    if _is_home_location(location):
        return None  # candidate already has the right to work here
    for pat in VISA_NO_SPONSORSHIP_PATTERNS:
        m = re.search(pat, description, flags=re.IGNORECASE)
        if m:
            return (
                f"no visa sponsorship + location outside home countries "
                f"({location!r}): {m.group(0)!r}"
            )
    return None


def check_education(description: str, profile: dict) -> str | None:
    """Hard-gate JDs whose required degree level exceeds the candidate's."""
    candidate_rank = _candidate_degree_rank(profile)
    if candidate_rank >= 3:
        return None  # a PhD satisfies every degree requirement
    # If the JD explicitly relaxes the requirement, no hard gate.
    for pat in EDUCATION_RELAXED_PATTERNS:
        if re.search(pat, description, flags=re.IGNORECASE):
            return None
    for pat in EDUCATION_REQUIRED_PATTERNS:
        m = re.search(pat, description, flags=re.IGNORECASE)
        if m:
            matched = m.group(0).lower()
            required_rank = 3 if re.search(r"phd|ph\.d|doctor", matched) else 2
            if candidate_rank < required_rank:
                return f"Master's/PhD required: {m.group(0)!r}"
    return None


def check_years(description: str, title: str = "", profile: dict | None = None) -> str | None:
    """Hard-gate when the JD's required years exceed the variant-specific cap.

    The cap is the maximum years credibly claimable for the matched variant
    (see cv/variants/seniority_caps.json), with a 1-year tolerance.

    Falls back to the candidate's total experience years (job_goals.json
    experience_years) if the variant selector or caps file is unavailable.
    """
    yrs = _extract_required_years(description)
    if yrs is None:
        return None

    cap = None
    cap_source = "fallback (no variant)"
    try:
        from select_variant import select_variant as _sv  # type: ignore
        match = _sv(title or "", description)
        cap = match.get("max_years")
        if cap is not None:
            cap_source = f"variant '{match.get('variant')}' cap={cap}y"
    except Exception:
        cap = None

    if cap is None:
        # Legacy behaviour: gate on total experience years.
        total = _candidate_total_years(profile or {})
        if total is not None and yrs > total:
            return f"requires {yrs}+ years experience (candidate has {total})"
        return None

    tolerance = 1
    if yrs > cap + tolerance:
        return (
            f"requires {yrs}+ years experience but {cap_source} "
            f"(skip threshold > {cap + tolerance}y)"
        )
    return None


def check_language(description: str) -> str | None:
    for pat in _language_hard_gate_patterns():
        m = pat.search(description)
        if m:
            return f"native/bilingual language hard gate: {m.group(0)!r}"
    return None


def check_title_blacklist(title: str) -> list[str]:
    matched: list[str] = []
    for pat in _filter_patterns("title_blacklist"):
        m = pat.search(title)
        if m:
            matched.append(m.group(0))
    return matched


def check_title_whitelist(title: str) -> list[str]:
    matched: list[str] = []
    for pat in _filter_patterns("title_whitelist"):
        m = pat.search(title)
        if m:
            matched.append(m.group(0))
    return matched


def score_competitiveness(description: str, profile: dict, location: str) -> dict:
    """Deterministic competitiveness score (0-10).

    Components:
      - Years gap: 0-4. Penalty grows as the JD's required years approach the
        candidate's total (job_goals.json experience_years). Requirements
        above the cap are hard-gated in check_years(); this scorer only sees
        roles that passed.
      - Must-have skills coverage: 0-6 (the main determinant), from
        candidate_profile.strong_skills / developing_skills.
    """
    score = {"years": 0, "skills": 0, "total": 0}

    required_years = _extract_required_years(description)
    candidate_years = _candidate_total_years(profile)
    if required_years is None or required_years <= 1:
        score["years"] = 4  # no meaningful constraint
    elif candidate_years is not None:
        # Full marks when the requirement is far below the candidate's total,
        # scaling down to 1 point when it equals it.
        score["years"] = max(0, min(4, candidate_years + 1 - required_years))
    else:
        score["years"] = 2  # experience_years not configured: neutral

    # Must-have skills coverage — main determinant
    strong_skills = [s.lower() for s in profile["candidate_profile"].get("strong_skills", [])]
    developing_skills = [s.lower() for s in profile["candidate_profile"].get("developing_skills", [])]
    desc_lower = description.lower()

    strong_hits = sum(1 for s in strong_skills if s in desc_lower)
    developing_hits = sum(1 for s in developing_skills if s in desc_lower)

    if strong_hits >= 4:
        score["skills"] = 6
    elif strong_hits >= 2:
        score["skills"] = 5
    elif strong_hits >= 1:
        score["skills"] = 4
    elif developing_hits >= 1:
        score["skills"] = 2
    else:
        score["skills"] = 1  # not 0 — keep permissive bias on no-info JDs

    score["total"] = score["years"] + score["skills"]
    return score


def quick_filter(
    title: str,
    description: str,
    location: str,
    threshold: int = 5,
    profile_override: dict | None = None,
) -> dict:
    """Run the full quick filter and return a structured verdict.

    Args:
        title: Job title.
        description: Full JD text.
        location: City/region (used for the visa gate).
        threshold: Minimum competitiveness total to pass (default 5).
        profile_override: Inject a custom job_goals dict (for tests).

    Returns:
        Dict with verdict (APPLY|SKIP), reason, competitiveness scores,
        hard_gates_triggered, title_signals, elapsed_ms.
    """
    started = time.perf_counter()
    profile = profile_override or load_goals()

    combined_text = f"{title}\n{description}"

    hard_gates_triggered: list[str] = []
    for check_fn, args in [
        (check_industry_dealbreaker, (combined_text,)),
        (check_contract_type, (combined_text,)),
        (check_visa, (description, location)),
        (check_education, (description, profile)),
        (check_years, (description, title, profile)),
        (check_language, (description,)),
        (check_lacking_skill_years, (description,)),
    ]:
        result = check_fn(*args)
        if result:
            hard_gates_triggered.append(result)

    blacklist_hits = check_title_blacklist(title)
    whitelist_hits = check_title_whitelist(title)

    competitiveness = score_competitiveness(description, profile, location)

    title_signals = {
        "blacklisted": bool(blacklist_hits),
        "whitelisted": bool(whitelist_hits),
        "matched_blacklist_terms": blacklist_hits,
        "matched_whitelist_terms": whitelist_hits,
    }

    elapsed_ms = int((time.perf_counter() - started) * 1000)

    # Verdict logic — order matters.
    if hard_gates_triggered:
        return {
            "verdict": "SKIP",
            "reason": "; ".join(hard_gates_triggered),
            "competitiveness": competitiveness,
            "hard_gates_triggered": hard_gates_triggered,
            "title_signals": title_signals,
            "elapsed_ms": elapsed_ms,
        }
    if blacklist_hits:
        return {
            "verdict": "SKIP",
            "reason": f"title blacklist: {blacklist_hits}",
            "competitiveness": competitiveness,
            "hard_gates_triggered": [],
            "title_signals": title_signals,
            "elapsed_ms": elapsed_ms,
        }
    if competitiveness["total"] < threshold:
        return {
            "verdict": "SKIP",
            "reason": f"competitiveness {competitiveness['total']} < threshold {threshold}",
            "competitiveness": competitiveness,
            "hard_gates_triggered": [],
            "title_signals": title_signals,
            "elapsed_ms": elapsed_ms,
        }

    return {
        "verdict": "APPLY",
        "reason": "passed all gates",
        "competitiveness": competitiveness,
        "hard_gates_triggered": [],
        "title_signals": title_signals,
        "elapsed_ms": elapsed_ms,
    }


def cmd_check(args) -> int:
    if args.description_file:
        description = Path(args.description_file).read_text()
    elif args.description:
        description = args.description
    else:
        description = sys.stdin.read()
    result = quick_filter(args.title, description, args.location, threshold=args.threshold)
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "APPLY" else 1


def cmd_check_json(args) -> int:
    payload = json.loads(Path(args.input).read_text())
    result = quick_filter(
        title=payload["title"],
        description=payload.get("description", ""),
        location=payload.get("location", ""),
        threshold=args.threshold,
    )
    print(json.dumps(result, indent=2))
    return 0 if result["verdict"] == "APPLY" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Quick deterministic filter for auto-apply pipeline")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check")
    p_check.add_argument("--title", required=True)
    p_check.add_argument("--location", default="")
    p_check.add_argument("--description-file")
    p_check.add_argument("--description")
    p_check.add_argument("--threshold", type=int, default=5)
    p_check.set_defaults(func=cmd_check)

    p_json = sub.add_parser("check-json")
    p_json.add_argument("--input", required=True, help="Path to JSON with title/description/location")
    p_json.add_argument("--threshold", type=int, default=5)
    p_json.set_defaults(func=cmd_check_json)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
