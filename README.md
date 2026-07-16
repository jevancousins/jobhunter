# JobHunter

An open-source job-search automation system you run yourself: a Python harness driven from [Claude Code](https://claude.com/claude-code), with a job tracker you can review anywhere, and a small set of focused sub-agents for the parts that genuinely need an LLM. It takes a search from "what's out there?" to "submitted application" with as much or as little automation as you choose, using the tools you already have: no Notion account or LaTeX knowledge required.

Built and battle-tested across a real multi-month job search (hundreds of applications across LinkedIn, Greenhouse, Workday, Lever, Ashby and more), then genericised so anyone can adapt it to their own search.

## What it does

- **Discovers** roles daily from LinkedIn search (plus any career board or posting URL you feed it ad hoc) using your configured locations, query angles and recency window.
- **Filters deterministically** before any LLM sees a role: title and industry rules, seniority caps, language requirements, right-to-work logic, all from your config. Zero tokens spent on obvious mismatches.
- **Scores and logs** every surviving role to your tracker, the single source of truth, with a status state machine from `ToReview` through to `Offer`.
- **Tailors your CV** per role: honest, fact-checked against your own data. Works on a Word document copy or, for the strongest results, a LaTeX template iterated until the page is exactly full.
- **Applies**, if you let it: deterministic Python form-walkers for LinkedIn Apply, Greenhouse, Workday, Lever, Ashby, SmartRecruiters, BambooHR, Teamtailor, Jobvite and Welcome to the Jungle, with an LLM sub-agent picking up edge cases (novel forms, required cover letters, unknown ATSs).
- **Monitors responses**: a skill scans Gmail for rejections, interview invites and offers, and moves tracker statuses accordingly.

## Works with your tools

Everyone's setup differs, so the two most personal layers are pluggable, chosen during onboarding and switchable later in `data/search_config.json`:

| Layer | Options |
|---|---|
| **Tracker** | `local` (default, zero setup: the pipeline lives in `data/tracker.json`, with `data/tracker.csv` regenerated on every change so you can review it in Excel, Numbers or Google Sheets) or `notion` (a Notion Jobs Database, for people who already live in Notion) |
| **CV** | `pdf` (bring a finished PDF, used as-is; zero dependencies, no tailoring), `docx` (bring a Word/Google Docs export; the system tailors a copy per role), or `latex` (the full variant system with per-role tailoring and page-fill checks) |

The rich evidence files (`deep_experience.json`, `star_stories.json`, `technical_inventory.json`) are optional depth: cover letters and interview prep work from your CV data alone and get better as you add them.

## Choose your autonomy level

Set once during onboarding, change any time in `data/search_config.json`:

| Level | What the system does | What you do |
|---|---|---|
| `search` | Finds, filters, scores, logs to your tracker | Review and apply yourself |
| `tailor` | Search, plus a tailored CV per role | Submit each application |
| `full` | End-to-end, including form submission | Review escalations and results |

Most people should start at `search`, watch a week of results, tune their filters, then decide how much to delegate. The Python side enforces the level: application commands refuse to run below `full`.

## Requirements

- Python 3.10+ and Node (for `playwright-cli`)
- [Claude Code](https://claude.com/claude-code) with a subscription (a standard $20/month plan is enough; the pipeline is designed so the deterministic work costs nothing and LLM work runs in context-isolated sub-agents)
- Optional: a free Notion account (only for the Notion tracker backend)
- Optional: a LaTeX distribution (MacTeX / TeX Live), only for the latex CV backend

No Anthropic API key is required: all LLM calls happen inside your Claude Code session and bill against your subscription. The Python orchestrator itself never calls an LLM.

## Getting started

```bash
git clone <this repo> && cd jobhunter
pip install -r requirements.txt
claude        # open a Claude Code session in the repo
```

Then, inside Claude Code:

```
/onboard
```

Onboarding is a guided interview that builds your personal files (all gitignored, none of them ever committed): your CV data, goals, screening answers, search configuration, company watchlist, tracker and CV setup. It ends with a small test run. Budget 30 to 60 minutes for a thorough setup; see [docs/PERSONAS.md](docs/PERSONAS.md) for three worked example configurations.

## Day-to-day use

| Command | Purpose |
|---|---|
| `/auto-apply --discover` | The daily run at your autonomy level |
| `/auto-apply <job-url>` | Push a single posting (any board) through the pipeline |
| `/check-emails` | Scan Gmail for responses; update the tracker |
| `/tailor-cv` | High-touch manual tailoring for a hand-picked role |
| `/cover-letter` | Tailored cover letter |
| `/interview-prep` | Prep document for an upcoming round |
| `/drain-queue` | Work through the ReadyToApply backlog (at `full` autonomy) |

## Architecture

```
Claude Code main session
  │
  └─ /auto-apply skill ── thin orchestrator
        │
        ├─ Bash: python scripts/auto_apply.py search ...
        │     deterministic: LinkedIn search, title/JD filter, dedup,
        │     tracker rows written as Status="NeedsTailoring"  (zero LLM tokens)
        │
        ├─ Agent(role-tailorer)  per role  [isolated context]
        │     tailors the CV from data/master_cv.json, returns one line
        │
        ├─ Bash: python scripts/auto_apply.py apply --role <id>
        │     deterministic walker per ATS  (only at autonomy=full)
        │
        └─ Agent(edge-case-applicator)  on escalation  [isolated context]
              unknown ATS, novel fields, cover letters, salary research
```

Two design principles carried through everything:

1. **Programmatic over LLM orchestration.** Search extraction, filtering, form-walking and bookkeeping are plain Python. The LLM is reserved for open-ended reasoning: tailoring, cover letters, novel forms.
2. **Sub-agent isolation.** Each role's LLM work runs in a fresh sub-agent returning a one-line summary, so a 50-role run does not blow up the main session's context.

The tracker holds every role's state, so the pipeline can crash mid-run and resume from where it left off.

## Your data stays yours

Everything personal lives in gitignored files with tracked `.example` templates:

| File | Contents |
|---|---|
| `data/master_cv.json` | CV content, the single source of truth for factual claims |
| `data/job_goals.json` | Goals, preferences, scoring weights |
| `data/application_profile.json` | Identity and screening answers (keep chmod 600) |
| `data/search_config.json` | Search targets, filters, backends, autonomy |
| `data/watchlist.json` | Your target-company watchlist, grown over time |
| `data/tracker.json` + `data/tracker.csv` | Your pipeline (local tracker backend) |
| `data/deep_experience.json` | Rich experience narratives (optional, unlocks better output) |
| `cv/master.pdf` / `cv/master.docx` / `cv/variants/` | Your actual CV files (per backend) |

The system is deliberately strict about honesty: tailoring and screening answers may only claim what is present in your data files, and a fact-check pass runs before any CV ships.

## Repository structure

```
jobhunter/
├── scripts/
│   ├── auto_apply.py          # the Python orchestrator
│   ├── walkers/               # one module per ATS
│   ├── quick_filter.py        # deterministic title + JD filter
│   ├── answer_screening.py    # profile-driven screening answers
│   ├── select_variant.py      # job title → CV variant rules
│   ├── notion_cli.py          # tracker backend: Notion
│   ├── local_tracker_cli.py   # tracker backend: local JSON + CSV export
│   ├── check_page_fill.py     # CV page-fill validator (+ format/facts checkers)
│   └── launchd/               # scheduled-run templates (macOS)
├── .claude/
│   ├── skills/                # onboard, auto-apply, tailor-cv*, cover-letter,
│   │                          # interview-prep, check-emails, apply-job, drain-queue
│   └── agents/                # role-tailorer, edge-case-applicator(s), answer-reviewer
├── data/                      # your data (gitignored) + .example templates
├── cv/                        # LaTeX CV system: cv.cls, templates/, your variants/
└── docs/                      # personas and guides
```

## Disclaimers, please read

- **Platform terms.** Automated interaction with job platforms may breach their terms of service (LinkedIn in particular restricts automation). You choose your autonomy level and you carry that risk; the system never bypasses CAPTCHAs or bot detection, and backs off when it meets them.
- **Every application is sent in your name.** Review what the system produces, especially in your first weeks. The escalation paths exist so that uncertain answers reach a human; do not disable them.
- **Accuracy is enforced but starts with you.** Fill `master_cv.json` honestly during onboarding; everything downstream trusts it.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). The most valuable contributions are new or hardened ATS walkers and discovery sources. Never include personal data in a pull request.

## Licence

[MIT](LICENSE)
