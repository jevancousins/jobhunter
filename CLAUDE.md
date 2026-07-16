# JobHunter AI - Claude Context

## Project Overview

Job search automation platform: a pluggable job tracker (Notion, or a local JSON store with a CSV view), a Python harness for the deterministic pipeline, and Claude Code sub-agents for the work that genuinely needs an LLM (CV tailoring, edge-case applications, answer review).

See `README.md` for setup instructions.

## Backends

Two layers are pluggable, set in `data/search_config.json`:

- `tracker.backend`: `local` (data/tracker.json + data/tracker.csv via `scripts/local_tracker_cli.py`) or `notion` (`scripts/notion_cli.py`). Both expose the identical CLI surface; `auto_apply.py` dispatches automatically. Always go through `auto_apply.py mark-*` for state transitions.
- `cv.backend`: `pdf` (fixed cv/master.pdf, no tailoring), `docx` (cv/master.docx, tailored copies per role), or `latex` (cv/variants system). Tailoring skills branch on this value.

When the user asks for a pipeline overview ("show me my pipeline") on the local backend, read data/tracker.json and render a table; suggest data/tracker.csv for spreadsheet review.

To add a company to the watchlist, append to `data/watchlist.json` (schema in `data/watchlist.example.json`). Never remove entries without being asked.

## Key Data Files

All personal data files are gitignored and have tracked `.example` templates. The `/onboard` skill creates the real files.

- `data/master_cv.json` - Canonical CV data: roles, employment dates, bullets, projects, skills, education, languages, and allowed title framings (`title_variants`)
- `data/job_goals.json` - Career goals and preferences used for job scoring
- `data/application_profile.json` - Identity, work authorisation, and verified screening-form answers
- `data/search_config.json` - Pipeline tuning: search queries and locations, filters, autonomy level, tracker and CV backends, CV filename base, sponsorship posture
- `data/watchlist.json` - Target-company watchlist with career-board URLs; built during onboarding, grown over time
- `data/tracker.json` / `data/tracker.csv` - The pipeline itself (local tracker backend only)
- `data/deep_experience.json` - Optional long-form project deep-dives, metrics, and learnings; richer than the CV bullets. Skills degrade gracefully when absent (as do `star_stories.json` and `technical_inventory.json`)

## Personal Data

The data files above must never be committed; the `.gitignore` enforces this. Before adding any new data file, check whether it contains personal information and add it to `.gitignore` if it does. Only `.example` templates belong in version control.

## Notion MCP Usage

### CRITICAL: Select Field Updates

When using the Notion MCP to update a Select or Multi-Select field's data source (e.g., adding a new company to the Company column), you **MUST include ALL existing values** in the update request.

**Why:** Notion's API replaces the entire options list when updating a Select field's data source. If you only include the new value, all existing options will be deleted.

**Correct approach:**
1. First fetch the current database schema to get all existing Select options
2. Include all existing options PLUS any new options in the update request

**Example:** Adding "NewCo" to a Company select field that already has "Anthropic", "Google", "Meta":
- ❌ Wrong: Update with just `["NewCo"]` → Deletes Anthropic, Google, Meta
- ✅ Correct: Update with `["Anthropic", "Google", "Meta", "NewCo"]`

**Workaround:** For frequently-changing fields like Company, consider using a Text field type instead of Select to avoid this issue entirely.

## CV System

See `cv/CLAUDE.md` for CV-specific instructions including:
- LaTeX compilation workflow
- Tailoring process
- Template structure
