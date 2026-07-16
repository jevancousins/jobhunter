"""ATS-specific application walkers.

Each module exposes a single function:

    walk(role_context: dict, cv_pdf: Path, session_name: str) -> dict

`role_context` is the contents of `applications/<id>/role-context.json`
(includes id, title, company, location, country, url, apply_type, variant).

`cv_pdf` is the absolute path to the PDF to upload.

`session_name` is the playwright-cli session name (the orchestrator opens
the session before dispatching).

Return value is a JSON-serialisable dict with a `status` key:
- `applied`   — submission verified by ATS confirmation page/text
- `escalate`  — walker hit a novel form field, unknown ATS shape, or a
                low-confidence screening question; orchestrator should hand
                off to the edge-case sub-agent
- `failed`    — terminal error (CV missing, dialog closed, rate-limited)

For `applied`, also include:
    submitted_via:    canonical apply-channel string ("LinkedIn Apply",
                      "Greenhouse", etc.)
    confirmation:     the confirmation phrase observed on screen
    screening:        dict of question→answer pairs that were filled

For `escalate`, also include:
    reason:           short tag (e.g. "long_form_question", "unknown_field")
    payload:          dict the edge-case sub-agent needs (snapshot, label, etc.)
"""
