"""AI-powered screening-question drafter and reviewer.

Two-phase pipeline:
  1. Drafter  (Claude Haiku 4.5) — classifies and drafts an answer.
  2. Reviewer (Claude Haiku 4.5) — checks the draft against the profile.

Both passes must agree before the answer is auto-filled. Any failure or
disagreement falls back to the existing needs_human escalation path.

See docs/screening-answers-design.md for the full design specification.

Usage (as a module):
    from scripts.ai_screening import ai_draft_and_review
    result = ai_draft_and_review(label, field, role_context, country)
    if result["verdict"] == "APPROVED":
        # use result["answer_obj"]
    else:
        # escalate, optionally show result.get("draft") in MANUAL-APPLY.md

Usage (from the command line — for manual testing only):
    python scripts/ai_screening.py test --label "Describe a time you owned an ML system end-to-end" --field-type textarea --role-id 4408035874
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = PROJECT_ROOT / "data" / "application_profile.json"
DEEP_EXPERIENCE_PATH = PROJECT_ROOT / "data" / "deep_experience.json"
APPLICATIONS_DIR = PROJECT_ROOT / "applications"


def _resolve_role_dir(rid: str) -> Path:
    """Resolve a role folder under the legacy flat or nested layout."""
    flat = APPLICATIONS_DIR / rid
    if flat.is_dir():
        return flat
    for cand in APPLICATIONS_DIR.glob(f"*/{rid}"):
        if cand.is_dir():
            return cand
    return flat

# ---------------------------------------------------------------------------
# Cost-cap state (in-process; resets each Python process / each day)
# ---------------------------------------------------------------------------

_DAILY_COST_CAP_USD = 2.00
_cost_tracker: dict[str, float] = {}   # {date_str: cumulative_usd}


def _get_today_spend() -> float:
    today = dt.date.today().isoformat()
    return _cost_tracker.get(today, 0.0)


def _record_spend(usd: float) -> None:
    today = dt.date.today().isoformat()
    _cost_tracker[today] = _cost_tracker.get(today, 0.0) + usd


def _over_daily_cap() -> bool:
    return _get_today_spend() >= _DAILY_COST_CAP_USD


# ---------------------------------------------------------------------------
# Always-escalate regex pre-checks (no API call needed)
# ---------------------------------------------------------------------------

# These patterns are checked before any API call is made.
_SALARY_PATTERNS = [
    r"\bsalary\b",
    r"\bcompensation\b",
    r"\bpay\b",
    r"\bremuneration\b",
    r"\bpackage\b",
    r"\btotal comp\b",
    r"\bequity\b",
    r"\bbonus\b",
    r"expected.*pay",
    r"pay.*expectation",
    r"salary.*expectation",
    r"salary.*range",
    r"desired.*salary",
    r"current.*salary",
    r"current.*comp",
]

_LEGAL_PATTERNS = [
    r"non.compete",
    r"noncompete",
    r"conflict.of.interest",
    r"ip assignment",
    r"intellectual property assignment",
    r"regulatory restrict",
    r"nda\b",
    r"confidentiality agreement",
]

_IDENTITY_PATTERNS = [
    r"national insurance",
    r"\bnin\b",
    r"passport number",
    r"visa (number|reference|ref)",
    r"right to work (reference|document)",
    r"bank (account|sort code|detail)",
    r"social security",
    r"\bssn\b",
    r"tax id",
    r"\bitin\b",
]

_REFERRAL_PATTERNS = [
    r"referral code",
    r"who referred",
    r"referred by",
    r"referrer",
    r"promo code",
]

_DATE_PATTERNS = [
    r"exact (start )?date",
    r"start date.*specific",
    r"specific.*start date",
]

_ALWAYS_ESCALATE_MAP = {
    "salary_expectation": _SALARY_PATTERNS,
    "legal_or_contractual": _LEGAL_PATTERNS,
    "identity_document": _IDENTITY_PATTERNS,
    "referral_or_personal": _REFERRAL_PATTERNS,
    "start_date_specific": _DATE_PATTERNS,
}

_ALWAYS_ESCALATE_CATEGORIES = frozenset(_ALWAYS_ESCALATE_MAP.keys())


def classify_question(label: str, field_type: str, options: list | None) -> str | None:
    """Quick deterministic pre-check for always-escalate categories.

    Returns the category string if the question is deterministically an
    always-escalate type, or None if it requires the AI drafter to classify.
    """
    text = label.lower()
    for category, patterns in _ALWAYS_ESCALATE_MAP.items():
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                return category
    return None


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def _load_profile() -> dict:
    if not PROFILE_PATH.exists():
        return {}
    with PROFILE_PATH.open() as f:
        return json.load(f)


def _load_deep_experience() -> dict:
    if not DEEP_EXPERIENCE_PATH.exists():
        return {}
    with DEEP_EXPERIENCE_PATH.open() as f:
        return json.load(f)


def _load_jd(role_id: str) -> str:
    jd_path = _resolve_role_dir(role_id) / "jd.txt"
    if not jd_path.exists():
        return ""
    return jd_path.read_text(errors="replace")[:2000]


def _load_role_context(role_id: str) -> dict:
    rc_path = _resolve_role_dir(role_id) / "role-context.json"
    if not rc_path.exists():
        return {}
    with rc_path.open() as f:
        return json.load(f)


def _profile_excerpt(profile: dict) -> str:
    """Return the profile fields most relevant to screening questions.

    We deliberately exclude verified_form_answers (too large, not needed by
    the AI since it is only called when rule-based matching already failed)
    and any private key material.
    """
    keys = (
        "identity",
        "citizenship_and_authorisation",
        "availability",
        "education",
        "experience_years",
        "demographic_optional",
        "misc_common_questions",
    )
    trimmed = {k: profile[k] for k in keys if k in profile}
    return json.dumps(trimmed, indent=2)


def _deep_experience_excerpt(deep: dict) -> str:
    """Serialise the first 3000 characters of deep experience as JSON."""
    text = json.dumps(deep, indent=2)
    if len(text) > 3000:
        text = text[:3000] + "\n... (truncated)"
    return text


# ---------------------------------------------------------------------------
# Haiku API helpers
# ---------------------------------------------------------------------------

def _haiku_call(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    """Make a single synchronous Haiku 4.5 call. Returns the raw text content.

    Raises on any error (timeout, API error, etc.) — the caller catches and
    falls back to escalation.
    """
    import anthropic  # local import to avoid hard dependency at module load time
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
        timeout=5.0,  # hard 5-second timeout as specified in design doc
    )
    # Rough cost estimate: ~$0.001 per 1K input tokens (Haiku 4.5 pricing)
    input_tokens = getattr(msg.usage, "input_tokens", 0) or 0
    output_tokens = getattr(msg.usage, "output_tokens", 0) or 0
    cost_usd = (input_tokens / 1000) * 0.001 + (output_tokens / 1000) * 0.002
    _record_spend(cost_usd)
    return msg.content[0].text if msg.content else ""


def _parse_json_response(text: str) -> dict:
    """Extract and parse a JSON object from a model response.

    The model is instructed to return JSON only, but sometimes wraps it in
    markdown code fences. Strip those before parsing.
    """
    # Remove markdown code fences if present
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        # Drop first and last fence lines
        text = "\n".join(lines[1:-1]) if len(lines) > 2 else text
    # Find the first { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"No JSON object found in response: {text!r}")
    return json.loads(text[start : end + 1])


# ---------------------------------------------------------------------------
# Drafter
# ---------------------------------------------------------------------------

_DRAFTER_SYSTEM = """\
You are a screening-question answerer for a job application. Your task is to
draft an accurate, concise answer to a screening question on behalf of the
candidate. Use British English spelling. Never fabricate experience or
credentials the candidate does not hold. Never volunteer salary information."""

_DRAFTER_USER_TEMPLATE = """\
CANDIDATE PROFILE (factual, authoritative):
{profile_json}

CANDIDATE EXPERIENCE (detailed narratives for open-ended questions):
{deep_experience_excerpt}

JOB CONTEXT:
Title: {title}
Company: {company}
Country: {country}
Job description (first 2000 chars): {jd_excerpt}

QUESTION:
Label: "{question_label}"
Field type: {field_type}
Available options: {options_json_or_none}

INSTRUCTIONS:
1. Classify the question into exactly one category:
   factual_profile | factual_authorisation | binary_capability |
   preference_or_logistics | demographic_optional | open_ended_experience |
   salary_expectation | legal_or_contractual | start_date_specific |
   referral_or_personal | identity_document | unknown

2. If the category is salary_expectation, legal_or_contractual,
   start_date_specific, referral_or_personal, or identity_document:
   set answer to null and confidence to 0.0.

3. Otherwise, draft the answer:
   - For radio/select fields: pick the best matching option value from the
     available options list. Use the candidate profile as ground truth.
   - For text/textarea fields: write a concise, factual answer.
     For open_ended_experience questions, draw on specific projects from
     the candidate experience section. Keep under 150 words unless the
     field is a textarea (then up to 250 words).
   - Never fabricate experience, credentials, or skills the candidate
     does not have.
   - Never volunteer salary expectations, even if the question is indirect.
   - Use British English spelling.

4. Self-assess your confidence (0.0 to 1.0) that:
   - The classification is correct
   - The answer is factually grounded in the profile
   - The answer matches the likely intent of the question

OUTPUT FORMAT (JSON only, no markdown):
{{
  "category": "...",
  "answer": "..." or null if always-escalate category,
  "confidence": 0.0-1.0,
  "rationale": "one sentence explaining the answer source"
}}"""


def draft_answer(
    label: str,
    field: dict,
    role_context: dict,
    profile: dict,
    deep_experience: dict,
) -> dict:
    """Call Haiku to draft an answer. Returns the parsed JSON response dict."""
    options = field.get("options") or field.get("visible_options")
    options_json = json.dumps(options) if options else "null"

    jd_excerpt = ""
    role_id = role_context.get("id") or role_context.get("job_id") or ""
    if role_id:
        jd_excerpt = _load_jd(str(role_id))

    user_prompt = _DRAFTER_USER_TEMPLATE.format(
        profile_json=_profile_excerpt(profile),
        deep_experience_excerpt=_deep_experience_excerpt(deep_experience),
        title=role_context.get("title", ""),
        company=role_context.get("company", ""),
        country=role_context.get("country", ""),
        jd_excerpt=jd_excerpt,
        question_label=label,
        field_type=field.get("kind", "textbox"),
        options_json_or_none=options_json,
    )

    # Choose max_tokens based on field type
    is_long_form = field.get("kind") in ("textarea",)
    max_tokens = 800 if is_long_form else 400

    text = _haiku_call(_DRAFTER_SYSTEM, user_prompt, max_tokens)
    return _parse_json_response(text)


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------

_REVIEWER_SYSTEM = """\
You are a quality reviewer for AI-drafted screening-question answers in a job
application. Your job is to catch errors, hallucinations, and risky answers
before they are submitted. Be conservative: when in doubt, reject rather than
approve."""

_REVIEWER_USER_TEMPLATE = """\
CANDIDATE PROFILE (ground truth):
{profile_json}

QUESTION:
Label: "{question_label}"
Field type: {field_type}
Available options: {options_json_or_none}

DRAFTED ANSWER:
{draft_json}

REVIEW CHECKLIST:
1. FACTUAL ACCURACY: Does the answer match the candidate profile exactly?
   Check years of experience, degree, authorisation status, employment status.
   Flag any claim not directly supported by the profile.

2. OPTION VALIDITY: For radio/select fields, is the chosen value actually
   present in the available options list? If not, flag it.

3. TONE AND PROFESSIONALISM: Is the answer appropriate for a job application?
   No slang, no over-promising, no desperation signals.

4. RED FLAGS:
   - Does the answer volunteer salary information unprompted?
   - Does the answer disclose sensitive personal data unnecessarily?
   - Does the answer claim credentials the candidate does not hold?
   - Does the answer contradict information elsewhere in the profile?
   - Is the answer likely to trigger an automatic rejection filter?
     (e.g. answering "No" to "Do you have the right to work?" when the
     candidate profile shows they are already authorised in that country)

5. CATEGORY CHECK: Is the drafter's category classification correct?
   Should this question actually be in the always-escalate set?

OUTPUT FORMAT (JSON only, no markdown):
{{
  "verdict": "APPROVED" | "REJECTED" | "ALWAYS_ESCALATE",
  "reason": "one sentence",
  "revised_answer": "..." or null,
  "red_flags": ["list of any flags found, empty if none"]
}}"""


def review_answer(
    label: str,
    field: dict,
    draft: dict,
    profile: dict,
) -> dict:
    """Call Haiku to review the draft. Returns the parsed JSON response dict."""
    options = field.get("options") or field.get("visible_options")
    options_json = json.dumps(options) if options else "null"

    user_prompt = _REVIEWER_USER_TEMPLATE.format(
        profile_json=_profile_excerpt(profile),
        question_label=label,
        field_type=field.get("kind", "textbox"),
        options_json_or_none=options_json,
        draft_json=json.dumps(draft, indent=2),
    )

    text = _haiku_call(_REVIEWER_SYSTEM, user_prompt, 300)
    return _parse_json_response(text)


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def _write_audit_log(
    role_id: str,
    label: str,
    field: dict,
    draft: dict | None,
    review: dict | None,
    auto_filled: bool,
    error: str | None = None,
) -> None:
    """Append one entry to applications/<id>/ai-screening-log.json."""
    if not role_id:
        return
    log_path = _resolve_role_dir(role_id) / "ai-screening-log.json"
    entries: list[dict] = []
    if log_path.exists():
        try:
            entries = json.loads(log_path.read_text())
            if not isinstance(entries, list):
                entries = []
        except (json.JSONDecodeError, OSError):
            entries = []

    entries.append({
        "timestamp": dt.datetime.now().isoformat(),
        "label": label,
        "field_type": field.get("kind"),
        "drafter_response": draft,
        "reviewer_response": review,
        "auto_filled": auto_filled,
        "error": error,
    })

    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(json.dumps(entries, indent=2))
    except OSError:
        pass  # audit log failure must never block the pipeline


# ---------------------------------------------------------------------------
# Orchestrator: ai_draft_and_review
# ---------------------------------------------------------------------------

# Progressive trust: categories enabled for auto-fill.
# Week 1 (informational mode): nothing is auto-filled — all AI answers are
# returned for human review alongside the draft.
# Week 2+: enable factual_profile, binary_capability, preference_or_logistics
# by adding them to this set once week-1 accuracy exceeds 95%.
AUTOFILL_ENABLED_CATEGORIES: frozenset[str] = frozenset({
    # Uncomment when ready:
    # "factual_profile",
    # "binary_capability",
    # "preference_or_logistics",
    # "factual_authorisation",
    # "demographic_optional",
    # "open_ended_experience",
})

# Set to True to force informational-only mode regardless of
# AUTOFILL_ENABLED_CATEGORIES (Week 1 safety).
INFORMATIONAL_MODE: bool = True


def ai_draft_and_review(
    label: str,
    field: dict,
    role_context: dict,
    country: str | None,
) -> dict:
    """Main entry point for the AI screening layer.

    Called by linkedin_apply._handle_additional() when a field returns
    needs_human=True.

    Returns a dict:
        {
          "verdict": "APPROVED" | "REJECTED" | "ALWAYS_ESCALATE" | "FALLBACK",
          "answer_obj": {answer, confidence, needs_human, kind, ...},  # if APPROVED
          "draft":  { ... },   # drafter output, always included when available
          "review": { ... },   # reviewer output, always included when available
          "category": str,
          "reason":  str,
        }

    "FALLBACK" means the AI layer encountered an error and the caller should
    fall through to the existing escalation path.
    """
    role_id = (
        role_context.get("id")
        or role_context.get("job_id")
        or ""
    )

    # --- 1. Deterministic pre-check (no API call) ---
    pre_category = classify_question(label, field.get("kind", ""), field.get("options"))
    if pre_category is not None:
        _write_audit_log(role_id, label, field, None, None, False,
                         error=f"pre-classified as {pre_category}")
        return {
            "verdict": "ALWAYS_ESCALATE",
            "category": pre_category,
            "reason": f"Deterministic pre-check: question classified as {pre_category}.",
            "draft": None,
            "review": None,
        }

    # --- 2. Daily cost cap ---
    if _over_daily_cap():
        _write_audit_log(role_id, label, field, None, None, False,
                         error="daily-cost-cap-exceeded")
        return {
            "verdict": "FALLBACK",
            "category": "unknown",
            "reason": "Daily AI screening cost cap reached; falling back to needs_human escalation.",
            "draft": None,
            "review": None,
        }

    # --- 3. Load context ---
    try:
        profile = _load_profile()
        deep_experience = _load_deep_experience()
        if not role_context.get("country") and country:
            role_context = {**role_context, "country": country}
    except Exception as e:
        _write_audit_log(role_id, label, field, None, None, False,
                         error=f"context-load-error: {e}")
        return {
            "verdict": "FALLBACK",
            "category": "unknown",
            "reason": f"Failed to load context: {e}",
            "draft": None,
            "review": None,
        }

    # --- 4. Drafter ---
    draft: dict | None = None
    try:
        draft = draft_answer(label, field, role_context, profile, deep_experience)
    except Exception as e:
        _write_audit_log(role_id, label, field, None, None, False,
                         error=f"drafter-error: {e}")
        return {
            "verdict": "FALLBACK",
            "category": "unknown",
            "reason": f"Drafter API error: {e}",
            "draft": None,
            "review": None,
        }

    # --- 5. Check drafter always-escalate output ---
    category = draft.get("category", "unknown")
    drafter_confidence = float(draft.get("confidence") or 0.0)

    if category in _ALWAYS_ESCALATE_CATEGORIES:
        _write_audit_log(role_id, label, field, draft, None, False)
        return {
            "verdict": "ALWAYS_ESCALATE",
            "category": category,
            "reason": f"Drafter classified as always-escalate: {category}.",
            "draft": draft,
            "review": None,
        }

    if category == "unknown" or drafter_confidence < 0.8:
        _write_audit_log(role_id, label, field, draft, None, False)
        return {
            "verdict": "REJECTED",
            "category": category,
            "reason": f"Drafter confidence {drafter_confidence:.2f} < 0.8 or unknown category.",
            "draft": draft,
            "review": None,
        }

    # --- 6. Reviewer ---
    review: dict | None = None
    try:
        review = review_answer(label, field, draft, profile)
    except Exception as e:
        _write_audit_log(role_id, label, field, draft, None, False,
                         error=f"reviewer-error: {e}")
        return {
            "verdict": "FALLBACK",
            "category": category,
            "reason": f"Reviewer API error: {e}",
            "draft": draft,
            "review": None,
        }

    reviewer_verdict = review.get("verdict", "REJECTED")

    # --- 7. Progressive trust gate ---
    # Even if both passes agree, only auto-fill if the category is in the
    # enabled set AND we are not in informational mode.
    if reviewer_verdict == "APPROVED":
        if INFORMATIONAL_MODE or category not in AUTOFILL_ENABLED_CATEGORIES:
            # Informational mode — generate draft for human but still escalate.
            _write_audit_log(role_id, label, field, draft, review, False)
            revised = review.get("revised_answer")
            final_answer = revised if revised else draft.get("answer")
            return {
                "verdict": "INFORMATIONAL",
                "category": category,
                "reason": "Informational mode active; draft generated for human reviewer.",
                "draft": draft,
                "review": review,
                "suggested_answer": final_answer,
            }

        # Auto-fill path
        revised = review.get("revised_answer")
        final_answer = revised if revised else draft.get("answer")
        _write_audit_log(role_id, label, field, draft, review, True)
        answer_obj = {
            "answer": final_answer,
            "confidence": drafter_confidence,
            "needs_human": False,
            "rationale": draft.get("rationale", "AI-drafted and reviewer-approved."),
            "ai_drafted": True,
            "category": category,
        }
        return {
            "verdict": "APPROVED",
            "category": category,
            "reason": review.get("reason", "Reviewer approved."),
            "draft": draft,
            "review": review,
            "answer_obj": answer_obj,
        }

    # Reviewer rejected or requested escalation
    _write_audit_log(role_id, label, field, draft, review, False)
    return {
        "verdict": reviewer_verdict,
        "category": category,
        "reason": review.get("reason", "Reviewer rejected."),
        "draft": draft,
        "review": review,
    }


# ---------------------------------------------------------------------------
# CLI (manual testing only)
# ---------------------------------------------------------------------------

def _cmd_test(args: argparse.Namespace) -> int:
    field = {
        "kind": args.field_type,
        "label": args.label,
        "options": None,
        "required": True,
    }
    role_context = {}
    if args.role_id:
        role_context = _load_role_context(args.role_id)

    result = ai_draft_and_review(args.label, field, role_context, args.country)
    print(json.dumps(result, indent=2))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="AI screening-question drafter/reviewer (test harness)"
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_test = sub.add_parser("test", help="Test one question end-to-end")
    p_test.add_argument("--label", required=True, help="Question label")
    p_test.add_argument("--field-type", default="textarea",
                        choices=["textbox", "textarea", "radio_group",
                                 "combobox", "custom_combobox", "checkbox"],
                        help="Field type")
    p_test.add_argument("--role-id", default=None, help="Role ID for JD/context")
    p_test.add_argument("--country", default=None,
                        help="Country of the role (e.g. from role-context.json)")
    p_test.set_defaults(func=_cmd_test)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
