"""SmartRecruiters walker.

Drives the standard SmartRecruiters application form end-to-end.
Common URL shapes:
  - jobs.smartrecruiters.com/<Company>/<job-id>
  - careers.smartrecruiters.com/<Company>/<job-id>
  - <custom-domain>.smartrecruiters.com/...

Form structure (stable across tenants):
  First Name* / Last Name* / Email* / Phone / Resume/CV* (file upload) /
  optional Location, Country, Current Company, LinkedIn URL /
  optional screening questions (short-text, single/multi select).

If any required field beyond the boilerplate shape cannot be resolved from
`data/application_profile.json`, escalate rather than guess.
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
    """Return the ref of the first element of `kind` whose label contains `label`."""
    pat = re.compile(rf'{kind} "([^"]*{re.escape(label)}[^"]*)" \[ref=(e\d+)\]')
    m = pat.search(snap)
    return m.group(2) if m else None


def _fill(session: str, snap: str, label: str, value: str) -> bool:
    """Fill a textbox whose accessible name contains `label`. Returns True on success.

    Uses fill_by_label (DOM-based, React-aware) rather than the snapshot ref,
    because refs become stale after any subsequent snapshot or React re-render.
    The snap argument is kept only to check field presence before attempting the fill.
    """
    if not _ref(snap, "textbox", label) or not value:
        return False
    ok = p.fill_by_label(session, label, value)
    time.sleep(0.3)
    return ok


def _select_option(session: str, snap: str, combobox_label: str,
                   desired: list[str]) -> tuple[bool, str]:
    """Open a combobox/select element and choose the first matching option.

    SmartRecruiters renders dropdowns as <select> elements or as custom
    listbox widgets depending on the question type. This helper tries both
    patterns:
      1. native <select>: set value via `form_input` equivalent (pcli select).
      2. ARIA listbox: click the combobox, wait for options, click matching option.
    Returns (success, option_text_picked).
    """
    cb_ref = _ref(snap, "combobox", combobox_label)
    if not cb_ref:
        return (False, "")

    # Try native select first (fastest path)
    for want in desired:
        p.pcli(session, "select", cb_ref, want)
        time.sleep(0.3)
        # Verify something was picked (if pcli select succeeds, the value changes)
        fresh = p.snapshot(session)
        picked_pat = re.compile(
            rf'combobox "([^"]*{re.escape(combobox_label)}[^"]*)"[^\n]*\nselected: ([^\n]+)',
        )
        m = picked_pat.search(fresh)
        if m and m.group(2).strip().lower() != "select..." and m.group(2).strip():
            return (True, m.group(2).strip())

    # Fallback: click to open listbox, then click the matching option
    p.click(session, cb_ref)
    time.sleep(0.4)
    fresh = p.snapshot(session)
    # Gather all visible options
    options: list[tuple[str, str]] = re.findall(
        r'option "([^"]*)" \[ref=(e\d+)\]', fresh
    )
    for want in desired:
        for text, ref in options:
            if want.lower() in text.lower():
                p.click(session, ref)
                time.sleep(0.3)
                return (True, text)
    # Dismiss without picking (press Escape) so the dropdown doesn't linger
    p.pcli(session, "press", cb_ref, "Escape")
    return (False, "")


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

    p.goto(session_name, apply_url, settle=4)
    snap = p.snapshot(session_name)

    # SmartRecruiters sometimes lands on a job-detail page with an "Apply now"
    # button that opens the actual application form. Detect this and click through.
    if "First Name" not in snap and "Last Name" not in snap:
        apply_cta = (
            _ref(snap, "button", "Apply now")
            or _ref(snap, "button", "Apply for this job")
            or _ref(snap, "link", "Apply now")
            or _ref(snap, "button", "Apply")
        )
        if apply_cta:
            p.click(session_name, apply_cta)
            time.sleep(3)
            snap = p.snapshot(session_name)

    # Verify form is present
    if "First Name" not in snap and "Last Name" not in snap:
        return {"status": "failed", "reason": "smartrecruiters-form-not-detected",
                "payload": {"url": apply_url}}

    answers: dict = {}

    # Core identity fields
    for label, value in (
        ("First Name", ident["first_name"]),
        ("Last Name", ident["last_name"]),
        ("Email", ident["email"]),
        ("Phone", ident.get("phone_national") or ident.get("phone", "")),
        ("LinkedIn", ident.get("linkedin_url", "")),
        ("Current Company", ""),    # intentionally blank; not misleading
    ):
        if _fill(session_name, snap, label, value) and value:
            answers[label] = value

    # Resume upload: SmartRecruiters uses a file-input button labelled
    # "Upload your resume" or "Attach resume" or simply "Resume".
    snap = p.snapshot(session_name)
    upload_ref = (
        _ref(snap, "button", "Upload your resume")
        or _ref(snap, "button", "Attach resume")
        or _ref(snap, "button", "Upload resume")
        or _ref(snap, "button", "Resume")
        or _ref(snap, "button", "Attach")
        or _ref(snap, "button", "Upload")
    )
    if not upload_ref:
        # Try finding a file input directly via DOM
        file_input_ref = p.pcli_eval(
            session_name,
            """(() => {
              const el = document.querySelector('input[type="file"]');
              return el ? (el.getAttribute('data-ref') || el.id || '') : '';
            })()""",
        )
        if not file_input_ref:
            return {"status": "escalate", "reason": "smartrecruiters-resume-upload-not-found",
                    "payload": {"url": apply_url}}
    else:
        p.click(session_name, upload_ref)
        time.sleep(0.5)

    p.upload(session_name, cv_pdf)
    time.sleep(2)
    answers["Resume"] = str(cv_pdf.name)

    # Optional: location/country — fill if present and we have a value
    snap = p.snapshot(session_name)
    country = role_context.get("country") or auth.get("current_residence_country", "United Kingdom")
    ok, picked = _select_option(session_name, snap, "Country", [country, "United Kingdom"])
    if ok:
        answers["Country"] = picked

    # "How did you hear about us" style source question — pick LinkedIn
    snap = p.snapshot(session_name)
    ok, picked = _select_option(session_name, snap, "How did you hear",
                                 ["LinkedIn", "Job Board", "Online"])
    if ok:
        answers["How did you hear"] = picked

    # Work authorisation / sponsorship if present
    snap = p.snapshot(session_name)
    auth_for_country = auth.get("by_country", {}).get(country, {})
    needs_sponsorship = auth_for_country.get("requires_sponsorship_now", False)
    sponsorship_answer = "Yes" if not needs_sponsorship else "No"  # "authorised to work?" -> Yes
    ok, picked = _select_option(
        session_name, snap, "authoris",
        [sponsorship_answer, "Yes, I am authorised", "No, I require"],
    )
    if ok:
        answers["Work Authorisation"] = picked

    # ------------------------------------------------------------------
    # Required-field gate: detect any still-empty required inputs before
    # submitting. Two-pass check (DOM + snapshot), same as lever/greenhouse.
    # ------------------------------------------------------------------
    snap = p.snapshot(session_name)

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
                (el.id && document.querySelector('label[for="' + el.id + '"]')?.textContent?.trim()) ||
                el.placeholder || el.name || ''
              ).slice(0, 80).trim();
              out.push([el.tagName.toLowerCase(), label || el.id || '?']);
            }
          });
          return JSON.stringify(out.slice(0, 15));
        })()""",
    )

    # Filter out fields we already filled
    dom_extra: list[tuple[str, str]] = []
    if isinstance(dom_unfilled, list):
        for tag, label in dom_unfilled:
            if not any(a.lower() in label.lower() for a in answers):
                dom_extra.append((tag, label))

    # Snapshot fallback: visible "*" required labels not yet in answers
    snap_extras = re.findall(r'(textbox|combobox|textarea) "([^"]+\*)"', snap)
    snap_unfilled = [
        (k, lbl) for k, lbl in snap_extras
        if not any(a.lower() in lbl.lower() for a in answers)
    ]

    all_unfilled = dom_extra + [(k, lbl) for k, lbl in snap_unfilled
                                if (k, lbl) not in dom_extra]
    if all_unfilled:
        return {
            "status": "escalate",
            "reason": "smartrecruiters-extra-required-fields",
            "payload": {
                "unfilled": all_unfilled[:10],
                "url": apply_url,
                "answers_filled": answers,
                "note": "One or more required fields could not be filled automatically. "
                        "Edge-case agent must complete these before submitting.",
            },
        }

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------
    submit_ref = (
        _ref(snap, "button", "Submit application")
        or _ref(snap, "button", "Submit Application")
        or _ref(snap, "button", "Submit")
        or _ref(snap, "button", "Apply")
        or _ref(snap, "button", "Send Application")
    )
    if not submit_ref:
        return {"status": "escalate", "reason": "smartrecruiters-submit-button-missing",
                "payload": {"url": apply_url, "answers_filled": answers}}

    p.click(session_name, submit_ref)

    # -- Confirmation detection with retry (Fix 2) --------------------------
    SMARTRECRUITERS_CONFIRM_JS = r"""(() => /Application submitted|Thank(?:s| you) for (?:applying|your application)|Your application has been (?:received|submitted)|We(?:'ve| have) received your application|application is being processed|Candidature (?:envoy[ée]e|re[çc]ue)|Merci d'avoir postul[ée]|\/confirmation(?:\?|$|\/)/.test(document.body.innerText + ' ' + location.href))()"""

    confirmed = p.detect_confirmation(
        session_name, SMARTRECRUITERS_CONFIRM_JS, initial_delay=4,
    )
    if confirmed:
        return {
            "status": "applied",
            "submitted_via": "SmartRecruiters",
            "confirmation": "Application submitted",
            "screening": answers,
        }

    # -- Differentiated failure detection (Fix 1) ---------------------------
    failure = p.detect_pre_submit_failure(
        session_name, "smartrecruiters", url=apply_url, answers=answers,
    )
    if failure:
        return failure

    return {
        "status": "escalate",
        "reason": "smartrecruiters-confirmation-not-detected",
        "payload": {"url": apply_url, "answers_filled": answers},
    }
