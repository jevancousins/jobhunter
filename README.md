# JobHunter AI

Personal job-search automation: a Python harness driven from Claude Code, with Notion as the source of truth and a small set of focused sub-agents for the parts that genuinely need an LLM. Replaces the original "scrape → score → manually review → manually apply" workflow with a single end-to-end pipeline that takes you from "search LinkedIn" to "submitted application" in one command.

## Architecture (v2, May 2026)

```
Claude Code main session  (Opus 4.6, billed against Claude Max)
  │
  └─ /auto-apply skill  ── thin orchestrator
        │
        ├─ Bash: python scripts/auto_apply.py search ...
        │     deterministic: LinkedIn search, scroll, title-filter, JD-fetch,
        │     JD-aware filter, Notion dedup, dismiss SKIPs on LinkedIn,
        │     write APPLY rows to Notion as Status="NeedsTailoring"
        │     (zero LLM tokens)
        │
        ├─ Agent(role-tailorer)  per role  [Opus 4.6, isolated context]
        │     reads jd.txt + role-context.json,
        │     runs /tailor-cv-light, falls back to template PDF on failure,
        │     returns one summary line; sub-agent context dies after each role
        │
        ├─ Bash: python scripts/auto_apply.py apply --role <id>
        │     deterministic walker per ATS:
        │       LinkedIn Apply, Greenhouse, Workday, Lever, Ashby
        │     fills the form using application_profile.json + answer_screening.py,
        │     submits, captures confirmation, writes submission-log.json
        │
        ├─ Agent(edge-case-applicator)  on escalation  [Opus 4.6, isolated]
        │     handles unknown ATS hosts, novel form fields, required cover
        │     letters, low-confidence answers, salary research with WebSearch
        │
        └─ Bash: python scripts/auto_apply.py mark-applied / mark-escalated /
                 mark-failed / summary / session-close
```

**Two design principles:**

1. **Programmatic orchestrator over LLM orchestrator.** Almost every step in the daily run is deterministic (search-result extraction, regex/keyword filtering, form-walking, Notion bookkeeping). All of it is Python. The LLM is reserved for steps that genuinely need open-ended reasoning: CV tailoring, cover-letter generation, edge-case form-walking, salary research with no published band.

2. **Sub-agent isolation, not one big context.** Each role's tailoring runs in its own Claude Code sub-agent that returns a one-line summary. The main session never accumulates JD bodies, form snapshots, or DOM dumps. A 50-role run stays under a few-percent of the main context budget.

This is what makes the pipeline actually run end-to-end on Claude Max: the heavy parallel work happens in Python (free) or in fresh sub-agents (Max-billed, context-isolated), and the main session is just a thin coordinator.

## Notion as source of truth

The Jobs Database in Notion holds every role's full state. Status moves through a state machine and is the only persistent coordination point between phases — the orchestrator can crash mid-run and resume from Notion on the next invocation.

```
NeedsTailoring  ──►  ReadyToApply  ──►  AwaitingResponse  ──► [downstream]
                                  └──►  Escalated   (edge-case agent escalation)
                                  └──►  Failed      (terminal walker error)
```

Full status options (grouped, set in Notion as `type: "status"`):

- **to_do**: `ToReview`, `Consider`, `Apply`, `NeedsTailoring`, `ReadyToApply`, `Escalated`, `Failed`
- **in_progress**: `AwaitingResponse`, `ResponseReceived`, `PhoneScreen`, `Test`, `CultureInterview`, `TechnicalInterview`, `FinalRound`, `Offer`
- **complete**: `Expired`, `NoResponse`, `Rejected`, `Skip`, `Accepted`

Auto-apply only writes the five active states above. Downstream transitions (response received → interview stages → terminal) are owned by `/check-emails`, which scans Gmail for replies and updates Notion accordingly.

## Quick start

### 1. Install dependencies

```bash
pip install -r requirements.txt
npm install -g @playwright/cli@latest
```

### 2. Configure environment

```bash
cp .env.example .env
```

Required:
- `NOTION_API_KEY` — your Notion integration token, granted access to the Jobs Database
- `NOTION_JOBS_DB_ID` — the Jobs DB ID

The Anthropic API key is **not required** — the pipeline is designed to bill against your Claude Max subscription. All LLM calls happen inside Claude Code (main session and sub-agents); the Python orchestrator itself never makes an LLM call.

### 3. Capture LinkedIn auth (one-time)

```bash
python scripts/save_linkedin_state.py
```

This logs you in interactively and persists the cookies to `data/.linkedin-state.json`. Re-run when LinkedIn forces a re-auth (typically every 2-3 months).

### 4. Run the pipeline from a Claude Code session

```
/auto-apply --discover --max-roles 5 --location london --term solutions
```

Start small to validate the flow, then ramp:

```
/auto-apply --discover                 # default: 24h, paris+london, solutions/python/data
/auto-apply --discover --limit 50      # cap at 50 successful submissions
/auto-apply --discover --watchlist     # use the company watchlist URL pattern
/auto-apply <linkedin-url>             # ad-hoc single-role apply
```

## Repository structure

```
jobhunter/
├── scripts/
│   ├── auto_apply.py              # the Python orchestrator (search/filter/dispatch/apply/mark-*)
│   ├── walkers/                   # one module per ATS, pure Python
│   │   ├── linkedin_apply.py      # verified
│   │   ├── greenhouse.py          # planned (currently escalates to edge-case agent)
│   │   ├── workday.py             # planned
│   │   ├── lever.py               # planned
│   │   └── ashby.py               # planned
│   ├── quick_filter.py            # deterministic title + JD filter (no LLM)
│   ├── select_variant.py          # title → CV variant matcher
│   ├── answer_screening.py        # screening-question lookup (verified_form_answers)
│   ├── salary_research.py         # JD-band positioning + sanity bounds
│   ├── notion_cli.py              # Notion read/write CLI
│   ├── save_linkedin_state.py     # one-time auth capture
│   └── ...                        # legacy scripts (daily_discover.py etc., deprecated)
│
├── .claude/
│   ├── agents/
│   │   ├── role-tailorer.md           # Opus 4.6 sub-agent: per-role CV tailoring
│   │   └── edge-case-applicator.md    # Opus 4.6 sub-agent: unknown ATS, novel fields,
│   │                                   #                    cover letters, salary research
│   └── skills/auto-apply/
│       ├── SKILL.md                   # the orchestrator wrapper (thin)
│       └── MIGRATION.md               # v1→v2 notes, file change log
│
├── data/
│   ├── master_cv.json                 # source content for tailoring
│   ├── deep_experience.json           # rich JD-driven evidence pool for /tailor-cv-full
│   ├── application_profile.json       # canonical screening answers (verified_form_answers
│   │                                  # block compounds over time)
│   ├── job_goals.json                 # candidate profile, dealbreakers, thresholds
│   ├── linkedin-apply-learnings.md    # walker DOM patterns (formerly easy-apply-learnings.md)
│   ├── .linkedin-state.json           # gitignored; persisted browser auth
│   ├── applications/<linkedin-id>/    # per-role folder: jd.txt, role-context.json,
│   │                                  # cv.pdf (or cv-template-fallback.pdf),
│   │                                  # submission-log.json, screenshots
│   └── auto-apply-runs/<date>/        # daily run summary artefacts
│
├── cv/
│   ├── variants/                      # 20 canonical CV variants (.tex)
│   ├── output/<variant>.pdf           # pre-built fallback PDFs
│   └── ...
│
└── src/                                # legacy module (notion client, scrapers, scoring)
                                        # used by daily_discover.py and notion_cli.py
```

## How costs work

Per 50-role run (rough):

| Phase | Tokens / cost |
|---|---|
| Search (deterministic Python) | £0 |
| Tailor (Opus 4.6 sub-agent × ~50) | £7-12 — dominant cost |
| Apply (deterministic Python for known ATS) | £0 |
| Apply edge cases (Opus sub-agent × ~5-10) | £1-3 |
| Orchestrator main session (summary lines only) | £0.40 |
| **Total** | **£8-15** per 50-role run |

All of this bills against the Claude Max subscription via the interactive Claude Code session. The Python orchestrator does no LLM calls of its own. If you ever need to run cron-scheduled (no Claude Code session), the LLM-needing phases would have to switch to API-billed Anthropic SDK calls — out of scope for v2.

## Other commands

| Command | Purpose |
|---|---|
| `/auto-apply --discover` | The daily run |
| `/auto-apply <url>` | Single ad-hoc role |
| `/check-emails` | Scan Gmail for application responses; update Notion accordingly |
| `/tailor-cv` | Manual high-touch tailoring for a hand-picked role |
| `/tailor-cv-light` | The lightweight tailor used inside the role-tailorer sub-agent |
| `/tailor-cv-full` | JD-driven full rewrite for top-priority roles |
| `/cover-letter` | Manual cover letter generation |
| `/interview-prep` | Tailored interview prep for an upcoming round |
| `/apply-job <url>` | Legacy single-role orchestrator with manual review gates (kept for high-touch applications) |

## Documentation

- [`.claude/skills/auto-apply/SKILL.md`](.claude/skills/auto-apply/SKILL.md) — the orchestrator wrapper (definitive runbook)
- [`.claude/skills/auto-apply/MIGRATION.md`](.claude/skills/auto-apply/MIGRATION.md) — v1→v2 design notes, file change log, rollback path
- [`.claude/agents/role-tailorer.md`](.claude/agents/role-tailorer.md) — CV tailoring sub-agent contract
- [`.claude/agents/edge-case-applicator.md`](.claude/agents/edge-case-applicator.md) — escalation sub-agent contract
- [`JobHunter PRD.md`](JobHunter%20PRD.md) — original product requirements (the v2 Architecture section at the top supersedes the rest where they differ)
