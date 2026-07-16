"""Greenhouse job-boards walker.

Drives the standard Greenhouse application form end-to-end. Pure Python,
no LLM calls. Escalates when the form contains a question that is not in
`data/application_profile.json` or requires an email verification code
(handed off to the edge-case sub-agent which has Gmail-MCP access).

Verified form shape (Starburst Partner Solution Architect, 2026-05-03):
    First Name* / Last Name* / Email* / Phone (with Country combobox) /
    Resume/CV* (file upload) / Cover Letter (optional) / LinkedIn Profile /
    Website / Candidate Privacy Policy* (combobox listbox) /
    How did you hear about us?* / Sponsorship combobox /
    Voluntary Self-ID (Gender, Hispanic/Latino, Veteran, Disability) /
    Consent checkbox* / "Submit application" button /
    optional 8-char email verification code group on submit.
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


# ---------------------------------------------------------------------------
# snapshot helpers (snapshot text → ref lookup)
# ---------------------------------------------------------------------------

def _ref_after_label(snap: str, label_pattern: str, kind: str = "textbox") -> str | None:
    """Find the first ref of `kind` whose accessible name contains the label."""
    pat = re.compile(rf'{kind} "([^"]*{re.escape(label_pattern)}[^"]*)" \[ref=(e\d+)\]')
    m = pat.search(snap)
    return m.group(2) if m else None


def _button_ref(snap: str, label_pattern: str) -> str | None:
    return _ref_after_label(snap, label_pattern, kind="button")


def _combobox_ref(snap: str, label_pattern: str) -> str | None:
    return _ref_after_label(snap, label_pattern, kind="combobox")


def _toggle_button_ref_for(snap: str, label_pattern: str) -> str | None:
    """Greenhouse renders custom-select dropdowns with a 'Toggle flyout' button
    sibling to the combobox. Find the toggle whose nearest preceding combobox
    matches the label."""
    pat = re.compile(rf'combobox "({re.escape(label_pattern)})"[^]]*\[ref=(e\d+)\]')
    m = pat.search(snap)
    if not m:
        return None
    # The very next "Toggle flyout" button after this match
    tail = snap[m.end():]
    tm = re.search(r'button "Toggle flyout"[^]]*\[ref=(e\d+)\]', tail)
    return tm.group(1) if tm else None


def _all_listbox_options(snap: str) -> list[tuple[str, str]]:
    """Return [(option_text, ref), ...] from the most recent open listbox."""
    # find last occurrence of 'listbox [ref=...]'
    last_lb = None
    for m in re.finditer(r'listbox \[ref=e\d+\]:', snap):
        last_lb = m
    if not last_lb:
        return []
    tail = snap[last_lb.end():]
    # consume options until we hit a non-option line
    out: list[tuple[str, str]] = []
    for line in tail.splitlines():
        m = re.search(r'option "([^"]*)" \[ref=(e\d+)\]', line)
        if m:
            out.append((m.group(1), m.group(2)))
        elif line.strip() and not line.lstrip().startswith("- option"):
            # exit when we leave the listbox block (next non-option element)
            break
    return out


# ---------------------------------------------------------------------------
# field fillers
# ---------------------------------------------------------------------------

def _fill_textbox(session: str, snap: str, label: str, value: str) -> bool:
    """Fill a textbox by label.

    Uses fill_by_label (DOM-based, React-aware) instead of the snapshot ref,
    because refs from a previous snapshot are stale as soon as any subsequent
    snapshot or DOM mutation happens.  The snap argument is kept for signature
    compatibility but is no longer used for the fill itself.
    """
    # Verify the field is present in the snapshot before attempting the fill;
    # this preserves the caller's ability to skip missing fields.
    if not _ref_after_label(snap, label, kind="textbox"):
        return False
    ok = p.fill_by_label(session, label, value)
    time.sleep(0.3)
    return ok


def _select_dropdown_option(session: str, snap: str, combobox_label: str,
                             desired_options: list[str]) -> tuple[bool, str]:
    """Open a Greenhouse custom dropdown by clicking its 'Toggle flyout'
    button, then click the first matching option. Returns (ok, picked)."""
    toggle = _toggle_button_ref_for(snap, combobox_label)
    if not toggle:
        return (False, "")
    p.click(session, toggle)
    time.sleep(0.4)
    fresh = p.snapshot(session)
    options = _all_listbox_options(fresh)
    if not options:
        return (False, "")
    for want in desired_options:
        for text, ref in options:
            if want.lower() in text.lower():
                p.click(session, ref)
                time.sleep(0.3)
                return (True, text)
    # if no preferred match, pick the first option (fallback for binary
    # acknowledge-style dropdowns)
    text, ref = options[0]
    p.click(session, ref)
    time.sleep(0.3)
    return (True, text)


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
    auth = profile["citizenship_and_authorisation"]
    country = role_context.get("country") or "United Kingdom"
    auth_for_country = auth.get("by_country", {}).get(country, {})
    sponsorship_required = auth_for_country.get("requires_sponsorship_now", True)

    p.goto(session_name, apply_url, settle=4)

    # Some employer pages embed the Greenhouse form in an iframe (e.g.
    # refurbed.de wraps a `job-boards.eu.greenhouse.io/embed/job_app?...`
    # iframe). Detect the embed and re-navigate to the iframe src so we
    # can drive the form directly.
    iframe_src = p.pcli_eval(
        session_name,
        "(() => { const f = Array.from(document.querySelectorAll('iframe')).find(f => /greenhouse\\.io\\/(embed|jobs|job_app)/.test(f.src || '')); return f ? f.src : ''; })()",
    )
    if isinstance(iframe_src, str) and iframe_src:
        p.goto(session_name, iframe_src, settle=4)

    # core text fields
    snap = p.snapshot(session_name)
    # Detect expired iframe-embed validity token. Greenhouse signs the
    # iframe URL with a `validityToken` that expires (~30-60 min). When
    # the token is stale, the embed renders an "expired" / "no longer
    # available" message instead of the form. Re-fetch the parent
    # employer page once to mint a fresh token.
    body_text = p.pcli_eval(session_name, "(() => document.body.innerText)()")
    if isinstance(body_text, str) and re.search(
            r"link has expired|token has expired|no longer available|session has expired",
            body_text, re.IGNORECASE):
        p.goto(session_name, apply_url, settle=4)
        iframe_src2 = p.pcli_eval(
            session_name,
            "(() => { const f = Array.from(document.querySelectorAll('iframe')).find(f => /greenhouse\\.io\\/(embed|jobs|job_app)/.test(f.src || '')); return f ? f.src : ''; })()",
        )
        if isinstance(iframe_src2, str) and iframe_src2:
            p.goto(session_name, iframe_src2, settle=4)
            snap = p.snapshot(session_name)
    if "Submit application" not in snap and "Apply for this job" not in snap:
        return {"status": "failed", "reason": "greenhouse-form-not-detected",
                "host": role_context.get("apply_type", "")}

    answers: dict = {}
    for label, value in (
        ("First Name", ident["first_name"]),
        ("Last Name", ident["last_name"]),
        ("Email", ident["email"]),
        ("Phone", ident["phone_national"]),
        ("LinkedIn Profile", ident.get("linkedin_url", "")),
    ):
        if value:
            _fill_textbox(session_name, snap, label, value)
    answers.update({
        "First Name": ident["first_name"],
        "Last Name": ident["last_name"],
        "Email": ident["email"],
        "Phone": ident["phone_national"],
    })

    # phone country combobox
    snap = p.snapshot(session_name)
    ok, picked = _select_dropdown_option(
        session_name, snap, "Country",
        [f"{auth.get('current_residence_country', 'United Kingdom')} +"],
    )
    if ok:
        answers["Phone Country"] = picked

    # resume upload
    snap = p.snapshot(session_name)
    # the first "Attach" button (button [ref=eXXX]) under the Resume/CV group
    attach_pat = re.compile(r'group "Resume/CV.*?"[^]]*\[ref=e\d+\]:.*?button "Attach" \[ref=(e\d+)\]', re.DOTALL)
    m = attach_pat.search(snap)
    if not m:
        return {"status": "failed", "reason": "greenhouse-resume-attach-button-not-found"}
    p.click(session_name, m.group(1))
    time.sleep(0.5)
    p.upload(session_name, cv_pdf)
    time.sleep(2)

    # custom required dropdowns (best-effort: privacy policy, sponsorship,
    # how-did-you-hear). Iterate the page once more and try each known label.
    snap = p.snapshot(session_name)

    # "Candidate Privacy Policy" — single Acknowledge/Confirm option
    ok, picked = _select_dropdown_option(
        session_name, snap, "Candidate Privacy Policy",
        ["Acknowledge", "Agree", "Yes"],
    )
    if ok:
        answers["Candidate Privacy Policy"] = picked

    # "How did you hear about us" — pick LinkedIn (most accurate origin)
    snap = p.snapshot(session_name)
    ok, picked = _select_dropdown_option(
        session_name, snap, "How did you hear about us",
        ["LinkedIn"],
    )
    if ok:
        answers["How did you hear about us?"] = picked

    # "sponsorship for employment visa status" — Yes/No based on profile
    snap = p.snapshot(session_name)
    sponsorship_answer = "Yes" if sponsorship_required else "No"
    ok, picked = _select_dropdown_option(
        session_name, snap, "sponsorship for employment visa",
        [sponsorship_answer],
    )
    if ok:
        answers["Sponsorship"] = picked

    # voluntary self-id — leave Decline/Prefer-not-to-answer when present
    snap = p.snapshot(session_name)
    for vol_label in ("Gender", "Hispanic/Latino", "Veteran Status", "Disability Status"):
        ok, picked = _select_dropdown_option(
            session_name, snap, vol_label,
            ["Decline", "Prefer not", "I do not", "I don't"],
        )
        if ok:
            answers[vol_label] = picked
            snap = p.snapshot(session_name)  # refs rotate after each pick

    # required consent checkbox (final non-Submit interactive element)
    snap = p.snapshot(session_name)
    consent_pat = re.compile(
        r'checkbox "By checking this box, I agree to allow [^"]+ to store and process my data[^"]*" \[ref=(e\d+)\]'
    )
    cm = consent_pat.search(snap)
    if cm:
        p.pcli(session_name, "check", cm.group(1))
        time.sleep(0.3)
        answers["consent"] = True

    # Screen for fields we did NOT fill before attempting submission.
    # Two complementary checks:
    #   1. DOM query for HTML required inputs that are still empty (most reliable).
    #   2. Snapshot text scan for comboboxes still on "Select..." default.
    snap = p.snapshot(session_name)

    dom_unfilled = p.pcli_eval(
        session_name,
        """(() => {
          const out = [];
          document.querySelectorAll('[required], [aria-required="true"]').forEach(el => {
            if (el.type === 'hidden' || el.disabled) return;
            const val = (el.value || '').trim();
            if (!val || val === 'Select...') {
              const label = (
                el.getAttribute('aria-label') ||
                (el.id && document.querySelector('label[for="' + el.id + '"]')?.textContent) ||
                el.placeholder || el.name || ''
              ).slice(0, 80).trim();
              out.push(label || el.tagName + ':' + el.type);
            }
          });
          return JSON.stringify(out.slice(0, 15));
        })()""",
    )
    snap_unfilled: list[str] = []
    for m in re.finditer(r'combobox "([^"]+)" \[ref=e\d+\]', snap):
        label = m.group(1)
        ctx = snap[m.start():m.start() + 300]
        if "Select..." in ctx:
            snap_unfilled.append(label)

    unfilled: list[str] = []
    if isinstance(dom_unfilled, list):
        unfilled.extend(dom_unfilled)
    unfilled.extend(lbl for lbl in snap_unfilled if lbl not in unfilled)

    # Gate: if any required field is still empty, escalate now with an accurate
    # reason rather than submitting and receiving a misleading
    # "confirmation-not-detected" error.
    if unfilled:
        return {
            "status": "escalate",
            "reason": "greenhouse-required-fields-unfilled",
            "payload": {
                "unfilled_required": unfilled,
                "url": apply_url,
                "answers_filled": answers,
                "note": "One or more required fields were not filled. "
                        "Edge-case agent must complete these before submitting.",
            },
        }

    # submit
    submit_ref = _button_ref(snap, "Submit application")
    if not submit_ref:
        return {"status": "escalate", "reason": "greenhouse-submit-button-missing",
                "payload": {"unfilled_required": unfilled}, "answers": answers}
    p.click(session_name, submit_ref)

    # -- Confirmation detection with retry (Fix 2) --------------------------
    GREENHOUSE_CONFIRM_JS = """(() => {
      const text = document.body.innerText || '';
      const url  = location.href || '';
      const textOk = /Thank you for applying|Application submitted|application has been received|Your application is being processed|successfully submitted|we have received your application|your application has been received|thank you for your application|we.?ve received your|Merci d'avoir postul[ee]|Votre candidature a [ee]t[ee] re[cc]ue|Vielen Dank f[uu]r Ihre Bewerbung|Gracias por postular/i.test(text);
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

    page_text_check = p.detect_confirmation(
        session_name, GREENHOUSE_CONFIRM_JS, initial_delay=4,
    )

    if page_text_check:
        return {
            "status": "applied",
            "submitted_via": "Greenhouse",
            "confirmation": "Thank you for applying",
            "screening": answers,
        }

    # post-submit: check for verification-code gate before failure modes
    snap = p.snapshot(session_name)
    if re.search(r"verification code|security code|8-character code", snap, re.IGNORECASE):
        return {
            "status": "escalate",
            "reason": "greenhouse-email-verification-required",
            "payload": {
                "url": apply_url,
                "host": "greenhouse.io",
                "answers_filled": answers,
                "note": "Form submitted; Greenhouse sent an 8-character code "
                        "to the candidate email. Edge-case agent must fetch "
                        "the code via Gmail MCP and resubmit.",
            },
        }

    # -- Differentiated failure detection (Fix 1) ---------------------------
    failure = p.detect_pre_submit_failure(
        session_name, "greenhouse", url=apply_url, answers=answers,
    )
    if failure:
        return failure

    return {"status": "escalate", "reason": "greenhouse-confirmation-not-detected",
            "payload": {"unfilled_required": unfilled, "answers_filled": answers}}
