# JobHunter: instructions for AI agents

This file is for any agentic AI coding assistant operating in this repository (OpenAI Codex CLI, and others that read AGENTS.md). Claude Code users get the same behaviour automatically through `.claude/` and `CLAUDE.md`.

## What this repository is

A job-search automation system: a deterministic Python harness (search, filter, track, apply) plus a set of markdown playbooks for the work that needs an LLM (onboarding, CV tailoring, cover letters, interview prep). The Python layer never calls an LLM itself, so it works identically whichever assistant drives it.

## Commands and playbooks

The playbooks live in `.claude/skills/` (the directory name is historical; the content is agent-neutral operating procedure). When the user asks for one of these, open the playbook and follow it faithfully:

| User says | Playbook |
|---|---|
| "onboard me", "set me up", "/onboard" | `.claude/skills/onboard/SKILL.md` |
| "run the daily search", "/auto-apply --discover" | `.claude/skills/auto-apply/SKILL.md` |
| "apply to <url>", "/auto-apply <url>" | `.claude/skills/auto-apply/SKILL.md` (single-role section) |
| "tailor my CV for <role>", "/tailor-cv" | `.claude/skills/tailor-cv/SKILL.md` (light variant: `tailor-cv-light`) |
| "write a cover letter", "/cover-letter" | `.claude/skills/cover-letter/SKILL.md` |
| "prep me for my interview", "/interview-prep" | `.claude/skills/interview-prep/SKILL.md` |
| "check my emails", "/check-emails" | `.claude/skills/check-emails/SKILL.md` (needs Gmail access; see below) |

Role-specific sub-agent definitions in `.claude/agents/` (role-tailorer, edge-case-applicator, answer-reviewer) describe self-contained jobs with strict output contracts; treat each as a procedure to execute when a playbook dispatches it.

## Adapting Claude Code constructs

The playbooks were written for Claude Code. When you lack its facilities, adapt as follows rather than failing:

- **"Spawn the <name> sub-agent" / Agent tool**: do the sub-agent's job yourself, inline and sequentially, following its definition in `.claude/agents/<name>.md` including the final status-line contract. Process fewer roles per run to compensate for the lost context isolation: pass `--max-roles 5` (or less) to discovery, and prefer several small runs over one big one.
- **"Invoke the <name> skill" / Skill tool**: open `.claude/skills/<name>/SKILL.md` and follow it.
- **MCP tools** (`mcp__...` names, Notion MCP, Gmail MCP): if you have no MCP support, use the CLI equivalents where they exist (`scripts/notion_cli.py`, `scripts/local_tracker_cli.py`, `scripts/fetch_greenhouse_code.py`); otherwise state that the step needs a Claude Code session and skip it gracefully. `/check-emails` is the main casualty: without Gmail access, the user updates statuses conversationally instead ("mark <company> as rejected").
- **playwright-cli sessions**: the Python scripts drive the browser themselves; you only need to run the commands the playbooks give you.

## Ground rules (identical for every agent)

- **Configuration first**: user settings live in `data/search_config.json` (tracker backend, CV backend, autonomy level, search targets, filters). If it is missing, run onboarding. Never hardcode personal values into code or playbooks.
- **Autonomy is a hard limit**: read `autonomy.level` before acting. `search` = discover and log only; `tailor` = also produce CVs, the human submits; `full` = end-to-end applying. The Python side enforces this too; never bypass it or advise the user to pass override flags casually.
- **State transitions go through `python scripts/auto_apply.py mark-*`**, never by editing `data/tracker.json` or Notion directly.
- **Factual honesty**: every claim in a CV, cover letter, or screening answer must trace to `data/master_cv.json`, `data/application_profile.json`, the optional evidence files, or the user's own words in the session. Never upgrade language proficiencies, years of experience, or scope numbers.
- **Never commit personal data.** Everything about the user lives in gitignored files (`data/*.json` real files, `cv/master.*`, `cv/variants/`, `applications/`). Before any commit, check `git status` shows no personal files.
- **British English, no em-dashes** in all documents produced for the user.

## Quick orientation

- `CLAUDE.md` and `cv/CLAUDE.md`: further operating context (agent-neutral despite the filename).
- `README.md`: architecture and user-facing docs. `docs/PERSONAS.md`: three worked example configurations. `docs/USING_WITH_CHATGPT.md`: setup guide for ChatGPT/Codex CLI users.
- Backends: `tracker.backend` = `local` (data/tracker.json + data/tracker.csv via `scripts/local_tracker_cli.py`) or `notion`; `cv.backend` = `pdf`, `docx`, or `latex`. Both CLIs expose identical commands; `auto_apply.py` dispatches automatically.
