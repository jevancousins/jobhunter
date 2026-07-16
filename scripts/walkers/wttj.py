"""Welcome to the Jungle (welcometothejungle.com) walker.

WTTJ hosts job listings on its own platform but application flows come in two
distinct shapes:

  1. WTTJ-native apply form  -- the company has opted to use WTTJ's own form
     (hosted under welcometothejungle.com/*/jobs/*/apply or the jobs API
     subdomain). This is a React SPA with a predictable field set:
       First Name* / Last Name* / Email* / Phone / Resume/CV* (file upload) /
       LinkedIn URL / optional cover letter (textarea, rarely required) /
       optional screening questions (yes/no, single-select, short text).

  2. External redirect -- the "Apply" button on a WTTJ listing page navigates
     to a third-party ATS (Greenhouse, Lever, Workday, etc.). In that case this
     walker detects the redirect, identifies the target ATS, and hands off to
     the appropriate existing walker.  The dispatch logic in auto_apply.py
     should already have resolved the external URL before calling this walker,
     but we guard against arriving at a WTTJ listing page mid-flow.

URL patterns this walker handles:
  - www.welcometothejungle.com/*/jobs/<slug>/apply
  - www.welcometothejungle.com/*/companies/<co>/jobs/<slug>  (listing; need to
    click Apply)
  - jobs.welcometothejungle.com/* (rare, same React app)
  - uk.welcometothejungle.com / global.welcometothejungle.com (same shape)

WTTJ requires a candidate account for some tenants (single-sign-on via Google
or email). If the form shows a sign-in gate, escalate.

Confirmed form signals (public job listing page inspection, 2026-05-20):
  - Apply button label: "Apply for this job" / "Postuler" / "Apply now"
  - After clicking Apply (or navigating to /apply URL): a modal or page with
    fields: First name, Last name, Email, Phone, Resume, LinkedIn
  - Submit button: "Submit application" / "Send application" / "Apply"
  - Confirmation: "Application sent" / "Your application has been received" /
    "Thank you" / "Candidature envoyée"
  - Anti-bot: reCAPTCHA v3 (invisible, no action required) or hCaptcha
    (rare; escalate if detected).
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from urllib.parse import urlparse

from . import _pcli as p

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_PATH = ROOT / "data" / "application_profile.json"

# Regex patterns for detecting known external ATS hosts within WTTJ pages.
# When WTTJ redirects to one of these, we tell the orchestrator to re-dispatch.
_EXTERNAL_ATS_HOSTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"greenhouse\.io|grnh\.se|eu\.greenhouse\.io"), "greenhouse"),
    (re.compile(r"myworkdayjobs\.com"), "workday"),
    (re.compile(r"lever\.co"), "lever"),
    (re.compile(r"ashbyhq\.com"), "ashby"),
    (re.compile(r"smartrecruiters\.com"), "smartrecruiters"),
    (re.compile(r"teamtailor\.com"), "teamtailor"),
    (re.compile(r"bamboohr\.com"), "bamboohr"),
    (re.compile(r"jobvite\.com"), "jobvite"),
    (re.compile(r"icims\.com"), "icims"),
    (re.compile(r"taleo\.net|oracle\.com/taleo"), "taleo"),
]


def _load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def _ref(snap: str, kind: str, label: str) -> str | None:
    pat = re.compile(rf'{kind} "([^"]*{re.escape(label)}[^"]*)" \[ref=(e\d+)\]')
    m = pat.search(snap)
    return m.group(2) if m else None


def _detect_external_ats(url: str) -> str | None:
    """Return the ATS kind name if the URL belongs to a known external ATS."""
    host = (urlparse(url).hostname or "").lower()
    for pattern, kind in _EXTERNAL_ATS_HOSTS:
        if pattern.search(host):
            return kind
    return None


def _current_url(session: str) -> str:
    val = p.pcli_eval(session, "(() => location.href)()")
    return val if isinstance(val, str) else ""


def _body_text(session: str) -> str:
    val = p.pcli_eval(session, "(() => document.body ? document.body.innerText : '')()")
    return val if isinstance(val, str) else ""


def _fill(session: str, snap: str, label: str, value: str) -> bool:
    """Fill a textbox by accessible label. Uses DOM-based fill to avoid stale refs."""
    if not _ref(snap, "textbox", label) or not value:
        return False
    ok = p.fill_by_label(session, label, value)
    time.sleep(0.3)
    return ok


# ---------------------------------------------------------------------------
# navigate to the actual apply form
# ---------------------------------------------------------------------------

def _navigate_to_apply_form(session: str, apply_url: str) -> tuple[bool, str]:
    """Navigate to `apply_url` and, if we land on a WTTJ listing page, click
    through to the apply form.  Returns (arrived_at_form, final_url).

    WTTJ listing pages do not expose the form directly; they show an
    "Apply for this job" button (or "Postuler") that either:
      a) opens a modal with the WTTJ native form, or
      b) redirects to an external ATS.
    """
    p.goto(session, apply_url, settle=4)
    snap = p.snapshot(session)

    # Already on the apply form (native WTTJ form signals)
    if _is_apply_form(snap):
        return (True, _current_url(session))

    # On a listing page — find and click the Apply button
    apply_ref = (
        _ref(snap, "button", "Apply for this job")
        or _ref(snap, "button", "Apply now")
        or _ref(snap, "button", "Apply")
        or _ref(snap, "button", "Postuler")
        or _ref(snap, "link", "Apply for this job")
        or _ref(snap, "link", "Apply now")
        or _ref(snap, "link", "Postuler")
    )
    if apply_ref:
        p.click(session, apply_ref)
        time.sleep(4)
        snap = p.snapshot(session)
        current = _current_url(session)

        # Check whether we were redirected to an external ATS
        ats = _detect_external_ats(current)
        if ats:
            return (False, current)  # caller should re-dispatch

        if _is_apply_form(snap):
            return (True, current)

    # Try navigating directly to the /apply suffix as a fallback
    if not apply_url.rstrip("/").endswith("/apply"):
        fallback = apply_url.rstrip("/") + "/apply"
        p.goto(session, fallback, settle=4)
        snap = p.snapshot(session)
        if _is_apply_form(snap):
            return (True, _current_url(session))

    return (False, _current_url(session))


def _is_apply_form(snap: str) -> bool:
    """Return True if the snapshot looks like a WTTJ native application form."""
    return bool(
        re.search(r'textbox "(?:First name|Last name|Email|Firstname|Surname)', snap, re.IGNORECASE)
        or re.search(r'button "(?:Submit application|Send application|Apply|Postuler)"', snap, re.IGNORECASE)
        or "Resume" in snap and "Email" in snap
    )


def _is_login_gate(snap: str) -> bool:
    """Return True if WTTJ is demanding account sign-in before showing the form."""
    return bool(re.search(
        r"Sign in|Log in|Create an account|Connexion|Inscrivez-vous|sign.?up|register",
        snap, re.IGNORECASE,
    ) and "Email" not in snap)


# ---------------------------------------------------------------------------
# top-level walk()
# ---------------------------------------------------------------------------

def walk(role_context: dict, cv_pdf: Path, session_name: str) -> dict:
    apply_url = role_context.get("apply_type", "")
    if apply_url.startswith("EXT:"):
        apply_url = apply_url[4:]
    if not apply_url:
        return {"status": "failed", "reason": "no-apply-url"}

    profile = _load_profile()
    ident = profile["identity"]
    auth = profile.get("citizenship_and_authorisation", {})
    country = role_context.get("country") or auth.get("current_residence_country", "United Kingdom")

    # ------------------------------------------------------------------
    # Step 1: navigate to the apply form
    # ------------------------------------------------------------------
    arrived, final_url = _navigate_to_apply_form(session_name, apply_url)

    if not arrived:
        # Check for external ATS redirect
        ats = _detect_external_ats(final_url)
        if ats:
            # Tell the orchestrator to re-dispatch with the resolved URL so the
            # correct walker (greenhouse, lever, etc.) can handle it.
            return {
                "status": "escalate",
                "reason": "wttj-external-ats-redirect",
                "payload": {
                    "target_ats": ats,
                    "resolved_url": final_url,
                    "original_wttj_url": apply_url,
                    "note": (
                        f"WTTJ listing redirected to {ats} ATS at {final_url}. "
                        "Orchestrator should re-dispatch with apply_type=EXT:<resolved_url> "
                        f"so the {ats} walker handles the form."
                    ),
                },
            }
        # No recognisable form and no known external ATS
        return {
            "status": "escalate",
            "reason": "wttj-form-not-detected",
            "payload": {
                "url": apply_url,
                "final_url": final_url,
                "note": "Could not find the WTTJ native apply form or detect an "
                        "external ATS redirect. Manual review required.",
            },
        }

    snap = p.snapshot(session_name)

    # ------------------------------------------------------------------
    # Step 2: guard against login gate
    # ------------------------------------------------------------------
    if _is_login_gate(snap):
        return {
            "status": "escalate",
            "reason": "wttj-login-required",
            "payload": {
                "url": final_url,
                "note": "WTTJ is presenting a sign-in gate before the application "
                        "form. Edge-case agent must authenticate before continuing.",
            },
        }

    # ------------------------------------------------------------------
    # Step 3: fill standard identity fields
    # ------------------------------------------------------------------
    answers: dict = {}

    # WTTJ's React form uses several label variants depending on locale.
    # Try the most common English labels first, then French equivalents.
    field_map = [
        ("First name",    ident["first_name"]),
        ("Firstname",     ident["first_name"]),
        ("Prénom",        ident["first_name"]),
        ("Last name",     ident["last_name"]),
        ("Lastname",      ident["last_name"]),
        ("Surname",       ident["last_name"]),
        ("Nom",           ident["last_name"]),
        ("Email",         ident["email"]),
        ("Phone",         ident.get("phone_national") or ident.get("phone", "")),
        ("Téléphone",     ident.get("phone_national") or ident.get("phone", "")),
        ("LinkedIn",      ident.get("linkedin_url", "")),
        ("LinkedIn URL",  ident.get("linkedin_url", "")),
    ]
    for label, value in field_map:
        if value and _fill(session_name, snap, label, value):
            # Normalise to English key in answers dict
            canonical = label.replace("Prénom", "First name").replace("Nom", "Last name") \
                              .replace("Téléphone", "Phone").replace("Firstname", "First name") \
                              .replace("Lastname", "Last name").replace("Surname", "Last name")
            if canonical not in answers:
                answers[canonical] = value

    # ------------------------------------------------------------------
    # Step 4: resume upload
    # ------------------------------------------------------------------
    snap = p.snapshot(session_name)
    upload_ref = (
        _ref(snap, "button", "Resume")
        or _ref(snap, "button", "CV")
        or _ref(snap, "button", "Upload")
        or _ref(snap, "button", "Attach")
        or _ref(snap, "button", "Add your CV")
        or _ref(snap, "button", "Ajouter votre CV")
    )
    if not upload_ref:
        # Fallback: locate a file input via DOM
        file_input_js = p.pcli_eval(
            session_name,
            "(() => { const el = document.querySelector('input[type=\"file\"]'); "
            "return el ? el.id || el.name || 'found' : ''; })()",
        )
        if not file_input_js:
            return {
                "status": "escalate",
                "reason": "wttj-resume-upload-not-found",
                "payload": {"url": final_url, "answers_filled": answers},
            }
    else:
        p.click(session_name, upload_ref)
        time.sleep(0.5)

    p.upload(session_name, cv_pdf)
    time.sleep(2)
    answers["Resume"] = cv_pdf.name

    # ------------------------------------------------------------------
    # Step 5: handle optional cover-letter textarea
    # Do NOT fill it automatically — WTTJ cover letters benefit from
    # tailoring. If it is *required*, escalate.
    # ------------------------------------------------------------------
    snap = p.snapshot(session_name)
    cl_required = bool(re.search(
        r'textarea "([^"]*(?:cover letter|motivation|lettre de motivation)[^"]*\*)"',
        snap, re.IGNORECASE,
    ))
    if cl_required:
        return {
            "status": "escalate",
            "reason": "wttj-cover-letter-required",
            "payload": {
                "url": final_url,
                "answers_filled": answers,
                "note": "WTTJ form requires a cover letter / motivation text. "
                        "Edge-case agent must compose and insert this.",
            },
        }

    # ------------------------------------------------------------------
    # Step 6: required-field gate (DOM + snapshot two-pass check)
    # ------------------------------------------------------------------
    dom_unfilled = p.pcli_eval(
        session_name,
        """(() => {
          const out = [];
          document.querySelectorAll('[required], [aria-required="true"]').forEach(el => {
            if (el.type === 'hidden' || el.disabled) return;
            const val = (el.value || '').trim();
            if (!val || val.toLowerCase() === 'select...') {
              const label = (
                el.getAttribute('aria-label') ||
                (el.id && document.querySelector('label[for="' + el.id + '"]')
                  ?.textContent?.trim()) ||
                el.placeholder || el.name || ''
              ).slice(0, 80).trim();
              out.push([el.tagName.toLowerCase(), label || el.id || '?']);
            }
          });
          return JSON.stringify(out.slice(0, 15));
        })()""",
    )

    dom_extra: list[tuple[str, str]] = []
    if isinstance(dom_unfilled, list):
        for tag, label in dom_unfilled:
            if not any(a.lower() in label.lower() for a in answers):
                dom_extra.append((tag, label))

    snap_extras = re.findall(r'(textbox|combobox|textarea|checkbox) "([^"]+\*)"', snap)
    snap_unfilled = [
        (k, lbl) for k, lbl in snap_extras
        if not any(a.lower() in lbl.lower() for a in answers)
    ]

    all_unfilled = dom_extra + [(k, lbl) for k, lbl in snap_unfilled
                                if (k, lbl) not in dom_extra]
    if all_unfilled:
        return {
            "status": "escalate",
            "reason": "wttj-required-fields-unfilled",
            "payload": {
                "unfilled_required": all_unfilled[:10],
                "url": final_url,
                "answers_filled": answers,
                "note": "One or more required fields were not filled automatically. "
                        "Edge-case agent must complete these before submitting.",
            },
        }

    # ------------------------------------------------------------------
    # Step 7: submit
    # ------------------------------------------------------------------
    snap = p.snapshot(session_name)
    submit_ref = (
        _ref(snap, "button", "Submit application")
        or _ref(snap, "button", "Send application")
        or _ref(snap, "button", "Submit")
        or _ref(snap, "button", "Apply")
        or _ref(snap, "button", "Postuler")
        or _ref(snap, "button", "Envoyer")
    )
    if not submit_ref:
        return {
            "status": "escalate",
            "reason": "wttj-submit-button-missing",
            "payload": {"url": final_url, "answers_filled": answers},
        }

    p.click(session_name, submit_ref)

    # ------------------------------------------------------------------
    # Step 8: confirm submission
    # ------------------------------------------------------------------
    WTTJ_CONFIRM_JS = (
        "(() => /Application sent|application has been (?:received|submitted)|"
        "Thank(?:s| you)|received your application|"
        "Candidature envoy\\u00e9e|Votre candidature a \\u00e9t\\u00e9|Merci d\\'avoir postul\\u00e9|"
        "\\/confirmation(?:\\?|$|\\/)/.test(document.body.innerText + ' ' + location.href))()"
    )

    confirmed = p.detect_confirmation(
        session_name, WTTJ_CONFIRM_JS, initial_delay=4,
    )
    if confirmed:
        pass  # fall through to the success return below
    else:
        # -- Differentiated failure detection (Fix 1) -----------------------
        failure = p.detect_pre_submit_failure(
            session_name, "wttj", url=final_url, answers=answers,
        )
        if failure:
            return failure
        return {
            "status": "escalate",
            "reason": "wttj-confirmation-not-detected",
            "payload": {"url": final_url, "answers_filled": answers},
        }

    return {
        "status": "applied",
        "submitted_via": "Welcome to the Jungle",
        "confirmation": "Application sent",
        "screening": answers,
    }
