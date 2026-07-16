"""BambooHR (`*.bamboohr.com/careers/<id>` or `*/jobs/view.php?id=<id>`) walker.

BambooHR apply forms are single-page React forms with predictable fields:
First Name, Last Name, Email, Phone, and a Resume/CV file upload. Optional
fields (LinkedIn, website, cover letter) are skipped unless they are required.

Some employers add custom screening questions. Any extra required fields that
we cannot auto-fill cause an immediate escalate. Optional extras are skipped.
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

    # BambooHR job listing pages show an "Apply" CTA that navigates to the
    # actual application form. If we land on the listing page rather than the
    # form itself, click through.
    if "First Name" not in snap and "Resume" not in snap:
        cta_ref = (
            _ref(snap, "button", "Apply Now")
            or _ref(snap, "button", "Apply now")
            or _ref(snap, "button", "Apply for this Job")
            or _ref(snap, "button", "Apply")
            or _ref(snap, "link", "Apply Now")
            or _ref(snap, "link", "Apply")
        )
        if cta_ref:
            p.click(session_name, cta_ref)
            time.sleep(2)
            snap = p.snapshot(session_name)

    # Verify we have reached the application form.
    if "First Name" not in snap and "Resume" not in snap:
        return {"status": "failed", "reason": "bamboohr-form-not-detected"}

    answers: dict = {}

    # BambooHR splits name into First Name / Last Name (unlike Lever/Ashby
    # which use a single Full Name field).
    for label, value in (
        ("First Name", ident["first_name"]),
        ("Last Name", ident["last_name"]),
        ("Email", ident["email"]),
        ("Phone", ident["phone"]),
    ):
        if _ref(snap, "textbox", label) and value:
            p.fill_by_label(session_name, label, value)
            time.sleep(0.2)
            answers[label] = value

    # Optional but common: LinkedIn URL and personal website.
    for label, value in (
        ("LinkedIn", ident.get("linkedin_url", "")),
        ("Website", ident.get("website_url", "")),
    ):
        if _ref(snap, "textbox", label) and value:
            p.fill_by_label(session_name, label, value)
            time.sleep(0.2)
            answers[label] = value

    # Resume upload. BambooHR uses a button labelled "Upload Resume",
    # "Upload CV", "Choose File", or similar.
    upload_ref = (
        _ref(snap, "button", "Resume")
        or _ref(snap, "button", "Upload Resume")
        or _ref(snap, "button", "Upload CV")
        or _ref(snap, "button", "Choose File")
        or _ref(snap, "button", "Attach")
    )
    if upload_ref:
        p.click(session_name, upload_ref)
        time.sleep(0.5)
        p.upload(session_name, cv_pdf)
        time.sleep(2)
    else:
        return {
            "status": "escalate",
            "reason": "bamboohr-resume-button-not-found",
            "payload": {"url": apply_url},
        }

    # Refresh snapshot after upload before checking for unfilled required fields.
    snap = p.snapshot(session_name)

    # DOM-level check: find any required/aria-required inputs still empty.
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

    # Snapshot-level check: fields marked with "*" in their label that we
    # have not already answered.
    snap_extras = re.findall(r'(textbox|combobox|textarea) "([^"]+\*)"', snap)
    snap_unfilled = [
        (k, lbl)
        for k, lbl in snap_extras
        if not any(a.lower() in lbl.lower() for a in answers)
    ]

    all_unfilled = dom_extra + [
        (k, lbl) for k, lbl in snap_unfilled if (k, lbl) not in dom_extra
    ]
    if all_unfilled:
        return {
            "status": "escalate",
            "reason": "bamboohr-extra-required-fields",
            "payload": {"unfilled": all_unfilled[:10], "url": apply_url},
        }

    # Locate and click the submit button.
    submit_ref = (
        _ref(snap, "button", "Submit Application")
        or _ref(snap, "button", "Submit")
        or _ref(snap, "button", "Apply")
    )
    if not submit_ref:
        return {
            "status": "escalate",
            "reason": "bamboohr-submit-button-missing",
            "payload": {"url": apply_url},
        }
    p.click(session_name, submit_ref)

    # -- Confirmation detection with retry (Fix 2) --------------------------
    BAMBOOHR_CONFIRM_JS = (
        "(() => /Thank you for applying|Application received|Your application has been submitted"
        "|application.*submitted|received your application|Thank(?:s| you)/i"
        ".test(document.body.innerText + ' ' + location.href))()"
    )

    confirmed = p.detect_confirmation(session_name, BAMBOOHR_CONFIRM_JS)
    if confirmed:
        return {
            "status": "applied",
            "submitted_via": "BambooHR",
            "confirmation": "Application submitted",
            "screening": answers,
        }

    # -- Differentiated failure detection (Fix 1) ---------------------------
    failure = p.detect_pre_submit_failure(
        session_name, "bamboohr", url=apply_url, answers=answers,
    )
    if failure:
        return failure

    return {
        "status": "escalate",
        "reason": "bamboohr-confirmation-not-detected",
        "payload": {"url": apply_url, "answers_filled": answers},
    }
