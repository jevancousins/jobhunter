---
name: onboard
description: Guided first-run setup for JobHunter. Use when a new user says "set me up", "onboard me", "get started", "configure jobhunter", or when any pipeline command fails because data/search_config.json, data/master_cv.json or data/application_profile.json is missing. Interviews the user, generates their personal data files, sets up Notion, builds their first CV variant, and selects an autonomy level.
---

# JobHunter Onboarding

Take a new user from a fresh clone to a working, personalised pipeline. Everything personal is written to gitignored files in `data/` and `cv/`; nothing about the user ever goes into git.

Onboarding is a conversation, not a form. Ask questions in small batches, confirm what you inferred, and write files as each phase completes so progress survives an interrupted session. If a file already exists, offer to update rather than overwrite.

## Outputs

| File | Purpose |
|---|---|
| `data/master_cv.json` | Single source of truth for CV content and facts |
| `data/job_goals.json` | Career goals, preferences, scoring weights |
| `data/application_profile.json` | Identity and screening answers (chmod 600) |
| `data/search_config.json` | Search targets, filters, autonomy level |
| `cv/sections/header.tex` | Name and contact links for the LaTeX CV |
| `cv/variants/*.tex` + `variants.json` + `seniority_caps.json` | The user's CV variants and selection rules |
| `.env` | Notion credentials |
| `data/notion_ids.json` | Notion database IDs discovered during setup |

Schema truth for every JSON file is its `.example.json` sibling in `data/`. Read the example before writing the real file and match its shape exactly.

## Phase 0: Preflight

Check and report, but do not block on optional items:

```bash
python3 --version                          # required
pip install -r requirements.txt            # required
npx playwright-cli --version 2>/dev/null   # required for search and applying
pdflatex --version 2>/dev/null             # optional: LaTeX CV tailoring
```

If `pdflatex` is missing, note that the user can still run in "bring your own PDF" mode (see Phase 5) and install TeX later (MacTeX on macOS, TeX Live elsewhere).

Ask one framing question up front: "Roughly how much do you want to automate?" and hold the answer until Phase 6; it shapes how deep the earlier phases need to go.

## Phase 1: Who you are (master_cv.json)

1. Ask for an existing CV: a PDF or Word file path, or a LinkedIn profile export. Read it and draft `data/master_cv.json` following `data/master_cv.example.json` exactly: keyed `experience` entries, `education` with `modules` and `modules_by_year`, `languages` with honest proficiency levels, `skills`, `projects`, `certifications`, `awards`, `interests`.
2. Interview to fill what a CV never states:
   - Language proficiency levels (be precise: the system will refuse to let applications claim beyond this file).
   - `title_variants` per employer: alternative honest framings of each job title the user is comfortable with (e.g. an internal title of "Analyst II" might fairly be framed as "Data Analyst"). These are the only titles tailoring may use.
   - Exact employment dates and total years of experience.
   - 7 to 9 achievement bullets for the primary role, with real numbers where possible.
3. Read the finished draft back to the user section by section and get explicit confirmation. Factual accuracy here is the foundation of the whole system: downstream skills treat this file as the only permitted source of claims.

## Phase 2: What you want (job_goals.json)

Interview for: target roles and industries, a 5-year direction, location preferences with scores, compensation floor and flexibility, dealbreakers (industries, red-flag signals), skills to develop. Write `data/job_goals.json` matching the example schema, including `target_role_philosophy` and `scoring_weights` (keep the default weights unless the user has strong views; they must sum to 100).

## Phase 3: Where and how to search (search_config.json)

This file drives the pipeline. Work through it top to bottom using `data/search_config.example.json`:

1. **Candidate summary**: write a 2-3 sentence honest bio (name, years, current role, standout skills, notable gaps). Used by the realism filter to reject roles the user cannot credibly get, so honesty beats flattery.
2. **Right-to-work model**: which countries can the user work in without sponsorship (`home_countries`), what phrases identify their status on work-authorisation radio buttons (`right_to_work_labels`), and where they would need sponsorship (`needs_sponsorship_in`). Handle nuance explicitly, for example:
   - A candidate needing sponsorship in the target country should keep those roles rather than skip them; only a form with a hard gate and no sponsorship path is a skip. Encode the target country in `needs_sponsorship_in` and let the JD-level checks do the work.
   - Special schemes (such as France's V.I.E. for EU citizens abroad, or intra-company transfer visas) are search targets, not filters: add them as query phrases in `search.queries`.
3. **Locations**: for each target city or country, find the LinkedIn geo ID: run a LinkedIn Jobs search for that location in a browser and copy the `geoId=` parameter from the URL. Record `linkedin_geo_id`, `label`, `country`.
4. **Queries**: 3 to 7 named search phrases covering the user's angles. Include language or scheme-specific angles where relevant (e.g. "french speaking", "V.I.E.", "bilingual"). Set `default_queries` and `default_locations`.
5. **Filters**: title blacklist (seniority levels and role types to never consider), optional whitelist, industry dealbreakers, company blacklist (always include the current employer), contract types to skip, and the accepted-languages list.
6. **Where roles get discovered**: LinkedIn search is the built-in discovery source. If the user wants specific job boards or ATS-hosted boards (Ashby, Greenhouse, Lever company pages, Welcome to the Jungle, Otta and similar), set up a company/board watchlist: collect the board URLs into `search.watchlist_urls` (optional key) and note that `/auto-apply <url>` handles any single posting ad hoc regardless of source. Applying already works across LinkedIn, Greenhouse, Workday, Lever, Ashby, SmartRecruiters, BambooHR, Teamtailor, Jobvite and WTTJ.

## Phase 4: Screening answers (application_profile.json)

Build `data/application_profile.json` from the example: identity and contact details, work authorisation per target country, notice period and availability, compensation expectations per currency, demographics (default every field to "Prefer not to say" and tell the user they can change any of them), and a starter `verified_form_answers` block (years-of-experience style questions for their top skills). Then:

```bash
chmod 600 data/application_profile.json
```

Explain that `verified_form_answers` grows over time: whenever the pipeline answers a novel screening question and the user confirms it, it gets stored and reused.

## Phase 5: CV build

Two modes; ask which:

**LaTeX mode (recommended, enables tailoring):**
1. Create `cv/sections/header.tex` from `cv/sections/header.example.tex` with the user's details.
2. Generate 1 to 3 variants into `cv/variants/` using `cv/templates/general.tex` as the structural base, populated from `master_cv.json`. Name variants after target role families (e.g. `bizops-strategy.tex`, `general.tex`).
3. Create `cv/variants/variants.json` (title-pattern to variant rules; see `cv/templates/variants.example.json`) and `cv/variants/seniority_caps.json` (see `cv/templates/seniority_caps.example.json`). Set caps honestly: the cap is the maximum years of experience the user can credibly claim for that role family, and the filter uses it to skip roles that require more.
4. Build each variant and iterate to a full page:
   ```bash
   cd cv && make all
   python3 scripts/check_page_fill.py cv/output/<variant>.pdf
   ```

**Bring-your-own-PDF mode:** the user supplies a finished CV PDF; copy it to `cv/output/general.pdf` and set `cv.default_variant` to `general`. Tailoring is unavailable, so autonomy is capped at `search` plus manual applying with that fixed PDF; note this in the wrap-up.

## Phase 6: Autonomy level

Explain the three tiers and let the user choose; write to `search_config.json` `autonomy.level`:

- **search**: the pipeline finds, filters, scores and logs roles to Notion. The user reviews and applies personally. Zero risk, works for everyone; a good first week for every new user.
- **tailor**: search plus a tailored CV per role, left in the role folder with status `ReadyToApply`. The user submits.
- **full**: end-to-end, including form submission. Before enabling, make sure the user understands: automated applying may breach the terms of service of some platforms (notably LinkedIn); answers are drawn from their profile and low-confidence cases escalate to a sub-agent or to them; they are responsible for every application sent in their name. Recommend running at `tailor` for at least a few roles and inspecting the output first, then raising to `full`.

The level can be changed at any time by editing one line in `data/search_config.json`.

## Phase 7: Notion setup

Notion is the pipeline's database and review UI (free personal plan is fine).

1. User creates an integration at notion.so/my-integrations, and a parent page for JobHunter, then shares the page with the integration.
2. Create a **Jobs Database** under that page with exactly these properties (create it for them via the Notion MCP if connected, otherwise give click-by-click instructions):
   - `Name` (title), `Company` (text), `URL` (url), `Location` (select), `Source` (select), `Score` (number), `Salary` (text), `LinkedIn ID` (text), `Applied Date` (date), `Notes` (text)
   - `Status` (status type) with groups: To-do: `ToReview`, `Consider`, `Apply`, `NeedsTailoring`, `ReadyToApply`, `Escalated`, `Failed`; In progress: `AwaitingResponse`, `ResponseReceived`, `PhoneScreen`, `Test`, `CultureInterview`, `TechnicalInterview`, `FinalRound`, `Offer`; Complete: `Expired`, `NoResponse`, `Rejected`, `Skip`, `Accepted`
   - The Notion API cannot create status-type properties, so if creating programmatically, create everything else, then have the user add `Status` by hand from the list above.
3. Write `.env` from `.env.example` with `NOTION_API_KEY` and `NOTION_JOBS_DB_ID`.
4. Verify: `python3 scripts/notion_cli.py list --status ToReview` should return an empty list, not an error. Record any additional database IDs in `data/notion_ids.json`.

## Phase 8: LinkedIn auth

Needed for discovery at every autonomy level:

```bash
python3 scripts/save_linkedin_state.py
```

This opens a browser for an interactive login and stores cookies locally in `data/.linkedin-state.json` (gitignored). Re-run when LinkedIn forces re-authentication, typically every 2 to 3 months.

## Phase 9: Optional extras

Offer, do not push:

- **Deep experience pool** (`data/deep_experience.json`): a 20 to 30 minute interview capturing rich project narratives with metrics. Unlocks better cover letters, `/tailor-cv-full` and `/interview-prep`. Can be done later in instalments.
- **Email monitoring** (`/check-emails`): needs a Gmail MCP connection; records the tool prefix in the wrap-up notes.
- **Scheduled daily runs**: macOS launchd templates in `scripts/launchd/`; only sensible once the user trusts the pipeline at their chosen autonomy level.
- **Notifications**: `notifications.email` in `search_config.json` plus a Gmail app password.

## Phase 10: Test run and wrap-up

1. Run a deliberately small discovery: `/auto-apply --discover --max-roles 3`.
2. Review the results in Notion with the user: are the roles plausible? Tune `filters` and `queries` from what they see; this loop is how the config gets good.
3. Write a wrap-up note to `data/ONBOARDING_NOTES.md` (gitignored): chosen autonomy level, what was configured, what was deferred, and the exact commands for daily use.
4. Tell the user the three commands that matter day to day: `/auto-apply --discover`, `/auto-apply <job-url>`, `/check-emails`, and that every preference lives in `data/search_config.json`.

## Failure and resume behaviour

Each phase writes its file on completion, so re-running `/onboard` must detect existing files and offer: keep, update interactively, or regenerate. Never silently overwrite a file the user has edited by hand.
