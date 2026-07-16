# Contributing to JobHunter

Thanks for considering a contribution. This project automates a personal job search with a Python harness driven from Claude Code, so contributions divide into two kinds: code (scripts, walkers) and prompt assets (skills, agents).

## Ground rules

- **Never commit personal data.** All personal files are gitignored (`data/*.json` real files, `cv/variants/`, `cv/sections/header.tex` and friends). If you add a new data file, add a gitignore entry and a tracked `.example` sibling in the same change. Pull requests containing real names, emails, employers, salary figures or Notion IDs will be closed.
- **Config over code.** User-specific behaviour (locations, filters, right-to-work rules, autonomy) belongs in `data/search_config.json` keys, documented in `data/search_config.example.json`, never in Python literals or skill prose.
- **British English, no em-dashes** in documentation and skill text.

## Adding an ATS walker

Walkers live in `scripts/walkers/`, one module per ATS, implementing:

```python
def walk(role_context: dict, cv_pdf: str, session_name: str) -> dict
```

Design philosophy: fill what is deterministic, escalate everything novel. A thin walker that fills the standard fields and escalates the rest to the edge-case agent is better than a clever walker that guesses. Look at `ashby.py` (thin) and `greenhouse.py` (fuller, with email verification handoff) as reference points, and use the helpers in `_pcli.py`. Screening answers must come from `answer_screening.py` (profile-driven), never from hardcoded assumptions about the candidate.

## Changing skills or agents

Skill and agent markdown under `.claude/` is part of the product. Keep the depersonalised style: skills read the candidate's facts from `data/master_cv.json` and friends at runtime and must work for any user with valid data files. If you find a claim about a specific person baked into a skill, that is a bug; please report or fix it.

## Testing

- `python3 -m py_compile scripts/*.py scripts/walkers/*.py` must pass.
- For walker changes, include a note on which live board you tested against and at what autonomy level.
- For discovery/filter changes, run `/auto-apply --discover --max-roles 3` at `search` autonomy and check the Notion rows look sane.

## A note on platform terms of service

Automated interaction with job platforms may breach their terms of service. Features should default to the least automated behaviour that achieves the goal, respect the configured autonomy level, and never attempt to bypass CAPTCHAs or bot detection (`captcha_preflight.py` deliberately backs off; keep it that way).
