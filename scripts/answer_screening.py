"""Screening-question answerer for the /apply-job pipeline.

Matches incoming screening questions against the canonical answers in
data/application_profile.json. Returns structured answers with a confidence
score. Low-confidence matches are flagged for human review.

Design:
- No LLM calls. Pure rule-based matching against pre-computed facts.
- When a question doesn't match any hint, it is returned with
  confidence=0 and needs_human=True. The /apply-job skill then decides
  whether Claude should reason over deep_experience.json or pause for
  human input.

Usage:
  # Single question
  python scripts/answer_screening.py ask "How many years of Python?"

  # Batch from JSON file (list of {"id": str, "question": str, "type": "text|number|yes_no|select", "options": [...]})
  python scripts/answer_screening.py batch questions.json [--country France]

  # Dump the full profile as JSON
  python scripts/answer_screening.py profile
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = PROJECT_ROOT / "data" / "application_profile.json"


def load_profile() -> dict:
    with PROFILE_PATH.open() as f:
        return json.load(f)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _match_any(patterns: list[str], text: str) -> bool:
    for p in patterns:
        if re.search(p, text, flags=re.IGNORECASE):
            return True
    return False


def answer_years_experience(question: str, profile: dict) -> dict | None:
    """Detect 'years of X' questions and look up X in the skills table."""
    if not _match_any(profile["question_matching_hints"]["years_experience_regex_hints"], question):
        return None

    skills = profile["experience_years"]["by_skill"]
    q = _normalise(question)

    best_skill = None
    best_len = 0
    for skill, years in skills.items():
        if skill.lower() in q and len(skill) > best_len:
            best_skill = skill
            best_len = len(skill)

    if best_skill is None:
        return {
            "answer": profile["experience_years"]["overall_professional"],
            "confidence": 0.4,
            "rationale": "No specific skill matched; defaulting to overall years of professional experience.",
            "needs_human": True,
        }

    years = skills[best_skill]
    return {
        "answer": years,
        "confidence": 0.9,
        "rationale": f"Matched skill '{best_skill}' in experience_years.by_skill.",
        "needs_human": False,
    }


def answer_authorisation(question: str, profile: dict, country: str | None) -> dict | None:
    if not _match_any(profile["question_matching_hints"]["authorisation_regex_hints"], question):
        return None

    q = _normalise(question)

    countries = profile["citizenship_and_authorisation"]["by_country"]
    inferred_country = None
    for c in countries:
        if c.lower() in q:
            inferred_country = c
            break
    if inferred_country is None and re.search(r"\bu\.?s\.?\b|united states|america", q):
        inferred_country = "United States"
    if inferred_country is None and re.search(r"u\.?k\.?|united kingdom|britain", q):
        inferred_country = "United Kingdom"
    if inferred_country is None and re.search(r"\beu\b|european union|europe\b|europe without sponsorship", q):
        inferred_country = "European Union"
    if inferred_country is None:
        inferred_country = country

    if inferred_country is None:
        return {
            "answer": None,
            "confidence": 0.3,
            "rationale": "Authorisation question detected but country ambiguous — caller should pass --country matching the job location.",
            "needs_human": True,
        }

    row = countries.get(inferred_country)
    if row is None:
        return {
            "answer": None,
            "confidence": 0.2,
            "rationale": f"No profile row for country '{inferred_country}'.",
            "needs_human": True,
        }

    sponsorship_phrased = re.search(r"sponsor", q)
    if sponsorship_phrased:
        return {
            "answer": "Yes" if row["requires_sponsorship_now"] else "No",
            "confidence": 0.95,
            "rationale": f"Sponsorship question for {inferred_country}. Profile says requires_sponsorship_now={row['requires_sponsorship_now']}.",
            "needs_human": False,
            "notes": row.get("notes", ""),
        }
    return {
        "answer": "Yes" if row["authorised_to_work"] else "No",
        "confidence": 0.95,
        "rationale": f"Right-to-work question for {inferred_country}. Profile says authorised_to_work={row['authorised_to_work']}.",
        "needs_human": False,
        "notes": row.get("notes", ""),
    }


def answer_compensation(question: str, profile: dict, country: str | None) -> dict | None:
    if not _match_any(profile["question_matching_hints"]["compensation_regex_hints"], question):
        return None

    return {
        "answer": None,
        "kind": "compute_salary_per_role",
        "confidence": 0.95,
        "rationale": "Salary expectation requires role/company/location-specific research before submission.",
        "needs_human": False,
    }


def answer_notice(question: str, profile: dict) -> dict | None:
    if not _match_any(profile["question_matching_hints"]["notice_regex_hints"], question):
        return None
    return {
        "answer": profile["availability"]["notice_period_text"],
        "weeks": profile["availability"]["notice_period_weeks"],
        "confidence": 0.95,
        "rationale": "Notice period / start date question matched.",
        "needs_human": False,
    }


def answer_relocation(question: str, profile: dict) -> dict | None:
    if not _match_any(profile["question_matching_hints"]["location_regex_hints"], question):
        return None
    return {
        "answer": "Yes" if profile["availability"]["willing_to_relocate"] else "No",
        "preferences": profile["availability"]["relocation_preferences"],
        "confidence": 0.9,
        "rationale": "Location/relocation question matched.",
        "needs_human": False,
    }


def answer_demographic(question: str, profile: dict) -> dict | None:
    q = _normalise(question)
    demo = profile["demographic_optional"]

    mapping = [
        (r"veteran", demo["veteran_status"]),
        (r"disab", demo["disability_status"]),
        (r"ethnic|race", demo["ethnicity"]),
        (r"gender identity|gender$", demo["gender_identity"]),
        (r"sexual orientation|lgbt", demo["sexual_orientation"]),
    ]
    for pattern, value in mapping:
        if re.search(pattern, q):
            return {
                "answer": value,
                "confidence": 0.85,
                "rationale": f"Demographic question matched pattern /{pattern}/.",
                "needs_human": False,
            }
    return None


def _edu_unknown(aspect: str) -> dict:
    """Low-confidence escalation when the education block lacks a field."""
    return {
        "answer": None,
        "confidence": 0.2,
        "rationale": f"Education question matched but application_profile.json "
                     f"education block has no '{aspect}' information.",
        "needs_human": True,
    }


def _highest_level_rank(edu: dict) -> int | None:
    """Rank the profile's highest education level: 1=bachelor, 2=master, 3=phd.

    Uses the boolean flags when present, falling back to parsing the
    highest_level string. Returns None when nothing is stated.
    """
    if edu.get("has_phd"):
        return 3
    if edu.get("has_masters"):
        return 2
    if edu.get("has_bachelors"):
        return 1
    level = str(edu.get("highest_level", "")).lower()
    if not level:
        return None
    if re.search(r"phd|ph\.d|doctor", level):
        return 3
    if re.search(r"master|msc|mba|postgrad", level):
        return 2
    if re.search(r"bachelor|bsc|\bba\b|beng|undergrad|degree", level):
        return 1
    return None


def answer_education(question: str, profile: dict) -> dict | None:
    """Answer questions about education level / degree completion.

    All answers are derived from the application_profile.json education
    block: degree, field, grade, has_bachelors/has_masters/has_phd,
    highest_level, and optionally institution / graduation_year. When the
    profile lacks the relevant field, a low-confidence result is returned
    so the caller escalates instead of guessing.
    """
    q = _normalise(question)
    if not re.search(r"educat|degree|bachelor|master|phd|doctorate|graduate|undergrad|diploma|university|college", q):
        return None
    edu = profile.get("education", {})
    level_rank = _highest_level_rank(edu)

    # Degree classification / distinction check
    if re.search(r"1st class|first class|distinction", q):
        grade = str(edu.get("grade") or edu.get("gpa_uk_classification") or "")
        if not grade:
            return _edu_unknown("grade")
        is_first = bool(re.search(r"first|1st|distinction", grade, re.IGNORECASE))
        return {
            "answer": "Yes" if is_first else "No",
            "confidence": 0.95,
            "rationale": f"Degree classification is {grade!r}.",
            "needs_human": False,
        }

    # Field-of-study check (e.g. "Do you have a Computer Science degree?")
    if re.search(r"computer science|\bcs\b", q):
        field = str(edu.get("field") or edu.get("degree") or "")
        if not field:
            return _edu_unknown("field")
        is_cs = bool(re.search(r"computer science|computing", field, re.IGNORECASE))
        return {
            "answer": "Yes" if is_cs else "No",
            "confidence": 0.95,
            "rationale": f"Degree/field is {field!r}.",
            "needs_human": False,
        }

    if re.search(r"phd|doctorate", q):
        if "has_phd" not in edu and level_rank is None:
            return _edu_unknown("has_phd")
        has_phd = bool(edu.get("has_phd")) or (level_rank or 0) >= 3
        return {
            "answer": "Yes" if has_phd else "No",
            "confidence": 0.95,
            "rationale": f"PhD check from education block: {has_phd}.",
            "needs_human": False,
        }
    if re.search(r"master|postgrad|msc|mba|graduate degree", q):
        if "has_masters" not in edu and level_rank is None:
            return _edu_unknown("has_masters")
        has_masters = bool(edu.get("has_masters")) or (level_rank or 0) >= 2
        return {
            "answer": "Yes" if has_masters else "No",
            "confidence": 0.95,
            "rationale": f"Master's check from education block: {has_masters}.",
            "needs_human": False,
        }
    if re.search(r"bachelor|undergraduate|bsc\b|ba\b|bs\b|4.year|university degree|college degree", q):
        if level_rank is None:
            return _edu_unknown("highest_level")
        has_bachelors = level_rank >= 1
        detail = " ".join(
            str(edu[k]) for k in ("degree", "institution", "graduation_year") if edu.get(k)
        )
        return {
            "answer": "Yes" if has_bachelors else "No",
            "confidence": 0.95,
            "rationale": (
                f"Bachelor's check from education block: {detail}."
                if detail else "Bachelor's check from education block highest_level."
            ),
            "needs_human": False,
        }
    if re.search(r"highest level|level of education|degree level|education level", q):
        if not edu.get("highest_level"):
            return _edu_unknown("highest_level")
        return {
            "answer": edu["highest_level"],
            "confidence": 0.90,
            "rationale": f"Highest education level: {edu['highest_level']}.",
            "needs_human": False,
        }
    return None


def answer_yes_no_common(question: str, profile: dict) -> dict | None:
    """Answer common yes/no questions strictly from profile-supplied facts.

    Two sources, both in application_profile.json:
      - misc_common_questions: named boolean/text facts (18+, criminal record,
        background check, and so on).
      - question_matching_hints.custom_yes_no_rules: a list of
        {"pattern": <regex>, "answer": <str>} entries for candidate-specific
        regex-to-answer rules (e.g. residency history, security clearance
        eligibility, startup experience). The code never bakes in personal
        facts; anything not supplied by the profile falls through to the
        needs_human escalation path.
    """
    q = _normalise(question)
    misc = profile.get("misc_common_questions", {})

    rules: list[tuple[str, str]] = []
    for pattern, key in [
        (r"18 (years )?or older|at least 18", "are_you_18_or_older"),
        (r"worked (here|for|at).*before|previously employed", "have_you_worked_here_before"),
        (r"criminal (record|conviction)|convicted of", "have_criminal_record"),
        (r"background check", "willing_to_take_background_check"),
        (r"drug (test|screen)", "willing_to_take_drug_test"),
        (r"intellectual property|ip assignment", "willing_to_sign_ip_assignment"),
        # availability / employment status
        (r"start immediately|available (to start|immediately)|can you start", "can_start_immediately"),
        (r"currently employed|currently working|are you employed|still employed", "are_currently_employed"),
    ]:
        if key in misc:
            rules.append((pattern, "Yes" if misc[key] else "No"))
    if misc.get("how_did_you_hear_about_us"):
        rules.append((r"how did you hear", misc["how_did_you_hear_about_us"]))
    # An applicant actively submitting applications is, by definition, looking.
    rules.append((r"actively (looking|seeking|searching)|open to (new )?opportunit", "Yes"))

    # Candidate-specific regex-to-answer rules supplied by the profile.
    for entry in profile.get("question_matching_hints", {}).get("custom_yes_no_rules", []):
        if isinstance(entry, dict) and entry.get("pattern") and entry.get("answer") is not None:
            rules.append((entry["pattern"], str(entry["answer"])))

    for pattern, value in rules:
        try:
            matched = re.search(pattern, q)
        except re.error:
            continue
        if matched:
            return {
                "answer": value,
                "confidence": 0.90,
                "rationale": f"Matched common-question pattern /{pattern}/.",
                "needs_human": False,
            }
    return None


ANSWERERS = [
    answer_years_experience,
    answer_education,
    answer_demographic,
    answer_yes_no_common,
]

# Generic country-to-currency mapping used by verified_form_answers entries
# that carry an answer_by_currency table. Unknown countries fall back to the
# entry's own "default" value.
_COUNTRY_CURRENCY = {
    "United Kingdom": "GBP",
    "France": "EUR", "Germany": "EUR", "Spain": "EUR", "Italy": "EUR",
    "Netherlands": "EUR", "Belgium": "EUR", "Austria": "EUR",
    "Ireland": "EUR", "Portugal": "EUR", "Luxembourg": "EUR",
    "European Union": "EUR",
    "Switzerland": "CHF",
    "United States": "USD",
    "Canada": "CAD",
    "Australia": "AUD",
    "Sweden": "SEK", "Denmark": "DKK", "Norway": "NOK",
    "Poland": "PLN",
    "Japan": "JPY",
    "Singapore": "SGD",
    "India": "INR",
}


def answer_verified_form_label(question: str, profile: dict, country: str | None = None) -> dict | None:
    """Try the verified_form_answers exact-label table first.

    This block (in application_profile.json) is the authoritative lookup for
    LinkedIn Apply / ATS form labels seen in real submissions. It compounds
    over runs as new labels are added. Match by exact label first, then by
    substring (only entries explicitly marked match_by_substring=true).
    """
    table = profile.get("verified_form_answers", {})
    if not table:
        return None
    q_norm = _normalise(question)
    # 1. Exact match (case-insensitive)
    entry = None
    for label, e in table.items():
        if label.startswith("_"):
            continue
        if isinstance(e, dict) and _normalise(label) == q_norm:
            entry = (label, e)
            break
    # 2. Substring match for entries that opted in
    if entry is None:
        for label, e in table.items():
            if label.startswith("_") or not isinstance(e, dict):
                continue
            if e.get("match_by_substring") and _normalise(label) in q_norm:
                entry = (label, e)
                break
    if entry is None:
        return None

    label, e = entry
    kind = e.get("kind", "fill_text")

    # Resolve answer with country/currency dispatch. When the caller passes
    # no country, fall back to the candidate's residence country from the
    # profile rather than assuming any particular one.
    residence = profile.get("citizenship_and_authorisation", {}).get(
        "current_residence_country", ""
    )
    effective_country = country or residence
    answer = e.get("answer")
    if answer is None and "answer_by_country" in e:
        answer = e["answer_by_country"].get(
            effective_country, e["answer_by_country"].get("default")
        )
    if answer is None and "answer_by_currency" in e:
        currency = _COUNTRY_CURRENCY.get(effective_country, "")
        answer = e["answer_by_currency"].get(currency, e["answer_by_currency"].get("default"))
    if answer is None and "answer_typed" in e:
        answer = e["answer_typed"]

    return {
        "answer": answer,
        "kind": kind,
        "confidence": 0.98,
        "rationale": f"Exact-label match on verified_form_answers['{label}'].",
        "needs_human": False,
        "matched_label": label,
        **{k: v for k, v in e.items() if k in ("preferred_option_substring", "note")},
    }


def answer_question(question: str, profile: dict, country: str | None = None) -> dict:
    # 0. Verified form-answer table first — highest confidence, label-precise.
    result = answer_verified_form_label(question, profile, country)
    if result is not None:
        return {"question": question, **result}
    # 1. Authorisation / compensation / notice / relocation need the country arg
    for fn in (answer_authorisation,):
        result = fn(question, profile, country)
        if result is not None:
            return {"question": question, **result}
    for fn in (answer_compensation,):
        result = fn(question, profile, country)
        if result is not None:
            return {"question": question, **result}
    for fn in (answer_notice, answer_relocation):
        result = fn(question, profile)
        if result is not None:
            return {"question": question, **result}
    for fn in ANSWERERS:
        result = fn(question, profile)
        if result is not None:
            return {"question": question, **result}
    return {
        "question": question,
        "answer": None,
        "confidence": 0.0,
        "rationale": "No rule matched. Claude should reason over deep_experience.json or request human input.",
        "needs_human": True,
    }


def cmd_ask(args) -> int:
    profile = load_profile()
    result = answer_question(args.question, profile, args.country)
    print(json.dumps(result, indent=2))
    return 0


def cmd_batch(args) -> int:
    profile = load_profile()
    with open(args.questions_file) as f:
        questions = json.load(f)
    results = []
    for q in questions:
        text = q["question"] if isinstance(q, dict) else str(q)
        qid = q.get("id") if isinstance(q, dict) else None
        answer = answer_question(text, profile, args.country)
        if qid:
            answer["id"] = qid
        if isinstance(q, dict):
            for k in ("type", "options", "required"):
                if k in q:
                    answer[k] = q[k]
        results.append(answer)
    print(json.dumps(results, indent=2))
    return 0


def cmd_profile(args) -> int:
    print(json.dumps(load_profile(), indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Screening-question answerer")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_ask = sub.add_parser("ask")
    p_ask.add_argument("question")
    p_ask.add_argument("--country", default=None)
    p_ask.set_defaults(func=cmd_ask)

    p_batch = sub.add_parser("batch")
    p_batch.add_argument("questions_file")
    p_batch.add_argument("--country", default=None)
    p_batch.set_defaults(func=cmd_batch)

    p_prof = sub.add_parser("profile")
    p_prof.set_defaults(func=cmd_profile)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
