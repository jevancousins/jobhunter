"""LinkedIn Apply form walker.

Drives the SDUI multi-page modal end-to-end for one role. Pure Python; no
LLM calls. Escalates to the orchestrator when it hits a novel field or
low-confidence answer, so the edge-case sub-agent can reason about it.

Verified page sequence (2026-04-29):

    Contact info    →  Resume  →  Top choice (optional)  →
    Additional Questions  →  Review  →  Submit  →  "Application sent"
"""
from __future__ import annotations

import importlib.util
import json
import re
import time
from pathlib import Path
from typing import Any

from . import _pcli as p

ROOT = Path(__file__).resolve().parent.parent.parent
_spec = importlib.util.spec_from_file_location(
    "answer_screening", ROOT / "scripts" / "answer_screening.py"
)
_answer = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_answer)

_ai_spec = importlib.util.spec_from_file_location(
    "ai_screening", ROOT / "scripts" / "ai_screening.py"
)
_ai_screening = importlib.util.module_from_spec(_ai_spec)
_ai_spec.loader.exec_module(_ai_screening)

_uc_spec = importlib.util.spec_from_file_location(
    "user_config", ROOT / "scripts" / "user_config.py"
)
_user_config = importlib.util.module_from_spec(_uc_spec)
_uc_spec.loader.exec_module(_user_config)


def _rtw_label_js_pattern() -> str:
    """JS regex source matching the candidate's right-to-work option labels.

    Built from candidate.right_to_work_labels in data/search_config.json,
    normalised the same way as the radio option text in _apply_radio_answer
    (lowercase, apostrophes stripped, whitespace collapsed). Returns a
    never-matching pattern when no labels are configured.
    """
    labels = (
        _user_config.load_search_config()
        .get("candidate", {})
        .get("right_to_work_labels")
        or []
    )
    parts = []
    for label in labels:
        norm = str(label).lower().replace("’", "").replace("'", "")
        norm = re.sub(r"\s+", " ", norm).strip()
        if norm:
            # re.escape backslash-escapes spaces, which JS regexes only
            # tolerate via legacy identity escapes; keep spaces literal.
            parts.append(re.escape(norm).replace("\\ ", " "))
    if not parts:
        return r"$^"  # never matches
    return r"\b(" + "|".join(parts) + r")\b"


_RTW_LABEL_JS_PATTERN = _rtw_label_js_pattern()


CONFIDENCE_FLOOR = 0.7
MAX_PAGES = 8  # safety bound — LinkedIn Apply is at most 6 pages
MAX_FIELDS_PER_PAGE = 50


# ---------------------------------------------------------------------------
# DOM probes
# ---------------------------------------------------------------------------

def _dialog_state(session: str) -> dict:
    """Return {open, heading, page} where page identifies which step we are on."""
    return p.pcli_eval(
        session,
        """(() => {
          const dlg = document.querySelector('dialog[aria-label*="Apply to"], [role="dialog"]');
          if (!dlg) return JSON.stringify({open: false});
          const heading = dlg.querySelector('h2')?.textContent?.trim() || '';
          const subHeadings = Array.from(dlg.querySelectorAll('h3,h4'))
            .map(h => h.textContent.trim());
          const pb = dlg.querySelector('[role="progressbar"]');
          const progress = pb ? pb.getAttribute('aria-valuenow') : '';
          const buttons = Array.from(dlg.querySelectorAll('button'))
            .map(b => b.textContent.trim()).filter(t => t.length < 60);
          // classify
          let page = 'unknown';
          const sub = subHeadings.join(' | ');
          const buttonText = buttons.join(' | ');
          if (/Submit application|Soumettre|Envoyer ma candidature|Bewerbung absenden|Enviar solicitud/i.test(buttonText)) page = 'review';
          else if (/Review your application|V[ée]rifiez votre candidature|Revisar tu solicitud|Bewerbung [üu]berpr[üu]fen/i.test(heading)) page = 'review';
          else if (/Contact info|Coordonn[ée]es|Datos de contacto|Kontaktinformationen/i.test(sub)) page = 'contact';
          else if (/Resume|Curriculum vitae|CV|Lebenslauf/i.test(sub)) page = 'resume';
          else if (/top choice|premier choix/i.test(sub)) page = 'top_choice';
          else if (/Work experience|Exp[ée]rience professionnelle|Berufserfahrung|Experiencia laboral/i.test(sub)) page = 'work_experience';
          else if (/Education|Formation|Ausbildung|Educaci[óo]n/i.test(sub)) page = 'education';
          else if (/Additional Questions|Questions suppl[ée]mentaires|Preguntas adicionales|Weitere Fragen/i.test(sub)) page = 'additional';
          else if (/Work authori[sz]ation|Right to work|Work permit|Autorisation de travail/i.test(sub)) page = 'work_authorization';
          else if (/Review your application|V[ée]rifiez votre candidature|Revisar tu solicitud|Bewerbung [üu]berpr[üu]fen/i.test(sub)) page = 'review';
          return JSON.stringify({open: true, heading, sub_headings: subHeadings,
                                  progress, page, buttons});
        })()""",
    )


def _find_button_ref(session: str, text_pattern: str) -> str | None:
    """Find the latest snapshot ref of a button whose accessible name matches
    the pattern. Refs rotate after every fill so this MUST be re-run before
    each click."""
    out = p.snapshot(session)
    # snapshot output uses YAML-ish format: `- button "text" [ref=eXXX]`
    import re
    pat = re.compile(rf'button "([^"]*{re.escape(text_pattern)}[^"]*)" \[ref=(e\d+)\]')
    m = pat.search(out)
    if m:
        return m.group(2)
    # also try link refs (e.g. "LinkedIn Apply to this job" is a link)
    pat = re.compile(rf'link "([^"]*{re.escape(text_pattern)}[^"]*)" \[ref=(e\d+)\]')
    m = pat.search(out)
    return m.group(2) if m else None


# Locale-aware "Continue / Next" button finder. LinkedIn localises button
# labels to the user's UI language, so a hard-coded English string fails on
# French / German / Spanish job postings. Try the canonical English first,
# then known translations.
_CONTINUE_LABELS = (
    "Continue to next step",
    "Continue",
    "Next",
    "Continuer",        # French
    "Étape suivante",   # French
    "Suivant",          # French
    "Weiter",           # German
    "Siguiente",        # Spanish
    "Continuar",        # Spanish/Portuguese
)


_REVIEW_LABELS = (
    "Review your application",
    "Review",
    "Vérifiez votre candidature",
    "Revisar tu solicitud",
    "Bewerbung überprüfen",
    "Bewerbung ueberpruefen",
)


def _find_continue_ref(session: str) -> str | None:
    """Find a 'Continue/Next' button across LinkedIn UI locales."""
    for label in _CONTINUE_LABELS:
        ref = _find_button_ref(session, label)
        if ref:
            return ref
    return None


def _scroll_dialog(session: str, direction: str = "down") -> bool:
    """Scroll the LinkedIn Apply modal, not the page behind it."""
    val = p.pcli_eval(
        session,
        f"""(() => {{
          const dlg = document.querySelector('dialog[aria-label*="Apply to"], [role="dialog"]');
          if (!dlg) return false;
          const nodes = [dlg, ...Array.from(dlg.querySelectorAll('*'))];
          const scrollables = nodes
            .filter(el => el.scrollHeight > el.clientHeight + 24)
            .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight));
          const el = scrollables[0] || dlg;
          const direction = {json.dumps(direction)};
          if (direction === 'top') el.scrollTo(0, 0);
          else if (direction === 'bottom') el.scrollTo(0, el.scrollHeight);
          else el.scrollBy(0, Math.max(480, Math.floor(el.clientHeight * 0.8)));
          return true;
        }})()""",
    )
    time.sleep(0.5)
    return bool(val)


def _find_button_ref_scrolled(session: str, labels: tuple[str, ...], *, attempts: int = 5) -> str | None:
    """Find a modal button, scrolling the modal down between snapshot probes."""
    for i in range(attempts):
        for label in labels:
            ref = _find_button_ref(session, label)
            if ref:
                return ref
        if i < attempts - 1:
            _scroll_dialog(session, "top" if i == 0 else "down")
    return None


def _find_next_step_ref(session: str) -> str | None:
    """Find LinkedIn's next-step button, including the pre-submit Review step."""
    return _find_button_ref_scrolled(session, _CONTINUE_LABELS + _REVIEW_LABELS)


# ---------------------------------------------------------------------------
# page handlers
# ---------------------------------------------------------------------------

def _open_modal(session: str, role_url: str) -> bool:
    """Navigate directly to the apply URL — more reliable than clicking the
    link, which is intercepted by the cookie banner if not dismissed.

    Retries the dialog check once with an extra settle delay: LinkedIn's SDUI
    can render the modal frame slightly after the page load event, causing the
    first is_dialog_open probe to miss a modal that is visually present and
    scrolled into view.
    """
    apply_url = role_url.rstrip("/") + "/apply/?openSDUIApplyFlow=true"
    p.goto(session, apply_url, settle=5)
    if p.is_dialog_open(session):
        return True
    # Modal present but not yet fully painted (or below initial viewport) —
    # scroll it into view and retry once.
    p.pcli_eval(
        session,
        """(() => {
          const dlg = document.querySelector('dialog, [role="dialog"]');
          if (dlg) dlg.scrollIntoView();
        })()""",
    )
    time.sleep(2)
    return p.is_dialog_open(session)


def _is_no_longer_accepting(session: str) -> bool:
    val = p.pcli_eval(
        session,
        """(() => /no longer accepting applications|applications are no longer being accepted|job is no longer accepting/i.test(document.body.innerText || ''))()""",
    )
    return bool(val)


def _handle_contact(session: str) -> tuple[str, str]:
    """Page 1 is fully pre-filled. Return ("ok"|"escalate"|"failed", reason)."""
    ref = _find_next_step_ref(session)
    if not ref:
        return ("failed", "no-continue-button-on-contact")
    p.click(session, ref)
    time.sleep(3)
    return ("ok", "")


def _handle_resume(session: str, cv_pdf: Path) -> tuple[str, str]:
    upload_ref = _find_button_ref_scrolled(session, ("Upload resume", "Upload CV", "Téléverser", "Hochladen", "Subir"))
    if not upload_ref:
        return ("failed", "no-upload-button")
    p.click(session, upload_ref)
    time.sleep(1)
    p.upload(session, cv_pdf)
    time.sleep(4)
    # verify our PDF is now the selected resume
    fname = cv_pdf.name
    snap = p.snapshot(session)
    if fname not in snap:
        return ("failed", f"upload-not-confirmed: {fname}")
    cont = _find_next_step_ref(session)
    if not cont:
        return ("failed", "no-continue-after-upload")
    p.click(session, cont)
    time.sleep(3)
    return ("ok", "")


def _handle_top_choice(session: str) -> tuple[str, str]:
    """Optional toggle — leave unchecked, just continue."""
    cont = _find_next_step_ref(session)
    if not cont:
        return ("failed", "no-continue-on-top-choice")
    p.click(session, cont)
    time.sleep(3)
    return ("ok", "")


def _enumerate_additional_fields(session: str) -> list[dict]:
    """Read the visible Additional Questions form. Returns a list of fields:
        {kind: 'radio_group', label, options: [{value, checked, idx}], idx}
        {kind: 'textbox', label, value}
        {kind: 'combobox', label, value, options: [...]}          # native <select>
        {kind: 'custom_combobox', label, value, id, idx}          # ARIA role=combobox
        {kind: 'checkbox', label, checked}
    """
    val = p.pcli_eval(
        session,
        """(() => {
          const dlg = document.querySelector('dialog[aria-label*="Apply to"], [role="dialog"]');
          if (!dlg) return JSON.stringify([]);
          const out = [];

          // Helper: resolve a label for any element by aria-label, label[for=id],
          // or nearest ancestor containing a <label>.
          function resolveLabel(el, scope) {
            let label = (el.getAttribute('aria-label') || '').trim();
            if (!label && el.id) {
              const lblEl = scope.querySelector(`label[for="${CSS.escape(el.id)}"]`);
              if (lblEl) label = lblEl.textContent.trim().split('\\n')[0].trim();
            }
            if (!label) {
              let parent = el.parentElement;
              for (let h = 0; h < 6 && parent && parent !== scope; h++) {
                const lbl = parent.querySelector('label');
                if (lbl) { label = lbl.textContent.trim().split('\\n')[0].trim(); break; }
                parent = parent.parentElement;
              }
            }
            // Also check aria-labelledby
            if (!label) {
              const ids = (el.getAttribute('aria-labelledby') || '').split(/\\s+/).filter(Boolean);
              if (ids.length) {
                label = ids.map(id => { const e = document.getElementById(id); return e ? e.textContent.trim() : ''; }).join(' ').trim();
              }
            }
            return label;
          }

          // radio groups (fieldsets with input[type=radio])
          const fieldsets = Array.from(dlg.querySelectorAll('fieldset'));
          fieldsets.forEach((f, i) => {
            const radios = Array.from(f.querySelectorAll('input[type=radio]'));
            if (radios.length === 0) return;
            const lg = f.querySelector('legend');
            // Fall back to resolveLabel on the fieldset itself if legend is absent/empty
            let label = lg ? lg.textContent.trim().split('\\n')[0].trim() : '';
            if (!label) label = resolveLabel(f, dlg);
            // Last resort: use the group label from the first radio's aria context
            if (!label && radios[0]) label = resolveLabel(radios[0], dlg);
            const options = radios.map((r, j) => {
              const lbl = r.id ? f.querySelector(`label[for="${CSS.escape(r.id)}"]`) : null;
              return {value: r.value, label: lbl ? lbl.textContent.trim() : '', checked: r.checked, idx: j, id: r.id};
            });
            out.push({kind: 'radio_group', label, options, idx: i,
                      required: f.querySelector('[required],[aria-required="true"]') !== null});
          });

          // standalone textboxes / number inputs (not inside a fieldset)
          // Exclude inputs that are part of a custom ARIA combobox (handled below)
          const textInputs = Array.from(dlg.querySelectorAll('input[type=text], input[type=number], input:not([type])'));
          textInputs.forEach((inp, i) => {
            if (inp.closest('fieldset')) return;
            if (inp.getAttribute('role') === 'combobox') return; // handled in custom_combobox block
            const label = resolveLabel(inp, dlg);
            out.push({kind: 'textbox', label, value: inp.value, id: inp.id, idx: i,
                      required: inp.required || inp.getAttribute('aria-required') === 'true'});
          });

          // textareas (cover letter, long-form)
          const textareas = Array.from(dlg.querySelectorAll('textarea'));
          textareas.forEach((ta, i) => {
            const label = resolveLabel(ta, dlg) || (ta.getAttribute('aria-label') || '').trim();
            out.push({kind: 'textarea', label, value: ta.value, id: ta.id, idx: i,
                      required: ta.required || ta.getAttribute('aria-required') === 'true'});
          });

          // checkboxes (inside OR outside fieldsets — LinkedIn sometimes wraps
          // standalone checkboxes in a fieldset with no radios)
          const checkboxes = Array.from(dlg.querySelectorAll('input[type=checkbox]'));
          checkboxes.forEach((cb, i) => {
            const label = resolveLabel(cb, dlg);
            out.push({kind: 'checkbox', label, checked: cb.checked, id: cb.id, idx: i,
                      required: cb.required || cb.getAttribute('aria-required') === 'true'});
          });

          // Native comboboxes / selects — include label resolution via label[for]
          const selects = Array.from(dlg.querySelectorAll('select'));
          selects.forEach((s, i) => {
            const label = resolveLabel(s, dlg);
            const options = Array.from(s.options).map(o => ({value: o.value, text: o.text}));
            out.push({kind: 'combobox', label, value: s.value, id: s.id, options, idx: i,
                      required: s.required || s.getAttribute('aria-required') === 'true'});
          });

          // Custom ARIA comboboxes — LinkedIn SDUI uses input[role="combobox"] for
          // typeahead-style dropdowns that are NOT native <select> elements.
          // These are completely invisible to the 'select' query above.
          const ariaComboboxes = Array.from(dlg.querySelectorAll('[role="combobox"]'));
          ariaComboboxes.forEach((el, i) => {
            if (el.tagName === 'SELECT') return; // already handled above
            const label = resolveLabel(el, dlg);
            // Collect any already-visible listbox options (opened state)
            const listboxId = el.getAttribute('aria-controls') || el.getAttribute('aria-owns') || '';
            const listboxEl = listboxId ? document.getElementById(listboxId) : null;
            const visibleOptions = listboxEl
              ? Array.from(listboxEl.querySelectorAll('[role="option"]')).map(o => ({
                  value: o.getAttribute('data-value') || o.textContent.trim(),
                  text: o.textContent.trim(),
                  id: o.id || ''
                }))
              : [];
            out.push({kind: 'custom_combobox', label,
                      value: (el.value || el.textContent || '').trim(),
                      id: el.id || '', idx: i,
                      aria_controls: listboxId,
                      visible_options: visibleOptions,
                      required: el.getAttribute('aria-required') === 'true'
                                || (el.closest('[aria-required="true"]') !== null)});
          });

          return JSON.stringify(out);
        })()""",
    )
    return val if isinstance(val, list) else []


def _apply_radio_answer(
    session: str,
    field_idx: int,
    answer_value: str,
    preferred_option_substring: str | None = None,
) -> bool:
    """Click the radio whose value/label matches answer_value.

    LinkedIn sometimes phrases right-to-work options as nationality labels
    (e.g. "I'm a citizen of <country>") while the deterministic answer bank
    returns the canonical Yes/No; candidate.right_to_work_labels in
    data/search_config.json lists the phrasings that mean "Yes" for this
    candidate.
    """
    val = p.pcli_eval(
        session,
        f"""(() => {{
          const dlg = document.querySelector('dialog[aria-label*="Apply to"], [role="dialog"]');
          const fs = Array.from(dlg.querySelectorAll('fieldset'))[{field_idx}];
          if (!fs) return false;
          const norm = (s) => String(s || '').toLowerCase().replace(/[’']/g, '').replace(/\\s+/g, ' ').trim();
          const want = norm({json.dumps(str(answer_value))});
          const preferred = norm({json.dumps(preferred_option_substring or "")});
          const radios = Array.from(fs.querySelectorAll('input[type=radio]'));
          const textFor = (r) => {{
            const lbl = r.id ? fs.querySelector(`label[for="${{CSS.escape(r.id)}}"]`) : null;
            return norm([r.value, r.getAttribute('aria-label'), lbl ? lbl.textContent : ''].join(' '));
          }};
          const rightToWorkLabel = new RegExp({json.dumps(_RTW_LABEL_JS_PATTERN)});
          const match = radios.find(r => {{
            const txt = textFor(r);
            if (preferred && txt.includes(preferred)) return true;
            if (norm(r.value) === want || txt === want) return true;
            if (want === 'yes' && rightToWorkLabel.test(txt)) return true;
            if (want === 'yes' && /\\byes\\b/.test(txt)) return true;
            if (want === 'no' && /\\bno\\b/.test(txt)) return true;
            return false;
          }});
          if (!match) return false;
          const lbl = fs.querySelector(`label[for="${{CSS.escape(match.id)}}"]`);
          if (lbl) lbl.click(); else match.click();
          return match.checked;
        }})()""",
    )
    return bool(val)


def _apply_text_answer(session: str, input_id: str, value: str) -> bool:
    """Set a textbox/textarea via the React-native event setter so SDUI
    server-side validation accepts it. Plain `playwright-cli fill` does not
    propagate the event in LinkedIn's React app."""
    val = p.pcli_eval(
        session,
        f"""(() => {{
          const el = document.getElementById({json.dumps(input_id)});
          if (!el) return 'no-el';
          const proto = el.tagName === 'TEXTAREA'
            ? window.HTMLTextAreaElement.prototype
            : window.HTMLInputElement.prototype;
          const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
          setter.call(el, {json.dumps(str(value))});
          el.dispatchEvent(new Event('input', {{bubbles: true}}));
          el.dispatchEvent(new Event('change', {{bubbles: true}}));
          return el.value;
        }})()""",
    )
    return val == str(value)


def _clear_textarea(session: str, input_id: str, textarea_idx: int | None = None) -> bool:
    """Clear a textarea via ID, falling back to position index within the dialog.

    LinkedIn cover-letter textareas often have no stable id attribute, and the
    field may be pre-populated asynchronously after the initial page scan.
    We therefore:
      1. Try getElementById (fast path when id is present).
      2. Fall back to querySelectorAll('textarea')[idx] inside the dialog.
      3. Verify the field is actually empty after clearing and log if not.
    """
    import time as _time
    js = f"""(() => {{
      const dlg = document.querySelector('[role="dialog"]') || document.body;
      let el = {json.dumps(input_id)} ? document.getElementById({json.dumps(input_id)}) : null;
      if (!el && {json.dumps(textarea_idx)} !== null) {{
        el = Array.from(dlg.querySelectorAll('textarea'))[{json.dumps(textarea_idx)}] || null;
      }}
      if (!el) return 'no-el';
      const proto = window.HTMLTextAreaElement.prototype;
      const setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
      setter.call(el, '');
      el.dispatchEvent(new Event('input', {{bubbles: true}}));
      el.dispatchEvent(new Event('change', {{bubbles: true}}));
      return el.value;
    }})()"""
    val = p.pcli_eval(session, js)
    if val != "":
        # LinkedIn sometimes re-populates after a short delay — try once more
        _time.sleep(0.5)
        val = p.pcli_eval(session, js)
    return val == ""


def _apply_combobox_answer(
    session: str,
    input_id: str,
    value: str,
    preferred_option_substring: str | None = None,
) -> bool:
    val = p.pcli_eval(
        session,
        f"""(() => {{
          const el = document.getElementById({json.dumps(input_id)});
          if (!el) return false;
          const want = String({json.dumps(str(value))}).toLowerCase().trim();
          const preferred = String({json.dumps(preferred_option_substring or "")}).toLowerCase().trim();
          if (el.options) {{
            const opts = Array.from(el.options);
            const match = (preferred ? opts.find(o => String(o.text).toLowerCase().includes(preferred) || String(o.value).toLowerCase().includes(preferred)) : null)
              || opts.find(o => String(o.value).toLowerCase().trim() === want)
              || opts.find(o => String(o.text).toLowerCase().trim() === want)
              || opts.find(o => String(o.text).toLowerCase().includes(want));
            if (match) {{
              const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
              setter.call(el, match.value);
              el.dispatchEvent(new Event('change', {{bubbles: true}}));
              return el.value === match.value;
            }}
          }}
          const setter = Object.getOwnPropertyDescriptor(window.HTMLSelectElement.prototype, 'value').set;
          setter.call(el, {json.dumps(str(value))});
          el.dispatchEvent(new Event('change', {{bubbles: true}}));
          return el.value === {json.dumps(str(value))};
        }})()""",
    )
    return bool(val)


def _apply_custom_combobox_answer(
    session: str,
    input_id: str,
    value: str,
    preferred_option_substring: str | None = None,
) -> bool:
    """Fill a LinkedIn ARIA custom combobox (role='combobox' on an <input>).

    LinkedIn's SDUI renders dropdowns as typeahead inputs with an associated
    listbox.  Strategy:
      1. Type the desired value into the input (triggers React state + the
         dropdown to open).
      2. Wait briefly for the listbox options to appear.
      3. Click the best-matching [role='option'] item.
      4. If no option appeared, fall back to direct value-setter (for free-text
         comboboxes that accept arbitrary input).
    """
    # Step 1: type into the input to trigger the dropdown
    if not _apply_text_answer(session, input_id, value):
        return False
    time.sleep(1.2)

    # Step 2 & 3: click best matching option in any visible listbox
    val = p.pcli_eval(
        session,
        f"""(() => {{
          const norm = (s) => String(s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
          const want = norm({json.dumps(str(value))});
          const preferred = norm({json.dumps(preferred_option_substring or "")});
          // Gather all listbox options currently in the DOM (the listbox may be
          // attached anywhere — not necessarily inside the dialog)
          const candidates = Array.from(document.querySelectorAll(
            '[role="option"], [role="listbox"] [role="option"], ' +
            '[role="listbox"] li, .basic-typeahead__selectable'
          ));
          if (candidates.length === 0) return 'no-options';
          const match = (preferred
              ? candidates.find(el => norm(el.innerText || el.textContent).includes(preferred))
              : null)
            || candidates.find(el => norm(el.innerText || el.textContent) === want)
            || candidates.find(el => norm(el.innerText || el.textContent).includes(want))
            || candidates[0];  // best-guess first option
          if (!match) return 'no-match';
          match.click();
          return 'clicked:' + norm(match.innerText || match.textContent).slice(0, 60);
        }})()""",
    )
    time.sleep(0.5)
    if isinstance(val, str) and val.startswith("clicked:"):
        return True
    # Fallback: no listbox — the field may accept free text; value was already set
    return False


def _apply_checkbox_answer(session: str, input_id: str, desired_checked: bool) -> bool:
    """Check or uncheck a checkbox with proper React event dispatch.

    Unlike raw `.click()` or the element's `checked` setter, this fires the
    full synthetic event chain that LinkedIn's React SDUI expects so that form
    validation state updates correctly.
    """
    val = p.pcli_eval(
        session,
        f"""(() => {{
          const el = document.getElementById({json.dumps(input_id)});
          if (!el) return 'no-el';
          const current = el.checked;
          const desired = {json.dumps(desired_checked)};
          if (current === desired) return 'already-correct';
          // React requires a native setter call + synthetic events
          const setter = Object.getOwnPropertyDescriptor(
            window.HTMLInputElement.prototype, 'checked').set;
          setter.call(el, desired);
          el.dispatchEvent(new MouseEvent('click', {{bubbles: true, cancelable: true}}));
          el.dispatchEvent(new Event('change', {{bubbles: true}}));
          return el.checked === desired ? 'ok' : 'mismatch';
        }})()""",
    )
    return val in ("ok", "already-correct")


def _apply_typeahead_answer(
    session: str,
    input_id: str,
    typed_value: str,
    preferred_option_substring: str | None = None,
) -> bool:
    if not _apply_text_answer(session, input_id, typed_value):
        return False
    time.sleep(1)
    val = p.pcli_eval(
        session,
        f"""(() => {{
          const norm = (s) => String(s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
          const preferred = norm({json.dumps(preferred_option_substring or typed_value)});
          const typed = norm({json.dumps(typed_value)});
          const candidates = Array.from(document.querySelectorAll('[role="option"], [role="listbox"] li, [role="listbox"] div, .basic-typeahead__selectable'));
          const match = candidates.find(el => norm(el.innerText || el.textContent).includes(preferred))
            || candidates.find(el => norm(el.innerText || el.textContent).includes(typed));
          if (!match) return false;
          match.click();
          return true;
        }})()""",
    )
    time.sleep(0.5)
    return bool(val)


def _fill_required_fallback(session: str) -> dict:
    """Last-resort sweep: fill any still-empty required fields before advancing.

    Called just before clicking Continue on the additional-questions page to
    catch fields that were missed or not enumerated by _enumerate_additional_fields
    (e.g. hidden-until-revealed fields, or fields that appeared after earlier fills).

    Strategy per element type:
      - Native <select> with a blank/placeholder value: pick the first non-blank option.
      - input[role=combobox] still empty: already typed in _handle_additional; skip.
      - input[type=checkbox] that is required and unchecked: check it.
      - input[type=radio] fieldset where nothing is checked: click the first radio.

    Returns a summary dict for logging.
    """
    result = p.pcli_eval(
        session,
        """(() => {
          const dlg = document.querySelector('dialog[aria-label*="Apply to"], [role="dialog"]');
          if (!dlg) return JSON.stringify({filled: [], skipped: []});
          const filled = [];
          const skipped = [];

          // Helper: React-aware value setter for inputs/selects
          function setNativeValue(el, value) {
            const proto = el.tagName === 'SELECT'
              ? window.HTMLSelectElement.prototype
              : el.tagName === 'TEXTAREA'
                ? window.HTMLTextAreaElement.prototype
                : window.HTMLInputElement.prototype;
            const setter = Object.getOwnPropertyDescriptor(proto, 'value');
            if (setter && setter.set) setter.set.call(el, value);
            el.dispatchEvent(new Event('input', {bubbles: true}));
            el.dispatchEvent(new Event('change', {bubbles: true}));
          }

          // 1. Native selects still on placeholder ("" or index 0 with empty text)
          Array.from(dlg.querySelectorAll('select')).forEach(sel => {
            const isReq = sel.required || sel.getAttribute('aria-required') === 'true';
            if (!isReq) return;
            const val = (sel.value || '').trim();
            if (val && val !== '0' && val !== 'select' && val.toLowerCase() !== 'none') return;
            // Find first non-empty, non-placeholder option
            const opts = Array.from(sel.options);
            const pick = opts.find(o => o.value && o.value !== '0'
              && o.text.trim() && !/^(select|choose|please select|--)/i.test(o.text.trim()));
            if (pick) {
              setNativeValue(sel, pick.value);
              filled.push({type: 'select', id: sel.id, chosen: pick.text});
            } else {
              skipped.push({type: 'select', id: sel.id, reason: 'no-non-blank-option'});
            }
          });

          // 2. Required checkboxes that are unchecked
          // LinkedIn screening sometimes has required "I agree to the terms" checkboxes
          // that must be checked to advance.
          Array.from(dlg.querySelectorAll('input[type=checkbox]')).forEach(cb => {
            const isReq = cb.required || cb.getAttribute('aria-required') === 'true';
            if (!isReq || cb.checked) return;
            // Only auto-check if the checkbox has a visible label (to avoid
            // accidentally accepting hidden consent boxes).
            const hasSiblingLabel = !!(cb.id && dlg.querySelector(`label[for="${CSS.escape(cb.id)}"]`))
              || !!(cb.getAttribute('aria-label'));
            if (!hasSiblingLabel) {
              skipped.push({type: 'checkbox', id: cb.id, reason: 'no-visible-label'});
              return;
            }
            const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'checked').set;
            setter.call(cb, true);
            cb.dispatchEvent(new MouseEvent('click', {bubbles: true, cancelable: true}));
            cb.dispatchEvent(new Event('change', {bubbles: true}));
            filled.push({type: 'checkbox', id: cb.id});
          });

          // 3. Required radio fieldsets where nothing is checked — select first option
          Array.from(dlg.querySelectorAll('fieldset')).forEach(fs => {
            const radios = Array.from(fs.querySelectorAll('input[type=radio]'));
            if (radios.length === 0) return;
            const isReq = !!fs.querySelector('[required],[aria-required="true"]');
            if (!isReq) return;
            const anyChecked = radios.some(r => r.checked);
            if (anyChecked) return;
            // Click the first radio's associated label (or the radio itself)
            const first = radios[0];
            const lbl = first.id ? fs.querySelector(`label[for="${CSS.escape(first.id)}"]`) : null;
            if (lbl) lbl.click(); else first.click();
            filled.push({type: 'radio', fieldset_idx: Array.from(dlg.querySelectorAll('fieldset')).indexOf(fs), chosen_value: first.value});
          });

          return JSON.stringify({filled, skipped});
        })()""",
    )
    if isinstance(result, dict):
        return result
    return {"filled": [], "skipped": []}


def _handle_additional(
    session: str, country: str, role_context: dict | None = None
) -> tuple[str, dict | str]:
    """Walk every visible field, resolve via answer_screening, fill or escalate."""
    fields = _enumerate_additional_fields(session)
    answers: dict[str, Any] = {}
    profile = _answer.load_profile()
    role_context = role_context or {}
    for f in fields:
        label = (f.get("label") or "").strip()
        # Build a usable label even when the DOM yields nothing — use the field
        # kind + position so answer_screening can at least be queried (it will
        # return confidence=0 / needs_human=True which triggers escalation rather
        # than silently skipping a potentially required field).
        if not label:
            label = f"{f['kind']}_{f.get('idx', 0)}"
        # Trim duplicated text and the trailing "Required" suffix that LinkedIn
        # injects into legends/labels; helps exact-label match in answer_screening.
        # e.g. "Are you legally authorized?Are you legally authorized?\n  Required"
        label_clean = label.split("\n")[0].strip()
        if len(label_clean) > 10 and label_clean[: len(label_clean) // 2] == label_clean[len(label_clean) // 2 :]:
            label_clean = label_clean[: len(label_clean) // 2]
        # Strip trailing " Required" / " *" that LinkedIn appends to some labels
        label_clean = label_clean.removesuffix(" Required").removesuffix(" *").strip()

        # query answer_screening
        try:
            ans = _answer.answer_question(label_clean, profile, country=country)
        except Exception as e:
            return ("escalate", {"reason": "answer_screening_error",
                                  "label": label_clean, "error": str(e)})
        if ans.get("needs_human"):
            # Only escalate for required fields; skip optional unlabelled ones
            is_required = f.get("required", False)
            if not is_required and not (f.get("label") or "").strip():
                continue  # unlabelled optional — leave alone

            # --- AI drafter + reviewer gate ---
            # Try the two-phase AI layer before falling through to human
            # escalation.  Any error or non-APPROVED verdict falls back to
            # the existing escalation path.  The AI draft is always passed
            # through in the escalation payload so MANUAL-APPLY.md can show
            # it as a suggested answer even when not auto-filled.
            try:
                ai_result = _ai_screening.ai_draft_and_review(
                    label_clean, f, role_context, country
                )
            except Exception as _ai_err:
                import sys as _sys
                print(f"  ai_screening error (ignored): {_ai_err}", file=_sys.stderr)
                ai_result = {"verdict": "FALLBACK", "reason": str(_ai_err),
                             "draft": None, "review": None}

            ai_verdict = ai_result.get("verdict", "FALLBACK")

            if ai_verdict == "APPROVED":
                # Both drafter and reviewer agreed — use the AI answer
                ans = ai_result["answer_obj"]
                # Continue to the field-filling block below (do not return)
            else:
                # Not approved: escalate, but include AI draft for human reviewer
                escalate_payload = {
                    "reason": "needs_human",
                    "label": label_clean,
                    "rationale": ans.get("rationale", ""),
                    "ai_verdict": ai_verdict,
                    "ai_reason": ai_result.get("reason", ""),
                    "ai_category": ai_result.get("category", ""),
                    "ai_draft": ai_result.get("draft"),
                    "ai_review": ai_result.get("review"),
                }
                # For informational mode, add the suggested answer so
                # MANUAL-APPLY.md can display it as a pre-filled suggestion.
                if ai_verdict == "INFORMATIONAL":
                    escalate_payload["ai_suggested_answer"] = ai_result.get("suggested_answer")
                return ("escalate", escalate_payload)
        if ans.get("confidence", 0) < CONFIDENCE_FLOOR:
            return ("escalate", {"reason": "low_confidence",
                                  "label": label_clean,
                                  "confidence": ans.get("confidence"),
                                  "field_kind": f["kind"]})
        kind = ans.get("kind") or ""
        # generate-cover-letter or long-form — escalate to writer sub-agent
        if kind in ("generate_cover_letter", "long_form", "compute_salary_per_role"):
            return ("escalate", {"reason": kind, "label": label_clean,
                                  "field_kind": f["kind"], "field_id": f.get("id")})

        answer_value = ans.get("answer")
        # apply by field kind
        if f["kind"] == "radio_group":
            ok = _apply_radio_answer(
                session,
                f["idx"],
                str(answer_value),
                ans.get("preferred_option_substring"),
            )
            if not ok:
                # check: maybe the radios accept the canonical "No"/"Yes" but
                # answer_value is e.g. "no" (lowercase) — answer_screening
                # tends to return capitalised. If still fails, escalate.
                return ("escalate", {"reason": "radio_value_unmatched",
                                      "label": label_clean, "answer": answer_value,
                                      "options": f.get("options", [])})
        elif f["kind"] in ("textbox", "textarea"):
            if kind == "clear_then_skip":
                # Always attempt to clear regardless of the scanned value —
                # LinkedIn pre-populates cover-letter fields asynchronously
                # after the initial page scan, so f["value"] may appear empty
                # even when LinkedIn will actually submit the previous role's letter.
                cleared = _clear_textarea(session, f.get("id") or "", f.get("idx"))
                if not cleared:
                    import sys as _sys
                    print(f"  WARNING: could not clear cover-letter textarea (id={f.get('id')!r} idx={f.get('idx')!r}) — old letter may be sent", file=_sys.stderr)
                continue
            # skip_optional: clear only if the field was pre-populated
            if kind == "skip_optional" and (f.get("value") or "").strip():
                _clear_textarea(session, f.get("id") or "", f.get("idx"))
                continue
            if answer_value is None or answer_value == "":
                continue  # leave blank
            if kind == "click_option":
                _apply_typeahead_answer(
                    session,
                    f["id"],
                    str(ans.get("answer_typed") or answer_value),
                    ans.get("preferred_option_substring"),
                )
            else:
                _apply_text_answer(session, f["id"], str(answer_value))
        elif f["kind"] == "combobox":
            _apply_combobox_answer(session, f["id"], str(answer_value), ans.get("preferred_option_substring"))
        elif f["kind"] == "custom_combobox":
            # LinkedIn SDUI ARIA combobox (typeahead-style, not a native <select>)
            ok = _apply_custom_combobox_answer(
                session,
                f["id"],
                str(ans.get("answer_typed") or answer_value),
                ans.get("preferred_option_substring"),
            )
            if not ok:
                import sys as _sys
                print(f"  WARNING: custom_combobox fill returned False for label={label_clean!r} id={f.get('id')!r}", file=_sys.stderr)
        elif f["kind"] == "checkbox":
            desired = answer_value in (True, "true", "Yes", "yes", 1)
            _apply_checkbox_answer(session, f["id"], desired)
        answers[label_clean] = answer_value

    # Final sweep: fill any required fields that were missed or appeared
    # dynamically after earlier fills (e.g. conditional fields revealed by
    # radio selection). This prevents the form from stalling on Continue.
    sweep = _fill_required_fallback(session)
    if sweep.get("filled"):
        import sys as _sys
        print(f"  required-field fallback filled {len(sweep['filled'])} field(s): {sweep['filled']}", file=_sys.stderr)

    return ("ok", answers)


# ---------------------------------------------------------------------------
# top-level walk()
# ---------------------------------------------------------------------------

def _capture_draft_screenshot(session: str) -> str:
    """Take a screenshot of the current LinkedIn Apply modal and return the
    playwright-cli output.  Called before every escalation return so the user
    can see exactly which fields were already filled when they resume.

    IMPORTANT: this function intentionally does NOT click the Discard button.
    LinkedIn stores the partially-filled form as a draft that persists until
    the user explicitly discards it.  Leaving the modal open (or simply
    navigating away without clicking Discard) means the draft is preserved and
    the user can resume from exactly the point where automation stopped.
    """
    try:
        return p.screenshot(session)
    except Exception:
        return ""


def walk(role_context: dict, cv_pdf: Path, session_name: str) -> dict:
    role_url = role_context.get("url") or ""
    country = role_context.get("country") or "Unknown"

    def _linkedin_debug(page: str | None = None) -> dict:
        state = _dialog_state(session_name) or {}
        return {
            "state": state,
            "page": page or state.get("page"),
            "buttons": state.get("buttons", []),
        }

    if not _open_modal(session_name, role_url):
        if _is_no_longer_accepting(session_name):
            return {"status": "expired",
                    "reason": "linkedin-no-longer-accepting-applications",
                    "role_url": role_url,
                    "payload": _linkedin_debug()}
        return {"status": "failed", "reason": "modal-did-not-open",
                "role_url": role_url, "payload": _linkedin_debug()}

    answers: dict = {}
    visited_pages: list[str] = []

    for step in range(MAX_PAGES):
        if not p.is_dialog_open(session_name):
            return {"status": "failed",
                    "reason": "modal_closed_unexpectedly",
                    "step": step, "visited": visited_pages,
                    "payload": _linkedin_debug()}

        state = _dialog_state(session_name) or {}
        page = state.get("page", "unknown")
        visited_pages.append(page)

        if page == "review":
            # capture screenshot of review then submit
            p.screenshot(session_name)
            ref = _find_button_ref_scrolled(
                session_name,
                (
                    "Submit application",
                    "Soumettre",
                    "Envoyer ma candidature",
                    "Bewerbung absenden",
                    "Enviar solicitud",
                ),
            )
            if not ref:
                return {"status": "failed", "reason": "no-submit-button",
                        "visited": visited_pages, "payload": _linkedin_debug(page)}
            p.click(session_name, ref)
            time.sleep(5)
            confirmed = p.pcli_eval(
                session_name,
                "(() => /Application sent|Your application was sent|Application submitted|Candidature envoy[ée]e|Votre candidature a [ée]t[ée] envoy[ée]e|Bewerbung gesendet|Solicitud enviada/i.test(document.body.innerText))()",
            )
            if not confirmed:
                return {"status": "failed", "reason": "submission-unverified",
                        "visited": visited_pages, "payload": _linkedin_debug(page)}
            p.screenshot(session_name)
            return {
                "status": "applied",
                "submitted_via": "LinkedIn Apply",
                "confirmation": "Application sent or submitted",
                "screening": answers,
                "visited": visited_pages,
            }

        if page == "contact":
            ok, reason = _handle_contact(session_name)
        elif page == "resume":
            ok, reason = _handle_resume(session_name, cv_pdf)
        elif page == "top_choice":
            ok, reason = _handle_top_choice(session_name)
        elif page in ("work_experience", "education"):
            # Both pages are pre-filled from the candidate's LinkedIn profile.
            # Anything missing from the profile we can't synthesise here, so
            # just click Continue to advance — LinkedIn lets the candidate
            # submit even if these are partially populated.
            ok, reason = _handle_top_choice(session_name)
        elif page in ("additional", "work_authorization"):
            # Detect if we are stuck on the same page type from the previous
            # step — this means a required field was not filled and the "Next"
            # click did not advance the form.  Escalate early rather than
            # exhausting MAX_PAGES and returning a misleading max-pages-exceeded.
            if visited_pages.count(page) > 1:
                # Gather unfilled required fields via DOM for the escalation payload
                stuck_fields = p.pcli_eval(
                    session_name,
                    """(() => {
                      const dlg = document.querySelector('dialog[aria-label*="Apply to"], [role="dialog"]');
                      if (!dlg) return JSON.stringify([]);
                      const out = [];
                      dlg.querySelectorAll('[required], [aria-required="true"]').forEach(el => {
                        if (el.type === 'hidden' || el.disabled) return;
                        const val = (el.value || '').trim();
                        if (!val) {
                          const label = (
                            el.getAttribute('aria-label') ||
                            el.placeholder || el.name || el.id || ''
                          ).slice(0, 80);
                          out.push({tag: el.tagName, type: el.type || '', label});
                        }
                      });
                      return JSON.stringify(out.slice(0, 15));
                    })()""",
                )
                # Capture a screenshot of the current modal state so the user
                # can see which fields are filled and which are stuck.
                # Discard is intentionally NOT clicked — the LinkedIn draft
                # persists and the user can resume from this exact point.
                _capture_draft_screenshot(session_name)
                return {
                    "status": "escalate",
                    "reason": "additional-page-not-advancing",
                    "payload": {
                        "stuck_fields": stuck_fields if isinstance(stuck_fields, list) else [],
                        "answers_filled_so_far": answers,
                        "draft_preserved": True,
                        "note": "LinkedIn Apply additional-questions page did not "
                                "advance after filling. One or more required fields "
                                "(checkbox, dropdown, or text) were not filled. "
                                "Edge-case agent must complete them. "
                                "The LinkedIn draft has been preserved (Discard was "
                                "NOT clicked) — navigate to the job URL to resume.",
                    },
                    "visited": visited_pages,
                }

            verdict, payload = _handle_additional(session_name, country, role_context)
            if verdict == "escalate":
                # Capture draft state screenshot before escalating.
                # Discard is intentionally NOT clicked — the LinkedIn draft
                # persists so the user can resume from the current modal state.
                _capture_draft_screenshot(session_name)
                esc_payload = dict(payload) if isinstance(payload, dict) else {"raw": payload}
                esc_payload.setdefault("answers_filled_so_far", answers)
                esc_payload.setdefault("draft_preserved", True)
                esc_payload.setdefault(
                    "resume_note",
                    "LinkedIn draft preserved (Discard NOT clicked). "
                    "Navigate to the job URL to resume the partially-filled form.",
                )
                return {"status": "escalate",
                        "reason": esc_payload.get("reason") if isinstance(esc_payload, dict) else page,
                        "payload": esc_payload,
                        "visited": visited_pages}
            answers.update(payload if isinstance(payload, dict) else {})
            ref = _find_next_step_ref(session_name)
            if not ref:
                return {"status": "failed", "reason": "no-review-button",
                        "visited": visited_pages, "payload": _linkedin_debug(page)}
            p.click(session_name, ref)
            time.sleep(3)
            ok, reason = "ok", ""
        else:
            # Unknown page — capture screenshot before escalating so the user
            # can see the modal state. Draft is preserved (no Discard click).
            _capture_draft_screenshot(session_name)
            return {"status": "escalate", "reason": "unknown-page",
                    "payload": {
                        "state": state,
                        "answers_filled_so_far": answers,
                        "draft_preserved": True,
                        "resume_note": "LinkedIn draft preserved (Discard NOT clicked). "
                                       "Navigate to the job URL to resume.",
                    },
                    "visited": visited_pages}

        if ok != "ok":
            return {"status": "failed", "reason": reason,
                    "page": page, "visited": visited_pages,
                    "payload": _linkedin_debug(page)}

    return {"status": "failed", "reason": "max-pages-exceeded",
            "visited": visited_pages, "payload": _linkedin_debug()}
