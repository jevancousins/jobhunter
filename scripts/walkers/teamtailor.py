"""TeamTailor walker.

TeamTailor apply forms are found at URLs like:
  - <company>.teamtailor.com/jobs/<id>/applications/new
  - <company>.teamtailor.com/apply/<id>

Typical layout: First Name, Last Name, Email, Phone, Resume/CV upload,
optional LinkedIn, optional cover letter textarea (never required on the
standard tenant). Some tenants add custom screening questions; escalate
on those.

No account creation required by default. Forms are single-page.
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

    # TeamTailor may show a job listing page with an "Apply" CTA before the
    # actual form. Detect whether we need to navigate into the form first.
    on_form = (
        "Send application" in snap
        or "Apply" in snap
        and ("Resume" in snap or "CV" in snap or "First name" in snap or "First Name" in snap)
    )
    if not on_form:
        cta_ref = (
            _ref(snap, "button", "Apply")
            or _ref(snap, "link", "Apply")
            or _ref(snap, "button", "Apply now")
            or _ref(snap, "link", "Apply now")
        )
        if cta_ref:
            p.click(session_name, cta_ref)
            time.sleep(2)
            snap = p.snapshot(session_name)

    # Verify we are on the application form
    form_detected = (
        "Send application" in snap
        or "First name" in snap
        or "First Name" in snap
        or "Resume" in snap
        or "CV" in snap
    )
    if not form_detected:
        return {"status": "failed", "reason": "teamtailor-form-not-detected",
                "payload": {"url": apply_url}}

    answers: dict = {}

    # TeamTailor typically splits name into First name / Last name fields.
    # Try split fields first; fall back to a single "Full name" field.
    # Presence check uses snapshot refs; actual fill uses fill_by_label to avoid
    # stale-ref failures when the form re-renders between fills.
    first_ref = _ref(snap, "textbox", "First name") or _ref(snap, "textbox", "First Name")
    last_ref = _ref(snap, "textbox", "Last name") or _ref(snap, "textbox", "Last Name")
    if first_ref and last_ref:
        p.fill_by_label(session_name, "First name", ident["first_name"])
        time.sleep(0.2)
        p.fill_by_label(session_name, "Last name", ident["last_name"])
        time.sleep(0.2)
        answers["First name"] = ident["first_name"]
        answers["Last name"] = ident["last_name"]
    else:
        full_ref = _ref(snap, "textbox", "Full name") or _ref(snap, "textbox", "Name")
        if full_ref:
            p.fill_by_label(session_name, "Full name", ident["full_name"])
            time.sleep(0.2)
            answers["Full name"] = ident["full_name"]

    # Email and Phone
    for label, value in (
        ("Email", ident["email"]),
        ("Phone", ident["phone"]),
        ("LinkedIn", ident.get("linkedin_url", "")),
    ):
        if _ref(snap, "textbox", label) and value:
            p.fill_by_label(session_name, label, value)
            time.sleep(0.2)
            answers[label] = value

    # Resume upload — TeamTailor uses a file input triggered by a button
    # labelled "Resume", "CV", "Upload", or "Attach".
    upload_ref = (
        _ref(snap, "button", "Resume")
        or _ref(snap, "button", "CV")
        or _ref(snap, "button", "Upload")
        or _ref(snap, "button", "Attach")
    )
    if upload_ref:
        p.click(session_name, upload_ref)
        time.sleep(0.5)
        p.upload(session_name, cv_pdf)
        time.sleep(2)
    else:
        # TeamTailor also uses a file input directly in some tenants — try DOM.
        file_input_present = p.pcli_eval(
            session_name,
            "(() => !!document.querySelector('input[type=\"file\"]'))()",
        )
        if file_input_present:
            p.upload(session_name, cv_pdf)
            time.sleep(2)
        else:
            return {"status": "escalate", "reason": "teamtailor-resume-upload-not-found",
                    "payload": {"url": apply_url}}

    # Re-snapshot after upload to catch any newly revealed required fields.
    snap = p.snapshot(session_name)

    # Check for required cover letter textarea — TeamTailor occasionally marks
    # this as required on bespoke tenants. Escalate so the sub-agent can draft
    # a cover letter rather than submitting an empty one.
    cover_letter_required = re.search(
        r'textarea "([^"]*(?:[Cc]over [Ll]etter|[Mm]otivation|[Pp]ersonal [Ss]tatement)[^"]*\*)"',
        snap,
    )
    if cover_letter_required:
        return {
            "status": "escalate",
            "reason": "teamtailor-cover-letter-required",
            "payload": {
                "url": apply_url,
                "answers_filled": answers,
                "note": "Tenant requires a cover letter / motivation text. "
                        "Sub-agent must draft and fill it.",
            },
        }

    # Check for any other unfilled required fields via DOM query.
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

    # Snapshot-level check for visible "*" required labels we haven't filled.
    snap_extras = re.findall(r'(textbox|combobox|textarea) "([^"]+\*)"', snap)
    snap_unfilled = [
        (k, l) for k, l in snap_extras
        if not any(a.lower() in l.lower() for a in answers)
    ]

    all_unfilled = dom_extra + [
        (k, l) for k, l in snap_unfilled if (k, l) not in dom_extra
    ]
    if all_unfilled:
        return {
            "status": "escalate",
            "reason": "teamtailor-extra-required-fields",
            "payload": {"unfilled": all_unfilled[:10], "url": apply_url,
                        "answers_filled": answers},
        }

    # Submit
    submit_ref = (
        _ref(snap, "button", "Send application")
        or _ref(snap, "button", "Submit application")
        or _ref(snap, "button", "Submit")
        or _ref(snap, "button", "Apply")
    )
    if not submit_ref:
        return {"status": "escalate", "reason": "teamtailor-submit-button-missing",
                "payload": {"url": apply_url}}

    p.click(session_name, submit_ref)

    # -- Confirmation detection with retry (Fix 2) --------------------------
    TEAMTAILOR_CONFIRM_JS = (
        "(() => /Thank you for your application|Application sent|We.ve received|"
        "application has been (?:sent|received)|Tack f[oö]r din ans[oö]kan|"
        "Merci pour votre candidature|Vielen Dank f[uü]r/i"
        ".test(document.body.innerText))()"
    )

    confirmed = p.detect_confirmation(session_name, TEAMTAILOR_CONFIRM_JS)
    if confirmed:
        return {
            "status": "applied",
            "submitted_via": "TeamTailor",
            "confirmation": "Thank you for your application",
            "screening": answers,
        }

    # -- Differentiated failure detection (Fix 1) ---------------------------
    failure = p.detect_pre_submit_failure(
        session_name, "teamtailor", url=apply_url, answers=answers,
    )
    if failure:
        return failure

    return {
        "status": "escalate",
        "reason": "teamtailor-confirmation-not-detected",
        "payload": {"url": apply_url, "answers_filled": answers},
    }
