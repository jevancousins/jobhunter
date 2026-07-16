"""Ashby (`*.ashbyhq.com/*/application`) walker.

Ashby's application forms are clean React forms with predictable labels:
Name, Email, Phone, Resume, LinkedIn, plus a small set of custom questions
that vary by tenant. Single page; no account creation by default.

If the form has long-form text questions or unusual custom fields, escalate.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import _pcli as p

ROOT = Path(__file__).resolve().parent.parent.parent
PROFILE_PATH = ROOT / "data" / "application_profile.json"


def _load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text())


def _ref(snap: str, kind: str, label: str) -> str | None:
    pat = re.compile(rf'{kind} "([^"]*{re.escape(label)}[^"]*)" \[ref=(e\d+)\]')
    m = pat.search(snap)
    return m.group(2) if m else None


def walk(role_context: dict, cv_pdf: Path, session_name: str) -> dict:
    apply_url = role_context.get("apply_type", "")
    if apply_url.startswith("EXT:"):
        apply_url = apply_url[4:]
    if not apply_url:
        return {"status": "failed", "reason": "no-apply-url"}

    profile = _load_profile()
    ident = profile["identity"]

    p.goto(session_name, apply_url, settle=3)
    snap = p.snapshot(session_name)

    # Ashby job listing pages show a "Submit Application" CTA that, when clicked,
    # navigates into the actual form (typically at <url>/application). Detect
    # whether we are already on the form (resume upload present) or still on the
    # listing page, and navigate into the form before filling anything.
    upload_ref = _ref(snap, "button", "Resume") or _ref(snap, "button", "Upload")
    if not upload_ref:
        # Try clicking the entry CTA on the listing page
        cta_ref = (
            _ref(snap, "button", "Submit Application")
            or _ref(snap, "button", "Apply")
            or _ref(snap, "link", "Apply")
            or _ref(snap, "button", "Apply now")
        )
        if cta_ref:
            p.click(session_name, cta_ref)
            time.sleep(2)
            snap = p.snapshot(session_name)
            upload_ref = _ref(snap, "button", "Resume") or _ref(snap, "button", "Upload")

        # Still not on the form — navigate directly to the canonical /application URL
        if not upload_ref:
            app_url = apply_url.rstrip("/") + "/application"
            if app_url != apply_url.rstrip("/"):
                p.goto(session_name, app_url, settle=3)
                snap = p.snapshot(session_name)

    if "Submit Application" not in snap and "Apply for this Job" not in snap:
        return {"status": "failed", "reason": "ashby-form-not-detected"}

    answers: dict = {}
    for label, value in (
        ("Full Name", ident["full_name"]),
        ("Name", ident["full_name"]),
        ("Email", ident["email"]),
        ("Phone", ident["phone"]),
        ("LinkedIn", ident.get("linkedin_url", "")),
    ):
        # Only fill if the field is present in the snapshot (presence check),
        # but use fill_by_label so we are not relying on a ref that may be stale
        # by the time we reach the second or later fill call.
        if _ref(snap, "textbox", label) and value:
            p.fill_by_label(session_name, label, value)
            time.sleep(0.2)
            answers[label] = value

    # Resume — "Upload Your Resume" or similar.  Re-read snap in case the CTA
    # click above caused a page transition that we already captured above; if
    # upload_ref was resolved during the entry-navigation block, skip the
    # re-lookup (it's already valid).
    if not upload_ref:
        upload_ref = _ref(snap, "button", "Resume") or _ref(snap, "button", "Upload")
    if upload_ref:
        p.click(session_name, upload_ref)
        time.sleep(0.5)
        p.upload(session_name, cv_pdf)
        time.sleep(2)
    else:
        return {"status": "escalate", "reason": "ashby-resume-button-not-found",
                "payload": {"url": apply_url}}

    # Long-form questions or extra required fields → escalate
    snap = p.snapshot(session_name)
    if re.search(r'textarea[^"]*"[^"]+\*"', snap):
        return {"status": "escalate", "reason": "ashby-textarea-question-required",
                "payload": {"url": apply_url, "answers_filled": answers,
                            "note": "Tenant added a required free-text question "
                                    "(cover-letter style). Sub-agent must answer."}}
    extras = re.findall(r'(textbox|combobox) "([^"]+\*)"', snap)
    unfilled = [(k, l) for k, l in extras
                if not any(a.lower() in l.lower() for a in answers)]
    if unfilled:
        return {"status": "escalate", "reason": "ashby-extra-required-fields",
                "payload": {"unfilled": unfilled[:10], "url": apply_url}}

    submit_ref = _ref(snap, "button", "Submit Application") or _ref(snap, "button", "Submit")
    if not submit_ref:
        return {"status": "escalate", "reason": "ashby-submit-button-missing",
                "payload": {"url": apply_url}}
    p.click(session_name, submit_ref)

    # Detect possible-spam / bot-detection warning before checking for confirmation
    # (Ashby's own spam check is kept; shared helper skips spam for this walker)
    time.sleep(3)
    spam_flag = p.pcli_eval(
        session_name,
        "(() => /spam|suspicious activity|not.*human|automated.*submission|bot detected/i.test(document.body.innerText))()",
    )
    if spam_flag:
        return {"status": "escalate", "reason": "ashby-spam-flag-detected",
                "payload": {"url": apply_url, "answers_filled": answers,
                            "note": "Ashby displayed a possible-spam or bot-detection "
                                    "warning after submission. Manual submission required."}}

    # -- Confirmation detection with retry (Fix 2) --------------------------
    ASHBY_CONFIRM_JS = """(() => {
      const text = document.body.innerText || '';
      const url  = location.href || '';
      const textOk = /application has been received|thank you for applying|we have received your application|successfully submitted|your application has been received|application submitted|thank you for your application|we.?ve received your/i.test(text);
      const urlOk = /\\/(submitted|thank-you|thankyou|confirmation|success|complete|done|thanks)(\\?|$|\\/|#)/i.test(url);
      const domOk = Array.from(
        document.querySelectorAll('[class*="confirmation"],[class*="success"],[class*="submitted"],[id*="confirmation"],[id*="success"],[id*="submitted"]')
      ).some(el => {
        const txt = (el.innerText || el.textContent || '').trim();
        return txt.length > 0;
      });
      const submitBtn = Array.from(document.querySelectorAll('button[type="submit"], button'))
        .find(b => /submit/i.test(b.innerText || b.textContent || ''));
      const btnOk = submitBtn ? (submitBtn.disabled || submitBtn.hidden || getComputedStyle(submitBtn).display === 'none') : false;
      return textOk || urlOk || domOk || btnOk;
    })()"""

    # initial_delay=0 because we already slept 3 s for the spam check
    confirmed = p.detect_confirmation(
        session_name, ASHBY_CONFIRM_JS, initial_delay=0,
    )
    if confirmed:
        return {
            "status": "applied",
            "submitted_via": "Ashby",
            "confirmation": "application received",
            "screening": answers,
        }

    # -- Differentiated failure detection (Fix 1) ---------------------------
    # skip_spam=True because Ashby has its own spam check above
    failure = p.detect_pre_submit_failure(
        session_name, "ashby", url=apply_url, answers=answers, skip_spam=True,
    )
    if failure:
        return failure

    return {"status": "escalate", "reason": "ashby-confirmation-not-detected",
            "payload": {"url": apply_url, "answers_filled": answers}}
