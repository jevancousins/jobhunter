"""Lever (`*.lever.co/*/apply`) walker.

Lever's apply forms are reliably simple: name, email, phone, resume, optional
LinkedIn URL, optional GitHub, and a small set of free-text "additional
information" fields (often ungated). Most tenants do NOT require account
creation. Forms are single-page.

If the tenant has added custom screening questions beyond the boilerplate
shape, escalate.
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

    # Lever URLs sometimes need the trailing /apply suffix
    if not apply_url.rstrip("/").endswith("/apply"):
        apply_url = apply_url.rstrip("/") + "/apply"

    profile = _load_profile()
    ident = profile["identity"]

    p.goto(session_name, apply_url, settle=3)
    snap = p.snapshot(session_name)
    if "Submit application" not in snap and "Apply for this role" not in snap and "Resume" not in snap:
        return {"status": "failed", "reason": "lever-form-not-detected"}

    answers: dict = {}
    for label, value in (
        ("Full name", ident["full_name"]),
        ("Email", ident["email"]),
        ("Phone", ident["phone"]),
        ("Current company", ""),
        ("LinkedIn URL", ident.get("linkedin_url", "")),
        ("GitHub URL", ident.get("github_url", "")),
    ):
        if _ref(snap, "textbox", label) and value:
            p.fill_by_label(session_name, label, value)
            time.sleep(0.2)
            answers[label] = value

    # Resume upload via the "Upload Resume" / "Attach a resume" button
    upload_ref = _ref(snap, "button", "Resume") or _ref(snap, "button", "Attach")
    if upload_ref:
        p.click(session_name, upload_ref)
        time.sleep(0.5)
        p.upload(session_name, cv_pdf)
        time.sleep(2)
    else:
        return {"status": "escalate", "reason": "lever-resume-button-not-found",
                "payload": {"url": apply_url}}

    # Detect any extra required fields the form has added — escalate if so.
    # Two-pass check:
    #   1. DOM query for HTML required/aria-required inputs that are still empty
    #      (catches fields not marked with a visible "*" in the label).
    #   2. Snapshot scan for "*"-labelled elements not yet filled.
    snap = p.snapshot(session_name)

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

    # Filter out fields we already filled (name, email, phone, LinkedIn, resume)
    dom_extra: list[tuple[str, str]] = []
    if isinstance(dom_unfilled, list):
        for tag, label in dom_unfilled:
            if not any(a.lower() in label.lower() for a in answers):
                dom_extra.append((tag, label))

    # Snapshot-level check as a fallback (catches visible "*" labels)
    snap_extras = re.findall(r'(textbox|combobox|textarea) "([^"]+\*)"', snap)
    snap_unfilled = [(k, l) for k, l in snap_extras
                     if not any(a.lower() in l.lower() for a in answers)]

    all_unfilled = dom_extra + [(k, l) for k, l in snap_unfilled
                                if (k, l) not in dom_extra]
    if all_unfilled:
        return {"status": "escalate", "reason": "lever-extra-required-fields",
                "payload": {"unfilled": all_unfilled[:10], "url": apply_url}}

    submit_ref = _ref(snap, "button", "Submit application") or _ref(snap, "button", "Submit")
    if not submit_ref:
        return {"status": "escalate", "reason": "lever-submit-button-missing",
                "payload": {"url": apply_url}}
    p.click(session_name, submit_ref)

    # -- Confirmation detection with retry (Fix 2) --------------------------
    LEVER_CONFIRM_JS = """(() => {
      const text = document.body.innerText || '';
      const url  = location.href || '';
      const textOk = /Application submitted|received your application|Thank(?:s| you)|Application received|successfully submitted|we have received your application|your application has been received|thank you for applying|Candidature (?:envoy[ee]e|re[cc]ue)|Bewerbung (?:erhalten|gesendet)/i.test(text);
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

    confirmed = p.detect_confirmation(session_name, LEVER_CONFIRM_JS)
    if confirmed:
        return {
            "status": "applied",
            "submitted_via": "Lever",
            "confirmation": "Application submitted",
            "screening": answers,
        }

    # -- Differentiated failure detection (Fix 1) ---------------------------
    failure = p.detect_pre_submit_failure(
        session_name, "lever", url=apply_url, answers=answers,
    )
    if failure:
        return failure

    return {
        "status": "escalate",
        "reason": "lever-confirmation-not-detected",
        "payload": {"url": apply_url, "answers_filled": answers},
    }
