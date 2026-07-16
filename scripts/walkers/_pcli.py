"""Shared playwright-cli helpers used by walker modules."""
from __future__ import annotations

import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any


def pcli(session: str, *args: str, capture: bool = True, timeout: int = 60) -> str:
    cmd = ["playwright-cli", f"-s={session}", *args]
    res = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
    return res.stdout


def pcli_eval(session: str, js: str, timeout: int = 60) -> Any:
    out = pcli(session, "eval", js, "--raw", timeout=timeout).strip()
    if not out:
        return None
    try:
        val = json.loads(out)
    except json.JSONDecodeError:
        return out
    if isinstance(val, str):
        try:
            return json.loads(val)
        except json.JSONDecodeError:
            return val
    return val


def goto(session: str, url: str, settle: float = 3.0, timeout: int = 30) -> None:
    pcli(session, "goto", url, timeout=timeout)
    time.sleep(settle)


def click(session: str, ref: str, timeout: int = 30) -> str:
    return pcli(session, "click", ref, timeout=timeout)


def fill_by_label(session: str, label_substring: str, value: str, timeout: int = 30) -> bool:
    """Fill an input or textarea by finding it in the live DOM via its accessible
    label, bypassing the stale-ref problem.

    playwright-cli refs (e.g. ref=e886) are generated at snapshot time and are
    invalidated by any subsequent snapshot call or React re-render.  Using a
    ref captured from an earlier snapshot will silently fail (playwright-cli
    returns no error but the fill does not propagate).

    This helper locates the element by label text at fill-time (not snapshot-time)
    and uses the React-native value setter + input/change events, which is the
    same approach proven stable in linkedin_apply.py.

    Returns True if the fill succeeded (element found and value set), False otherwise.
    """
    js = f"""(() => {{
      const want = {json.dumps(label_substring.lower())};
      // Candidate inputs: all visible, non-hidden, non-disabled text-accepting elements.
      const inputs = Array.from(document.querySelectorAll(
        'input[type="text"], input[type="email"], input[type="tel"], ' +
        'input[type="number"], input:not([type]), textarea'
      )).filter(el => !el.disabled && el.type !== 'hidden');

      function labelFor(el) {{
        // 1. aria-label attribute
        let lbl = (el.getAttribute('aria-label') || '').trim();
        if (lbl) return lbl.toLowerCase();
        // 2. label[for=id]
        if (el.id) {{
          const le = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
          if (le) return le.textContent.trim().toLowerCase();
        }}
        // 3. aria-labelledby
        const ids = (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
        if (ids.length) {{
          const t = ids.map(id => {{ const e = document.getElementById(id); return e ? e.textContent.trim() : ''; }}).join(' ').trim();
          if (t) return t.toLowerCase();
        }}
        // 4. nearest ancestor label
        let parent = el.parentElement;
        for (let h = 0; h < 5 && parent; h++) {{
          const lbEl = parent.querySelector('label');
          if (lbEl) return lbEl.textContent.trim().toLowerCase();
          parent = parent.parentElement;
        }}
        // 5. placeholder
        return (el.getAttribute('placeholder') || '').toLowerCase();
      }}

      const match = inputs.find(el => labelFor(el).includes(want));
      if (!match) return false;

      const proto = match.tagName === 'TEXTAREA'
        ? window.HTMLTextAreaElement.prototype
        : window.HTMLInputElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(match, {json.dumps(str(value))});
      match.dispatchEvent(new Event('input', {{bubbles: true}}));
      match.dispatchEvent(new Event('change', {{bubbles: true}}));
      return match.value === {json.dumps(str(value))};
    }})()"""
    result = pcli_eval(session, js, timeout=timeout)
    return bool(result)


def upload(session: str, path: Path, timeout: int = 60) -> str:
    return pcli(session, "upload", str(path), timeout=timeout)


def screenshot(session: str) -> str:
    return pcli(session, "screenshot")


def snapshot(session: str) -> str:
    return pcli(session, "snapshot")


def _safe_name(text: str, fallback: str = "diagnostic") -> str:
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-")
    return name[:80] or fallback


def capture_diagnostics(
    session: str,
    out_dir: Path,
    *,
    reason: str,
    metadata: dict | None = None,
) -> dict:
    """Capture browser state for auditing a failed/escalated application.

    Returns a small dict of artifact paths and never raises; callers should be
    able to attach diagnostics without changing apply outcomes.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _safe_name(reason)
    paths = {
        "dir": str(out_dir),
        "screenshot": str(out_dir / f"{stem}.png"),
        "snapshot": str(out_dir / f"{stem}.snapshot.md"),
        "page": str(out_dir / f"{stem}.page.json"),
        "metadata": str(out_dir / f"{stem}.metadata.json"),
    }

    page: dict[str, Any] = {}
    try:
        pcli(session, "screenshot", "--full-page", "--filename", paths["screenshot"], timeout=30)
    except Exception as e:
        page["screenshot_error"] = str(e)
    try:
        pcli(session, "snapshot", "--boxes", "--filename", paths["snapshot"], timeout=30)
    except Exception as e:
        page["snapshot_error"] = str(e)
    try:
        state = pcli_eval(
            session,
            """(() => JSON.stringify({
              url: location.href,
              title: document.title,
              body_text: document.body ? document.body.innerText.slice(0, 12000) : "",
              buttons: Array.from(document.querySelectorAll("button")).slice(0, 80)
                .map((b, i) => ({
                  idx: i,
                  text: (b.innerText || b.textContent || "").trim(),
                  aria: b.getAttribute("aria-label") || "",
                  disabled: !!b.disabled,
                  type: b.getAttribute("type") || "",
                  visible: !!(b.offsetWidth || b.offsetHeight || b.getClientRects().length)
                })),
              links: Array.from(document.querySelectorAll("a[href]")).slice(0, 80)
                .map((a, i) => ({
                  idx: i,
                  text: (a.innerText || a.textContent || "").trim(),
                  aria: a.getAttribute("aria-label") || "",
                  href: a.href
                })),
              inputs: Array.from(document.querySelectorAll("input, textarea, select")).slice(0, 120)
                .map((el, i) => ({
                  idx: i,
                  tag: el.tagName,
                  type: el.getAttribute("type") || "",
                  name: el.getAttribute("name") || "",
                  id: el.id || "",
                  aria: el.getAttribute("aria-label") || "",
                  required: !!el.required,
                  disabled: !!el.disabled,
                  value: el.type === "password" ? "" : (el.value || "").slice(0, 250)
                }))
            }))()""",
            timeout=30,
        )
        page.update(state if isinstance(state, dict) else {"raw_state": state})
    except Exception as e:
        page["page_state_error"] = str(e)

    payload = {
        "reason": reason,
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "metadata": metadata or {},
        "page": page,
    }
    try:
        Path(paths["page"]).write_text(json.dumps(page, indent=2))
        Path(paths["metadata"]).write_text(json.dumps(payload, indent=2))
    except Exception as e:
        paths["write_error"] = str(e)
    return paths


# -----------------------------------------------------------------
# Post-submit helpers (Fix 1 + Fix 2 from TSK-249)
# -----------------------------------------------------------------

# JS snippet: detect validation errors still visible on the page
_VALIDATION_JS = """(() => {
  const msgs = Array.from(document.querySelectorAll(
    '[class*="error"], [class*="invalid"], [aria-invalid="true"], [class*="Error"]'
  ))
    .map(el => (el.innerText || el.textContent || '').trim())
    .filter(t => t.length > 0 && t.length < 200);
  return JSON.stringify(msgs.slice(0, 8));
})()"""

# JS snippet: detect rate-limit / duplicate-application messages
_RATE_LIMIT_JS = (
    "(() => /already applied|application limit|duplicate application"
    "|you.ve already|previously applied|already submitted"
    "|limit reached|too many applications/i"
    ".test(document.body.innerText))()"
)

# JS snippet: detect spam / bot-detection warnings
_SPAM_JS = (
    "(() => /spam|suspicious activity|not.*human|automated.*submission"
    "|bot detected|captcha|verify you.re human|security check/i"
    ".test(document.body.innerText))()"
)


def detect_pre_submit_failure(
    session: str,
    ats: str,
    *,
    url: str = "",
    answers: dict | list | None = None,
    skip_spam: bool = False,
) -> dict | None:
    """Check for validation errors, rate-limits, and spam flags after submit.

    Returns an escalation dict with a differentiated reason tag, or None if
    none of these failure modes are detected (caller should proceed to
    confirmation detection).
    """
    payload_base: dict = {}
    if url:
        payload_base["url"] = url
    if answers:
        payload_base["answers_filled"] = answers

    # 1. Validation errors (form stayed open with red messages)
    raw = pcli_eval(session, _VALIDATION_JS)
    errors = raw if isinstance(raw, list) else []
    if errors:
        return {
            "status": "escalate",
            "reason": f"{ats}-validation-rejected",
            "payload": {**payload_base, "validation_errors": errors},
        }

    # 2. Rate-limit / duplicate-application
    if pcli_eval(session, _RATE_LIMIT_JS):
        return {
            "status": "escalate",
            "reason": f"{ats}-rate-limited",
            "payload": {
                **payload_base,
                "note": "ATS indicated a duplicate or rate-limited application.",
            },
        }

    # 3. Spam / bot-detection (skip for walkers that handle it themselves)
    if not skip_spam and pcli_eval(session, _SPAM_JS):
        return {
            "status": "escalate",
            "reason": f"{ats}-spam-flag-detected",
            "payload": {
                **payload_base,
                "note": "ATS displayed a spam or bot-detection warning.",
            },
        }

    return None


def detect_confirmation(
    session: str,
    confirmation_js: str,
    *,
    initial_delay: float = 3.0,
    retries: int = 3,
) -> bool:
    """Poll for a confirmation signal with backoff.

    Replaces the old pattern of ``time.sleep(N)`` + single ``pcli_eval``.
    Waits *initial_delay* before the first check, then 2 s between retries.
    Returns True as soon as the JS expression is truthy.
    """
    for attempt in range(retries):
        time.sleep(initial_delay if attempt == 0 else 2)
        result = pcli_eval(session, confirmation_js)
        if result:
            return True
    return False


def is_dialog_open(session: str) -> bool:
    val = pcli_eval(
        session,
        "(() => !!document.querySelector('dialog[aria-label*=\"Apply to\"], [role=\"dialog\"]'))()",
    )
    return bool(val)
