---
name: apply-job
description: End-to-end application orchestrator. Chains review-job, tailor-cv, cover-letter, screening-question answering, and guided form submission for a single role. Use when the user says "apply to this job", "run the full pipeline on X", provides a job URL and asks to apply, or wants to process a Notion "To Review" job through to submission.
argument-hint: "[job-url OR notion-page-id]"
---

# Apply Job Skill

> **Tracker note:** wherever this skill reads or writes job state, use the configured backend (`tracker.backend` in `data/search_config.json`): Notion via the Notion MCP / `scripts/notion_cli.py`, or the local store via `scripts/local_tracker_cli.py`. State transitions should go through `scripts/auto_apply.py mark-*`, which dispatches automatically.


Orchestrates the full application pipeline for a single job: review → tailor CV → cover letter → pre-answer screening questions → drive ATS form → human approval gate → submit → Notion update.

## Usage

```
/apply-job https://www.linkedin.com/jobs/view/4391949750
/apply-job <notion-page-id>                              # Notion page id
/apply-job                                               # prompt for input
```

## Inputs
1. **LinkedIn / ATS URL**: fetch JD, create or update Notion record.
2. **Notion page id / URL**: fetch stored record, re-use its URL for the JD.
3. **No argument**: ask user which job.

---

## Operating Principles

- **Every submit goes through a human gate** during the validation period. Do NOT auto-submit until the user explicitly flips that rail.
- **Unknown screening question → pause, do not guess.** Use `scripts/answer_screening.py` for known patterns; for `needs_human=true` or confidence <0.7, consult `data/deep_experience.json` if the answer is derivable, otherwise ask the user.
- **Staging directory per job**: `applications/<notion-page-id>/` holds `job.json`, `<employer_filename_base> - <Company> <Title>.pdf` (where `employer_filename_base` comes from `data/search_config.json` `cv.employer_filename_base`), `cover-letter.md`, `cover-letter.pdf`, `screening-answers.json`, `submission-log.json`.
- **Idempotent**: re-running on the same job should not duplicate work — check the staging directory and Notion status first.

---

## Workflow

### Phase 0 — Resolve Job

- If argument is a URL, call Notion CLI to check for an existing record:
  ```
  python scripts/notion_cli.py list-by-status "To Review"
  ```
  Find matching URL. If not found, abort and ask user to add it via `/search-jobs` first (keeps the discovery path consistent).
- If argument is a Notion page id, fetch it:
  ```
  python scripts/notion_cli.py get-job <page-id-or-url>
  ```
- Extract: `title`, `company`, `location`, `url`, `status`, `description`. If the status is already "Applied", "Interview", "Offer", "Rejected" — stop and tell the user.
- Create `applications/<page-id>/` if missing. Write `job.json` with the resolved fields.

### Phase 1 — Review

Invoke the `/review-job` skill internally (follow its workflow inline, don't spawn it as a subagent). Output the verdict + score + breakdown.

**Gate:** if verdict is SKIP or hard-gate triggered → update Notion status to "Pass", write reasoning to Notes, stop. Do not proceed.

If CONSIDER → ask user whether to continue (cost of tailoring ~10 min).
If APPLY → continue automatically.

### Phase 2 — Tailor CV

Invoke the `/tailor-cv` workflow inline. Output PDF to `cv/output/tailored/` as usual, then COPY to `applications/<page-id>/<employer_filename_base> - <Company> <Title>.pdf` (employer-facing filename, with `employer_filename_base` read from `data/search_config.json` `cv.employer_filename_base`; never use bare `cv.pdf`).

### Phase 3 — Open the Application Form and Inspect Fields

Open the application form in Chrome MCP BEFORE generating a cover letter or pre-answering screening questions. For LinkedIn Apply you'll need to walk through every modal step (Next → Next → …) to see the full set of fields, since LinkedIn paginates the form. For external ATS (Greenhouse, Workday, etc.) the fields are usually on one or two pages.

Routing by ATS:

| Host domain | Driver |
|---|---|
| linkedin.com/jobs | Chrome MCP → LinkedIn Apply flow (see `data/linkedin-apply-learnings.md`) |
| greenhouse.io, boards.greenhouse.io | Chrome MCP → standard Greenhouse form |
| workday.com, *.myworkdayjobs.com | Chrome MCP → Workday form |
| lever.co, jobs.lever.co | Chrome MCP → Lever form |
| ashbyhq.com | Chrome MCP → Ashby form |
| other | Log "unsupported ATS" in Notion notes, hand off to user with staging artefacts ready |

Walk the form end-to-end in read-only mode (filling fields you already know, like identity + CV upload, is fine). Record the full field inventory in `applications/<page-id>/form-inventory.json`:

```json
{
  "ats": "linkedin_linkedin_apply",
  "has_cover_letter_field": false,
  "cover_letter_required": false,
  "screening_questions": [
    {"id": "q1", "question": "How many years of Python?", "type": "number", "required": true},
    {"id": "q2", "question": "Do you require sponsorship?", "type": "yes_no", "required": true}
  ],
  "other_fields": ["email", "phone_country_code", "phone_number", "cv_upload"]
}
```

### Phase 4 — Cover Letter (conditional)

**Rule: only generate a cover letter if the form has a cover letter input field** (file upload OR large textarea labelled "cover letter", "message to hiring team", "why this role", or similar).

- If `form-inventory.json.has_cover_letter_field == false` → skip this phase entirely. Do not waste time generating a letter. Log "No cover letter field detected — skipping cover letter generation." in Notes.
- If `has_cover_letter_field == true` → invoke the `/cover-letter` workflow inline (whether the field is required or optional; default to including when the form offers it). Output markdown to `applications/<page-id>/cover-letter.md`.

For PDF upload targets (run from the repo root):
```bash
pandoc applications/<page-id>/cover-letter.md -o applications/<page-id>/cover-letter.pdf --pdf-engine=xelatex
```

If `pandoc`/`xelatex` missing, skip PDF compilation and log a note — markdown paste still works for textarea fields.

### Phase 5 — Pre-answer the Screening Questions Discovered in Phase 3

For each question captured in `form-inventory.json.screening_questions`, call:

```bash
python scripts/answer_screening.py batch applications/<page-id>/form-inventory-questions.json --country "<job-country>"
```

(Or `ask` for one-offs.)

Save the result to `applications/<page-id>/screening-answers.json`. For any `needs_human: true` or `confidence < 0.7`:
1. Read `data/deep_experience.json` and try to derive an answer.
2. If still uncertain, add it to a "pending human review" list and ask the user.

### Phase 6 — Fill the Form

Now that we have tailored CV, conditional cover letter, and screening answers, drive the ATS:

**General form-fill procedure (any ATS):**
1. Re-open the form (the Phase 3 session may have timed out).
2. For each field from `form-inventory.json`, fill:
   - Identity fields → `application_profile.json` `identity` block.
   - Authorisation/sponsorship → `screening-answers.json`.
   - Years experience → `screening-answers.json`.
   - CV upload → the employer-named PDF in `applications/<page-id>/` (`<employer_filename_base> - <Company> <Title>.pdf`). Resolve using glob `<employer_filename_base>*.pdf`; never hardcode `cv.pdf`.
   - Cover letter upload/textarea → `applications/<page-id>/cover-letter.pdf` (or markdown) — only present if Phase 4 generated one.
   - Other screening questions → `screening-answers.json`.
3. Fill fields one by one. After each, verify via `read_page` or screenshot that the field accepted the value.
4. Walk through every modal page (LinkedIn) or scroll to the bottom (single-page ATS). Stop at the final "Submit application" step. Do NOT click Submit yet.

**File upload procedure (critical — browsers block `form_input` on `<input type="file">` for security). This flow is macOS-specific: it drives the native macOS Finder file dialog via computer-use. On other platforms, ask the user to select the file manually or use a Playwright-based upload instead.**

Do NOT try to set file inputs with the Chrome MCP `form_input` tool — it will error with "may only be programmatically set to the empty string". Instead:

1. Ensure the native-app grant is in place:
   ```
   mcp__computer-use__request_access with apps=["Finder", "Google Chrome"], reason="File upload for job application"
   ```
   (If access is already granted this is a no-op.)
2. Click the "Upload resume" / "Choose file" / "Attach" button via Chrome MCP to trigger the native macOS file dialog.
3. Wait ~1 sec for the dialog, then drive it via computer-use:
   - `mcp__computer-use__key` with `text="cmd+shift+g"` to open "Go to folder"
   - `mcp__computer-use__type` the absolute path to the employer-named CV PDF (i.e. `<repo-root>/applications/<page-id>/<employer_filename_base> - <Company> <Title>.pdf` — resolve the repo root with `pwd` first, since the dialog needs an absolute path)
   - `mcp__computer-use__key` with `text="return"` to navigate + select the file in the dialog
   - `mcp__computer-use__key` with `text="return"` again to confirm the upload
4. Wait ~2 sec, then screenshot the Chrome tab to verify the new file shows selected in the form.
5. If any step fails (native dialog doesn't appear, filename doesn't update, etc.), fall back to asking the user to select the file manually — do not retry silently.

This procedure works for both CV and cover letter uploads.

### Phase 7 — Human Approval Gate

Print a summary to the user:
- Role, company, score
- CV path, cover letter path
- **Every answer that will be submitted**, field by field
- Any `needs_human` or low-confidence items flagged with "NEEDS YOUR CALL"
- A final "Ready to submit? (y/n)" prompt

Wait for explicit approval. If declined, save state and stop — user can resume or abandon.

### Phase 8 — Submit

On approval:
1. Take a screenshot of the filled form.
2. Click Submit.
3. Wait for confirmation page; screenshot it.
4. Write `applications/<page-id>/submission-log.json` with timestamp, ATS name, answers submitted, confirmation screenshot path.

### Phase 9 — Update Notion

```bash
python scripts/notion_cli.py update-status <page-id> "Applied"
python scripts/notion_cli.py set-artefacts <page-id> --cv <cv-url> --cover-letter <cover-letter-url>
python scripts/notion_cli.py append-notes <page-id> "Applied <date> via <ATS>. <one-line summary>."
```

If the CV/cover letter are only local files (not uploaded to Drive), leave the URL fields blank and note the local paths in Notes.

Report completion to the user with the time taken and a link to the job.

---

## Safety Rails

- **Rate limit (LinkedIn Apply)**: maximum `autonomy.max_daily_linkedin_applications` LinkedIn Apply submissions per day, read from `data/search_config.json`. LinkedIn is reported to cap LinkedIn Apply at 50/day even for Premium accounts, so set the config value with a buffer below that. Before starting a LinkedIn submission, count today's `submission-log.json` files where `submitted_via == "LinkedIn Apply"` and `submitted_at` is today. If the count is at or above the configured limit, stop and warn — use external ATS for the rest of the day.
- **Rate limit (external ATS)**: no hard limit from LinkedIn; each ATS has its own throttle. Default practical ceiling: 30/day combined across Greenhouse/Workday/Lever/Ashby to avoid looking spammy to recruiters who share a backend.
- **Duplicate guard**: if Notion status is already "Applied", abort.
- **Dealbreaker re-check**: if `/review-job` triggers any hard gate in Phase 1, never proceed to tailoring.
- **Unknown ATS**: if the host doesn't match a supported driver and the form's DOM is unreadable, stop at Phase 3 and hand off to the user with all artefacts ready.
- **Confirmation page check**: if no confirmation page loads after Submit, do NOT mark Notion "Applied" — update Notes with "Submission status unknown" and ask the user to verify.

---

## Artefacts Written Per Run

```
applications/<notion-page-id>/
├── job.json                    # Resolved fields from Notion
├── <employer_filename_base> - <Company> <Title>.pdf  # Employer-facing tailored CV
├── form-inventory.json         # Fields discovered by walking the form in Phase 3
├── cover-letter.md             # Markdown source (only if Phase 4 ran)
├── cover-letter.pdf            # Compiled PDF (only if Phase 4 ran and pandoc available)
├── screening-answers.json      # Answers to each screening question, with confidence
├── form-screenshot.png         # Filled form before submit
├── confirmation-screenshot.png # Post-submit page
└── submission-log.json         # Audit record: timestamp, ATS, answers submitted
```

## Time Budget

- Phase 0: <30 sec (Notion lookup)
- Phase 1: 3-5 min (review)
- Phase 2: ~10 min (CV tailor)
- Phase 3: 1-2 min (open form, inventory fields)
- Phase 4: 0 or ~5 min (cover letter — only if form has the field)
- Phase 5: <1 min (screening pre-answers)
- Phase 6: 2-5 min (form fill, ATS-dependent)
- Phase 7: human time
- Phase 8: <30 sec (submit + capture)
- Phase 9: <30 sec (Notion update)

**Target: 15-20 min Claude time + 1-2 min user review per application.**

---

## Failure Modes and Recovery

| Failure | Action |
|---|---|
| JD unreachable in Phase 0 | Ask user to paste JD; continue with pasted text. |
| Review says SKIP | Mark Notion "Pass", stop. |
| CV page-fill fails | Surface the page-fill verdict; ask user to approve or re-tailor. |
| Cover letter generation errors | Retry with shorter JD; if still fails, flag for manual. |
| Unknown screening question | Consult deep_experience.json; if still unknown, ask user. |
| ATS form DOM unreadable | Save all artefacts; hand off to user with a "manual submit needed" summary. |
| Submit click doesn't fire | Screenshot, report URL, ask user to click manually; still update Notion on confirmation. |
| Confirmation page not detected | Do NOT mark "Applied"; ask user to verify status. |
