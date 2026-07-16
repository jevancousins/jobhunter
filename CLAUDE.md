# JobHunter AI - Claude Context

## Project Overview

Job search automation platform: Notion as the database/UI, a Python harness for the deterministic pipeline, and Claude Code sub-agents for the work that genuinely needs an LLM (CV tailoring, edge-case applications, answer review).

See `README.md` for setup instructions.

## Key Data Files

All personal data files are gitignored and have tracked `.example` templates. The `/onboard` skill creates the real files.

- `data/master_cv.json` - Canonical CV data: roles, employment dates, bullets, projects, skills, education, languages, and allowed title framings (`title_variants`)
- `data/job_goals.json` - Career goals and preferences used for job scoring
- `data/application_profile.json` - Identity, work authorisation, and verified screening-form answers
- `data/search_config.json` - Pipeline tuning: search queries and locations, filters, autonomy level, CV filename base, sponsorship posture
- `data/deep_experience.json` - Long-form project deep-dives, metrics, and learnings; richer than the CV bullets

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
