"""Jobvite ATS walker.

Supports both URL patterns Jobvite uses:
  - app.jobvite.com/<tenant>/apply/<job-id>
  - jobs.jobvite.com/<tenant>/job/<id>/apply

Jobvite's apply forms are largely consistent across tenants: First Name, Last
Name, Email, Phone, and a resume/CV upload. Optional extras include LinkedIn
URL, website, and a "How did you hear about us?" dropdown (which is rarely
required). Some tenants bolt on custom screening questions; escalate on those.

Forms are single-page React. No account creation is required by default.
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

    # Jobvite sometimes renders a job-details landing page before the actual
    # application form. If the form inputs aren't visible yet, look for an
    # "Apply" CTA and click it.
    form_indicators = ("First Name", "Last Name", "Resume", "Upload")
    if not any(ind in snap for ind in form_indicators):
        cta_ref = (
            _ref(snap, "button", "Apply Now")
            or _ref(snap, "button", "Apply")
            or _ref(snap, "link", "Apply Now")
            or _ref(snap, "link", "Apply")
        )
        if cta_ref:
            p.click(session_name, cta_ref)
            time.sleep(2)
            snap = p.snapshot(session_name)

    # Hard bail: if we still cannot detect the form, escalate so a human can
    # diagnose rather than silently failing.
    if not any(ind in snap for ind in form_indicators):
        return {"status": "failed", "reason": "jobvite-form-not-detected",
                "payload": {"url": apply_url}}

    answers: dict = {}

    # Jobvite splits name into First Name / Last Name (not a single "Full Name"
    # field). Try both the split labels first; fall back to "Full name" in case
    # a tenant uses a consolidated field.
    for label, value in (
        ("First Name", ident["first_name"]),
        ("Last Name", ident["last_name"]),
        ("Email", ident["email"]),
        ("Phone", ident["phone"]),
        ("LinkedIn", ident.get("linkedin_url", "")),
        ("Website", ident.get("website_url", "")),
    ):
        if _ref(snap, "textbox", label) and value:
            p.fill_by_label(session_name, label, value)
            time.sleep(0.2)
            answers[label] = value

    # "How did you hear about us?" is a common Jobvite dropdown; if present and
    # not required (no asterisk), leave it — do not attempt to fill it, as
    # guessing the right option is fragile. If it IS required we will catch it
    # in the unfilled-fields check below and escalate.

    # Resume upload. Jobvite renders either a button labelled "Upload Resume",
    # "Upload CV", or a generic "Upload" / "Attach" button.
    upload_ref = (
        _ref(snap, "button", "Upload Resume")
        or _ref(snap, "button", "Upload CV")
        or _ref(snap, "button", "Resume")
        or _ref(snap, "button", "Upload")
        or _ref(snap, "button", "Attach")
    )
    if upload_ref:
        p.click(session_name, upload_ref)
        time.sleep(0.5)
        p.upload(session_name, cv_pdf)
        time.sleep(2)
    else:
        return {"status": "escalate", "reason": "jobvite-resume-button-not-found",
                "payload": {"url": apply_url}}

    # Post-upload snapshot to catch any newly revealed required fields.
    snap = p.snapshot(session_name)

    # Two-pass required-fields check (mirrors lever.py pattern):
    #   1. DOM query for inputs flagged required/aria-required that are still empty.
    #   2. Snapshot scan for labels with a trailing "*".
    dom_unfilled = p.pcli_eval(
        session_name,
        """(() => {
          const out = [];
          document.querySelectorAll('[required], [aria-required="true"]').forEach(el => {
            if (el.type === 'hidden' || el.disabled) return;
            const val = (el.value || '').trim();
            if (!val) {
              const label = (
                el.getAttribute('aria-label') ||
                (el.id && document.querySelector('label[for="' + el.id + '"]')?.textContent?.trim()) ||
                el.placeholder || el.name || ''
              ).slice(0, 80).trim();
              out.push([el.tagName.toLowerCase(), label || el.id || '?']);
            }
          });
          return JSON.stringify(out.slice(0, 10));
        })()""",
    )

    dom_extra: list[tuple[str, str]] = []
    if isinstance(dom_unfilled, list):
        for tag, label in dom_unfilled:
            if not any(a.lower() in label.lower() for a in answers):
                dom_extra.append((tag, label))

    snap_extras = re.findall(r'(textbox|combobox|textarea) "([^"]+\*)"', snap)
    snap_unfilled = [(k, l) for k, l in snap_extras
                     if not any(a.lower() in l.lower() for a in answers)]

    all_unfilled = dom_extra + [(k, l) for k, l in snap_unfilled
                                if (k, l) not in dom_extra]
    if all_unfilled:
        return {"status": "escalate", "reason": "jobvite-extra-required-fields",
                "payload": {"unfilled": all_unfilled[:10], "url": apply_url,
                            "answers_filled": answers}}

    # Locate and click the submit button.
    submit_ref = (
        _ref(snap, "button", "Submit Application")
        or _ref(snap, "button", "Submit")
        or _ref(snap, "button", "Apply")
    )
    if not submit_ref:
        return {"status": "escalate", "reason": "jobvite-submit-button-missing",
                "payload": {"url": apply_url}}

    p.click(session_name, submit_ref)

    # -- Confirmation detection with retry (Fix 2) --------------------------
    JOBVITE_CONFIRM_JS = r"(() => /Thank\s+you|Application submitted|successfully submitted|application has been received|received your application|application was submitted/i.test(document.body.innerText + ' ' + location.href))()"

    confirmed = p.detect_confirmation(session_name, JOBVITE_CONFIRM_JS)
    if confirmed:
        return {
            "status": "applied",
            "submitted_via": "Jobvite",
            "confirmation": "Application submitted",
            "screening": answers,
        }

    # -- Differentiated failure detection (Fix 1) ---------------------------
    failure = p.detect_pre_submit_failure(
        session_name, "jobvite", url=apply_url, answers=answers,
    )
    if failure:
        return failure

    return {
        "status": "escalate",
        "reason": "jobvite-confirmation-not-detected",
        "payload": {"url": apply_url, "answers_filled": answers},
    }
