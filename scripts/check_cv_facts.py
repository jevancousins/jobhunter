#!/usr/bin/env python3
"""Factual cross-reference check for CV LaTeX source.

Verifies that specific factual claims in a .tex file trace to data/master_cv.json.
This catches the most common hallucination patterns when CVs are AI-generated or
heavily tailored. Everything is derived from master_cv.json, so the validator
works for any candidate whose master CV follows the expected shape.

Claims validated:
  1. Education modules: each module name in "Relevant modules: ..." must exist
     in education[*].modules.* or education[*].modules_by_year.* (case- and
     dash-normalised match).
  2. Language levels: any explicit language-level claim must not exceed the
     level recorded in master_cv.json languages (e.g. claiming "fluent" when
     the master says "Proficient").
  3. Experience years: any "<N> years" claim near "experience" or "at
     <employer>" must equal experience_years from master_cv.json.
  4. Employer titles: each \\cventry{<company>}{<title>} for a company listed
     in master_cv.json must use the canonical title or one of the approved
     alternatives in that role's "title_variants" list.
  5. Employer dates: each \\cventry's date range must match the source role's
     start/end dates. When an employer has multiple roles in the master but
     the variant lists fewer entries (roles combined into one), the combined
     entry may instead span the union of that employer's periods.

Expected master_cv.json shape (per experience entry):
  {"company": "...", "title": "...", "title_variants": ["...", ...],
   "start_date": "Mon YYYY", "end_date": "Mon YYYY" | "Present", ...}

Usage:
    python scripts/check_cv_facts.py <tex_path> [<master_cv_json_path>]

Default master_cv path: data/master_cv.json relative to the project root.

Exit codes:
    0 = all checks passed
    1 = factual mismatch
    2 = invalid arguments / file missing
"""

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Violation:
    code: str
    message: str


def normalise_dashes(s: str) -> str:
    """Normalise hyphens, en-dashes (--), em-dashes (---), and unicode dashes
    to a single ASCII hyphen for comparison."""
    s = s.replace("---", "-").replace("--", "-")
    for ch in ("‐", "‑", "‒", "–", "—"):
        s = s.replace(ch, "-")
    return s


_LATEX_ESCAPE_IN_TEXT = re.compile(r"\\([&%$#_{}~^])")


def normalise_for_module_match(s: str) -> str:
    s = _LATEX_ESCAPE_IN_TEXT.sub(r"\1", s)  # \& -> &, \% -> %, etc.
    s = normalise_dashes(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s.lower()


def normalise_title(s: str) -> str:
    """Normalise a company or role title for comparison (LaTeX escapes,
    dashes, whitespace)."""
    s = _LATEX_ESCAPE_IN_TEXT.sub(r"\1", s)
    s = normalise_dashes(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# ---------- Module check ----------

def collect_master_modules(master: dict) -> set[str]:
    """Collect all module names from master_cv.json education entries."""
    modules: set[str] = set()
    for edu in master.get("education", []):
        for module_list in edu.get("modules", {}).values():
            modules.update(module_list)
        for year_modules in edu.get("modules_by_year", {}).values():
            modules.update(year_modules)
    return modules


def check_modules(tex: str, master: dict) -> list[Violation]:
    """Each module in 'Relevant modules: ...' must exist in master_cv.json."""
    violations: list[Violation] = []
    # Find "Relevant modules:" prose. Variants typically have it inside the
    # \cveducation{...} block's optional-arg paragraph.
    matches = re.finditer(
        r"Relevant modules:\s*(.+?)(?:\}|\\\\)",
        tex,
        re.DOTALL,
    )
    master_modules_norm = {
        normalise_for_module_match(m): m for m in collect_master_modules(master)
    }

    for m in matches:
        modules_str = m.group(1).strip().rstrip(".")
        # Strip trailing LaTeX commands and braces
        modules_str = re.sub(r"\\\\.*$", "", modules_str)
        modules_str = re.sub(r"\}.*$", "", modules_str)
        # Split on commas (module names contain no commas)
        listed = [n.strip() for n in modules_str.split(",") if n.strip()]
        for mod in listed:
            mod_norm = normalise_for_module_match(mod)
            if mod_norm not in master_modules_norm:
                violations.append(Violation(
                    "MODULE_NOT_IN_MASTER",
                    f"Module '{mod}' not found in master_cv.json"
                ))
    return violations


# ---------- Language level check ----------

# Level words ranked from weakest (1) to strongest (5). A CV may only claim a
# level word whose rank does not exceed the rank recorded in master_cv.json.
_LEVEL_RANKS: list[tuple[str, int]] = [
    ("native", 5), ("bilingual", 5), ("mother tongue", 5), ("mother-tongue", 5), ("c2", 5),
    ("fluent", 4),
    ("proficient", 3), ("professional", 3), ("advanced", 3), ("c1", 3),
    ("intermediate", 2), ("conversational", 2), ("b2", 2), ("b1", 2),
    ("basic", 1), ("beginner", 1), ("elementary", 1), ("a2", 1), ("a1", 1),
]


def _level_rank(level_text: str) -> int | None:
    """Highest-ranked level word found in a level string, or None."""
    text = level_text.lower()
    best: int | None = None
    for word, rank in _LEVEL_RANKS:
        if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", text):
            if best is None or rank > best:
                best = rank
    return best


def check_language_levels(tex: str, master: dict) -> list[Violation]:
    """Any explicit language-level claim must not exceed master_cv.json.

    For every language listed in the master's languages section, each mention
    of that language in the .tex is inspected in a small window. If the window
    contains the expected level word, the claim is accepted. Otherwise any
    level word ranked above the master's level flags an overclaim. Implicit
    mentions without a level word (e.g. "English and French speaker") are
    allowed.
    """
    violations: list[Violation] = []
    for lang in master.get("languages", []):
        name = lang.get("language")
        expected = lang.get("level")
        if not name or not expected:
            continue
        expected_rank = _level_rank(str(expected))
        if expected_rank is None:
            continue  # unrecognised level wording; nothing to enforce

        for m in re.finditer(r"\b" + re.escape(name) + r"\b", tex):
            start = max(0, m.start() - 60)
            end = min(len(tex), m.end() + 60)
            context = tex[start:end].lower()

            # If the expected level word is nearby, treat as a correct claim.
            if str(expected).lower() in context:
                continue

            for word, rank in _LEVEL_RANKS:
                if rank <= expected_rank:
                    continue
                if re.search(r"(?<![a-z])" + re.escape(word) + r"(?![a-z])", context):
                    snippet = tex[start:end].replace("\n", " ")
                    violations.append(Violation(
                        "LANGUAGE_LEVEL_OVERCLAIM",
                        f"{name} claimed near '{word}', expected level "
                        f"'{expected}'. Context: ...{snippet.strip()}..."
                    ))
                    break
    return violations


# ---------- Years of experience ----------

def check_experience_years(tex: str, master: dict) -> list[Violation]:
    """Any '<N> years' claim referring to total experience must equal master."""
    violations: list[Violation] = []
    expected = master.get("experience_years")
    if expected is None:
        return violations

    # Context markers that indicate a total-experience claim: the word
    # "experience" or "at <employer>" for any employer in the master CV.
    employer_markers = [
        f"at {role.get('company', '').strip().lower()}"
        for role in master.get("experience", [])
        if role.get("company")
    ]

    # Find "<digits>+? years" patterns. We focus on patterns near the context
    # markers to avoid false positives on date ranges and unrelated year
    # mentions (like "over 7 years" describing project duration).
    for m in re.finditer(r"\b(\d+)\+?\s+years?\b", tex):
        # Inspect surrounding window for context
        start = max(0, m.start() - 40)
        end = min(len(tex), m.end() + 40)
        ctx = tex[start:end].lower()

        if not ("experience" in ctx or any(mk in ctx for mk in employer_markers)):
            continue

        years = int(m.group(1))
        if years != expected:
            snippet = tex[start:end].replace("\n", " ")
            violations.append(Violation(
                "EXPERIENCE_YEARS_MISMATCH",
                f"Experience claim '{m.group(0)}' but master has "
                f"{expected}. Context: ...{snippet.strip()}..."
            ))
    return violations


# ---------- Cventry date / title checks ----------

CVENTRY_RE = re.compile(
    r"\\cventry\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}"
)


def normalise_date_range(s: str) -> str:
    s = normalise_dashes(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


_MONTH_TO_INT = {
    m: i for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1
    )
}


def _month_year_to_int(s: str) -> int:
    """Convert 'Mon YYYY' (e.g. 'Aug 2022') to a sortable integer YYYYMM.
    'Present' sorts after every real date. Falls back to 0 for unparseable
    strings.
    """
    if s.strip().lower() == "present":
        return 999_912
    parts = s.strip().split()
    if len(parts) != 2:
        return 0
    month, year = parts
    try:
        return int(year) * 100 + _MONTH_TO_INT.get(month[:3], 0)
    except ValueError:
        return 0


def parse_master_period(role: dict) -> str:
    start = role.get("start_date", "")
    end = role.get("end_date", "")
    return f"{start} - {end}".strip()


def _approved_titles(role: dict) -> set[str]:
    """Approved titles for a role: the canonical title plus title_variants."""
    titles = {role.get("title", "").strip()}
    for variant in role.get("title_variants", []) or []:
        titles.add(str(variant).strip())
    return {normalise_title(t) for t in titles if t}


def check_employer_dates_and_titles(tex: str, master: dict) -> list[Violation]:
    """Each \\cventry must use an approved title and matching dates.

    For every employer present in master_cv.json:
      - the entry's title must be the canonical master title or one of the
        role's "title_variants";
      - the entry's dates must match that role's start/end dates. When the
        master lists several roles at the employer but the variant lists
        fewer entries (roles combined into one), the combined entry may
        instead span the union of the employer's periods.

    Employers not present in master_cv.json are not validated here.
    """
    violations: list[Violation] = []
    master_roles = master.get("experience", [])

    # Group master roles by normalised company name.
    roles_by_company: dict[str, list[dict]] = {}
    for role in master_roles:
        company = normalise_title(role.get("company", ""))
        if company:
            roles_by_company.setdefault(company, []).append(role)

    # Group tex cventries by normalised company name.
    entries_by_company: dict[str, list[tuple[str, str, str]]] = {}
    for m in CVENTRY_RE.finditer(tex):
        company = normalise_title(m.group(1))
        title = m.group(2).strip()
        dates = normalise_date_range(m.group(3))
        entries_by_company.setdefault(company, []).append((title, dates, m.group(3)))

    for company, entries in entries_by_company.items():
        roles = roles_by_company.get(company)
        if not roles:
            continue  # employer not tracked in master_cv.json

        company_display = roles[0].get("company", company)

        # Union of all periods at this employer (for combined entries).
        starts = sorted(
            (r.get("start_date", "") for r in roles), key=_month_year_to_int
        )
        ends = sorted(
            (r.get("end_date", "") for r in roles), key=_month_year_to_int
        )
        union_period = normalise_date_range(f"{starts[0]} - {ends[-1]}") if roles else ""

        combined_allowed = len(entries) < len(roles)

        for title, dates, raw_dates in entries:
            title_norm = normalise_title(title)

            # Title whitelist: find the master role this title belongs to.
            matched_role = None
            for role in roles:
                if title_norm in _approved_titles(role):
                    matched_role = role
                    break

            if matched_role is None:
                approved = sorted(
                    t for role in roles for t in _approved_titles(role)
                )
                violations.append(Violation(
                    "TITLE_UNAPPROVED",
                    f"{company_display}: title '{title}' not in approved set "
                    f"(canonical titles + title_variants): {approved}"
                ))
                continue

            expected_period = normalise_date_range(parse_master_period(matched_role))
            allowed = {expected_period}
            if combined_allowed and union_period:
                # Roles combined into fewer entries: the union span is valid.
                allowed.add(union_period)

            if dates not in allowed:
                expected_str = expected_period
                if combined_allowed and union_period != expected_period:
                    expected_str = f"{expected_period}' or combined union '{union_period}"
                violations.append(Violation(
                    "DATES_MISMATCH",
                    f"{company_display} / {title}: dates '{raw_dates}' do not "
                    f"match master '{expected_str}'"
                ))

    return violations


# ---------- Main ----------

def run_checks(tex: str, master: dict) -> list[Violation]:
    violations: list[Violation] = []
    violations.extend(check_modules(tex, master))
    violations.extend(check_language_levels(tex, master))
    violations.extend(check_experience_years(tex, master))
    violations.extend(check_employer_dates_and_titles(tex, master))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="CV factual cross-reference against master_cv.json."
    )
    parser.add_argument("tex_path", type=Path, help="Path to .tex source")
    parser.add_argument(
        "master_cv_path", type=Path, nargs="?",
        default=None,
        help="Path to master_cv.json (default: data/master_cv.json relative to project)"
    )
    args = parser.parse_args()

    if not args.tex_path.exists():
        print(f"tex file not found: {args.tex_path}", file=sys.stderr)
        return 2

    if args.master_cv_path is None:
        # Resolve relative to script's project root (scripts/ -> ../data/master_cv.json)
        args.master_cv_path = Path(__file__).resolve().parents[1] / "data" / "master_cv.json"
    if not args.master_cv_path.exists():
        print(
            f"master_cv.json not found: {args.master_cv_path}\n"
            "Run /onboard to generate it, or copy data/master_cv.example.json "
            "and fill it in.",
            file=sys.stderr,
        )
        return 2

    tex = args.tex_path.read_text()
    master = json.loads(args.master_cv_path.read_text())

    violations = run_checks(tex, master)

    if violations:
        print("Violations:")
        for v in violations:
            print(f"  - [{v.code}] {v.message}")
        return 1

    print("All factual checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
