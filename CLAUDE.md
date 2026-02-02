# JobHunter AI - Claude Context

## Project Overview

Personal job search automation platform using Notion as the database/UI and Claude API for AI-powered scoring and generation.

See `JobHunter PRD.md` for full requirements and `README.md` for setup instructions.

## Key Data Files

- `data/master_cv.json` - Complete CV data used for tailoring
- `data/job_goals.json` - Career goals and preferences for job scoring
- `data/learning_gaps.md` - Skills to develop (updated during CV optimisation)

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
