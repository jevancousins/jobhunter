#!/usr/bin/env python3
r"""Deterministic CV format checks beyond page fill.

Validates the LaTeX source against project formatting rules:

  Profile (LaTeX source):
    - Word count: 40 <= words <= 130
    - Sentence count: 3 <= sentences <= 4
    - No first-person pronouns (I, my, me, mine)

  Section structure:
    - Required sections present (Profile, Skills, Experience, Education, Projects)
    - Sections appear in canonical order

  Inline emphasis (LaTeX source):
    - \\textbf{} permitted ONLY inside the Projects section's bullet labels
    - \\textit{}, \\emph{}, \\textsl{} are NEVER permitted (no italic content)

  Punctuation:
    - Em-dashes (---) are banned outside LaTeX comments

  Banned phrases (CV cliches):
    - "results-driven", "passionate about", "team player", "self-starter",
      "strong work ethic", "thinking outside the box", "detail-oriented",
      "hardworking", "out-of-the-box", "synergies", "go-getter",
      "proven track record", "dynamic individual"

  Primary experience block (first \cventry):
    - Bullet count: 5 <= bullets <= 8

These checks complement scripts/check_page_fill.py (PDF rendering rules) and
scripts/check_cv_facts.py (cross-reference against master_cv.json).

Usage:
    python scripts/check_cv_format.py <tex_path>

Exit codes:
    0 = all checks passed
    1 = format violation (any rule above)
    2 = invalid arguments / file missing
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path


# --- Limits ---
PROFILE_WORD_MIN = 40
PROFILE_WORD_MAX = 110
PROFILE_SENTENCE_MIN = 3
PROFILE_SENTENCE_MAX = 4
PRIMARY_BULLET_MIN = 5
PRIMARY_BULLET_MAX = 8

CANONICAL_SECTION_ORDER = ["Profile", "Skills", "Experience", "Education", "Projects"]

# Cliches that should never appear in a CV
BANNED_PHRASES = [
    "results-driven",
    "passionate about",
    "team player",
    "self-starter",
    "strong work ethic",
    "thinking outside the box",
    "detail-oriented",
    "hardworking",
    "out-of-the-box",
    "synergies",
    "go-getter",
    "proven track record",
    "dynamic individual",
]

# First-person pronouns banned in the Profile section.
# Match as whole words only.
FIRST_PERSON_PRONOUNS = ["I", "my", "me", "mine", "myself"]


@dataclass
class Violation:
    code: str
    message: str


# ---------- Profile extraction ----------

LATEX_CMD_RE = re.compile(r"\\[a-zA-Z@]+(\{[^}]*\})?")
LATEX_ESCAPE_RE = re.compile(r"\\([&%$#_{}~^])")


def extract_profile_text(tex: str) -> str | None:
    """Return plain-text Profile content, or None if no \\cvprofile block.

    Strips LaTeX commands and escapes for word counting and pronoun checks.
    """
    start = tex.find(r"\cvprofile{")
    if start == -1:
        return None
    open_brace = start + len(r"\cvprofile{")
    depth = 1
    i = open_brace
    while i < len(tex) and depth > 0:
        c = tex[i]
        if c == "\\" and i + 1 < len(tex):
            i += 2
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
        i += 1
    if depth != 0:
        return None
    raw = tex[open_brace:i - 1]
    plain = LATEX_CMD_RE.sub(" ", raw)
    plain = LATEX_ESCAPE_RE.sub(r"\1", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    return plain


def count_words(text: str) -> int:
    return len([w for w in text.split() if w.strip()])


def count_sentences(text: str) -> int:
    if not text:
        return 0
    breaks = re.findall(r"[.!?]\s+(?=[A-Z])", text)
    return len(breaks) + 1


def check_profile_first_person(profile: str) -> list[Violation]:
    violations: list[Violation] = []
    for pronoun in FIRST_PERSON_PRONOUNS:
        if re.search(rf"\b{re.escape(pronoun)}\b", profile):
            violations.append(Violation(
                "PROFILE_FIRST_PERSON",
                f"Profile contains first-person pronoun '{pronoun}'"
            ))
    return violations


# ---------- Section structure ----------

SECTION_RE = re.compile(r"\\section\{([^}]+)\}")


def check_section_structure(tex: str) -> list[Violation]:
    """Verify required sections present and in canonical order.

    Profile is special — it lives in \\cvprofile{} not \\section{}. So we
    treat its position as the offset of \\cvprofile{ in the source.
    Other sections must be \\section{Name} with names matching CANONICAL_SECTION_ORDER.
    """
    violations: list[Violation] = []

    # Locate each canonical section
    positions: dict[str, int] = {}
    profile_pos = tex.find(r"\cvprofile{")
    if profile_pos != -1:
        positions["Profile"] = profile_pos

    for m in SECTION_RE.finditer(tex):
        name = m.group(1).strip()
        if name in CANONICAL_SECTION_ORDER and name != "Profile":
            if name in positions:
                violations.append(Violation(
                    "SECTION_DUPLICATE",
                    f"Duplicate \\section{{{name}}}"
                ))
                continue
            positions[name] = m.start()

    # Check all required sections present
    for name in CANONICAL_SECTION_ORDER:
        if name not in positions:
            violations.append(Violation(
                "SECTION_MISSING",
                f"Required section missing: {name}"
            ))

    # If all present, check order
    if all(name in positions for name in CANONICAL_SECTION_ORDER):
        actual_order = sorted(CANONICAL_SECTION_ORDER, key=lambda n: positions[n])
        if actual_order != CANONICAL_SECTION_ORDER:
            violations.append(Violation(
                "SECTION_ORDER",
                f"Sections out of canonical order. Expected: "
                f"{CANONICAL_SECTION_ORDER}; got: {actual_order}"
            ))
    return violations


# ---------- Bold / italic checks ----------

def find_projects_section_range(tex: str) -> tuple[int, int] | None:
    """Return (start, end) byte offsets for the \\section{Projects} body."""
    matches = list(SECTION_RE.finditer(tex))
    for idx, m in enumerate(matches):
        if m.group(1).strip().lower() == "projects":
            start = m.end()
            end = matches[idx + 1].start() if idx + 1 < len(matches) else len(tex)
            doc_end = tex.find(r"\end{document}", start, end)
            if doc_end != -1:
                end = doc_end
            return start, end
    return None


def _is_in_comment(tex: str, pos: int) -> bool:
    """Return True if `pos` falls inside a LaTeX comment line."""
    line_start = tex.rfind("\n", 0, pos) + 1
    return tex[line_start:pos].lstrip().startswith("%")


def check_textbf(tex: str) -> list[Violation]:
    violations: list[Violation] = []
    proj_range = find_projects_section_range(tex)
    for m in re.finditer(r"\\textbf\{", tex):
        if _is_in_comment(tex, m.start()):
            continue
        if proj_range and proj_range[0] <= m.start() < proj_range[1]:
            continue
        snippet = tex[max(0, m.start() - 25):m.start() + 35].replace("\n", " ")
        violations.append(Violation(
            "BOLD_OUTSIDE_PROJECTS",
            f"\\textbf{{}} found outside Projects section: ...{snippet.strip()}..."
        ))
    return violations


def check_italic(tex: str) -> list[Violation]:
    violations: list[Violation] = []
    for cmd in ("textit", "emph", "textsl"):
        for m in re.finditer(rf"\\{cmd}\{{", tex):
            if _is_in_comment(tex, m.start()):
                continue
            snippet = tex[max(0, m.start() - 25):m.start() + 35].replace("\n", " ")
            violations.append(Violation(
                "ITALIC_FORBIDDEN",
                f"\\{cmd}{{}} forbidden: ...{snippet.strip()}..."
            ))
    return violations


# ---------- Em-dash + banned phrases ----------

def check_em_dash(tex: str) -> list[Violation]:
    violations: list[Violation] = []
    for m in re.finditer(r"---", tex):
        if _is_in_comment(tex, m.start()):
            continue
        snippet = tex[max(0, m.start() - 25):m.start() + 30].replace("\n", " ")
        violations.append(Violation(
            "EM_DASH",
            f"em-dash (---) found: ...{snippet.strip()}..."
        ))
    return violations


def check_banned_phrases(tex: str) -> list[Violation]:
    """Scan the .tex source for cliche phrases (case-insensitive)."""
    violations: list[Violation] = []
    for phrase in BANNED_PHRASES:
        # Case-insensitive whole-phrase match (allow leading/trailing word boundaries)
        for m in re.finditer(rf"\b{re.escape(phrase)}\b", tex, re.IGNORECASE):
            if _is_in_comment(tex, m.start()):
                continue
            snippet = tex[max(0, m.start() - 20):m.start() + 40].replace("\n", " ")
            violations.append(Violation(
                "BANNED_PHRASE",
                f"banned cliche '{phrase}': ...{snippet.strip()}..."
            ))
    return violations


# ---------- Primary-role bullet count ----------

CVENTRY_RE = re.compile(r"\\cventry\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}\{([^}]+)\}")


def check_primary_bullet_count(tex: str) -> list[Violation]:
    """Verify the primary (first-listed) experience entry has 5-8 \\cvbullet{} entries.

    The primary role is the first \\cventry in the document, which by CV
    convention is the current or most recent role and carries the bulk of the
    evidence. The block ends at the next \\cventry, \\section, or
    \\end{document}.
    """
    violations: list[Violation] = []
    matches = list(CVENTRY_RE.finditer(tex))
    if not matches:
        return []
    boundaries = [m.start() for m in matches] + [
        len(tex) if (e := tex.find(r"\end{document}")) == -1 else e
    ]

    block_start = matches[0].end()
    block_end = boundaries[1]
    block = tex[block_start:block_end]
    bullet_count = len(re.findall(r"\\cvbullet\{", block))
    if bullet_count < PRIMARY_BULLET_MIN:
        violations.append(Violation(
            "PRIMARY_BULLETS_MIN",
            f"primary role has {bullet_count} bullets, "
            f"minimum {PRIMARY_BULLET_MIN}"
        ))
    if bullet_count > PRIMARY_BULLET_MAX:
        violations.append(Violation(
            "PRIMARY_BULLETS_MAX",
            f"primary role has {bullet_count} bullets, "
            f"maximum {PRIMARY_BULLET_MAX}"
        ))
    return violations


_BULLET_RE = re.compile(r"\\cvbullet\s*\{(.+?)\}", re.DOTALL)


def check_action_verb_uniqueness(tex: str) -> list[Violation]:
    """Every Experience-section bullet must start with a unique action verb.

    The first word of each `\\cvbullet{...}` across the entire CV is captured;
    duplicates are flagged. Word matching is case-insensitive and ignores
    punctuation. This is a deliberately strict rule (per user 2026-05-02)
    because action-verb repetition reads as lazy and weakens the CV.

    Note: bullets in Projects (which are not `\\cvbullet`) are excluded by
    design. Only Experience bullets are subject to this check.
    """
    violations: list[Violation] = []
    seen: dict[str, int] = {}
    for m in _BULLET_RE.finditer(tex):
        body = m.group(1).strip()
        # Take the first whitespace-separated token, strip surrounding punctuation.
        first = re.split(r"\s+", body, maxsplit=1)[0]
        first = re.sub(r"[^A-Za-z\-]", "", first).lower()
        if not first:
            continue
        seen[first] = seen.get(first, 0) + 1
    duplicates = sorted([(verb, n) for verb, n in seen.items() if n > 1])
    for verb, n in duplicates:
        violations.append(Violation(
            "ACTION_VERB_DUPLICATE",
            f"Experience bullets start with '{verb}' {n} times; each opening verb must be unique"
        ))
    return violations


# ---------- Main ----------

def run_checks(tex_path: Path) -> list[Violation]:
    tex = tex_path.read_text()
    violations: list[Violation] = []

    # Profile checks
    profile = extract_profile_text(tex)
    if profile is None:
        violations.append(Violation(
            "PROFILE_MISSING",
            "Profile section not found (no \\cvprofile{...} in source)"
        ))
    else:
        words = count_words(profile)
        sentences = count_sentences(profile)
        if words < PROFILE_WORD_MIN:
            violations.append(Violation(
                "PROFILE_WORDS_MIN",
                f"Profile {words} words below minimum {PROFILE_WORD_MIN}"
            ))
        if words > PROFILE_WORD_MAX:
            violations.append(Violation(
                "PROFILE_WORDS_MAX",
                f"Profile {words} words exceeds maximum {PROFILE_WORD_MAX}"
            ))
        if sentences < PROFILE_SENTENCE_MIN:
            violations.append(Violation(
                "PROFILE_SENTENCES_MIN",
                f"Profile {sentences} sentences below minimum {PROFILE_SENTENCE_MIN}"
            ))
        if sentences > PROFILE_SENTENCE_MAX:
            violations.append(Violation(
                "PROFILE_SENTENCES_MAX",
                f"Profile {sentences} sentences exceeds maximum {PROFILE_SENTENCE_MAX}"
            ))
        violations.extend(check_profile_first_person(profile))
        print(f"Profile: {words} words, {sentences} sentences")

    violations.extend(check_section_structure(tex))
    violations.extend(check_textbf(tex))
    violations.extend(check_italic(tex))
    violations.extend(check_em_dash(tex))
    violations.extend(check_banned_phrases(tex))
    violations.extend(check_primary_bullet_count(tex))
    violations.extend(check_action_verb_uniqueness(tex))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deterministic CV format checks."
    )
    parser.add_argument("tex_path", type=Path, help="Path to .tex source")
    args = parser.parse_args()

    if not args.tex_path.exists():
        print(f"tex file not found: {args.tex_path}", file=sys.stderr)
        return 2

    violations = run_checks(args.tex_path)

    if violations:
        print("\nViolations:")
        for v in violations:
            print(f"  - [{v.code}] {v.message}")
        return 1

    print("\nAll format checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
