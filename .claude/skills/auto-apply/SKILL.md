---
name: auto-apply
description: The single end-to-end daily job-application pipeline. Searches LinkedIn, filters with deterministic rules, tailors CVs via the role-tailorer sub-agent, applies through Python ATS walkers, and writes results to the tracker (Notion or the local data/tracker.json backend) as the source of truth. The orchestrator (this skill, running in the main Claude Code session) acts as a thin shell over `scripts/auto_apply.py` and dispatches sub-agents only for genuinely LLM-needing work (CV tailoring, edge cases). Use as the daily run via `/auto-apply --discover`, or for a single role via `/auto-apply <linkedin-url>`.
---

# Auto-apply (orchestrator skill)

This skill is the thin Claude Code shell over the Python orchestrator at `scripts/auto_apply.py`. It does the bookkeeping that has to happen inside an interactive Claude Code session (so LLM usage bills against your Claude subscription rather than metered API calls), and dispatches sub-agents for the two LLM-needing phases (CV tailoring + edge-case handling).

**Almost all the work is in Python.** This skill exists to (a) launch the Python orchestrator, (b) loop over its outputs, and (c) spawn sub-agents at the right moments. The skill itself contains no LinkedIn DOM logic, no form-walking code, no filter logic — that all lives in `scripts/auto_apply.py` and `scripts/walkers/`.

## Architecture (why the design looks the way it does)

```
Main Claude Code session  (subscription-billed)  ── this skill orchestrates
  │
  ├─ Bash: python scripts/auto_apply.py session-open
  │
  ├─ Bash: python scripts/auto_apply.py search ...
  │     → deterministic LinkedIn search, filter, dedup; writes Notion rows
  │       as Status="NeedsTailoring"; prints a compact JSON summary
  │     → ZERO LLM tokens; no JD/snapshot pollutes main context
  │
  ├─ Bash: python scripts/auto_apply.py list-queue --status NeedsTailoring
  │     → prints role IDs as JSON
  │
  ├─ PARALLEL BATCH (up to 10 at once — proven safe limit): for each role in NeedsTailoring:
  │     • Bash: python scripts/auto_apply.py prepare --role <id>
  │     • Agent(role-tailorer) → "OK <id> <pdf>" / "FALLBACK" / "ERROR"
  │     • Bash: python scripts/auto_apply.py mark-ready --role <id>
  │
  ├─ Bash: python scripts/auto_apply.py list-queue --status ReadyToApply
  │
  ├─ SERIAL walker loop — apply --role <id> one at a time (shared auto-apply session)
  │     collect all results before dispatching any edge-case agents
  │
  ├─ PARALLEL BATCH (up to 10 at once): for each escalated role:
  │     • Route by reason:
  │       - unknown-ats / ashby-* / workday-* / greenhouse-* → edge-case-applicator-HAIKU (~4× cheaper)
  │       - lever-* / cover-letter / essays / low-confidence  → edge-case-applicator-SONNET
  │       - needs_human / workday-account-creation            → mark-escalated directly (no agent)
  │     • Each agent owns an INDEPENDENT browser session (no collision)
  │     • Agents self-mark Notion; orchestrator reads only the status line
  │     • Exception: Greenhouse email-verify roles run SERIALLY so the main
  │       session can relay Gmail codes between each agent's session
  │
  ├─ Bash: python scripts/auto_apply.py summary
  └─ Bash: python scripts/auto_apply.py session-close
```

**Tracker state machine** (identical for both backends):

```
NeedsTailoring  ──► ReadyToApply  ──► AwaitingResponse
                                 └──► Escalated   (edge-case agent said HUMAN_REQUIRED)
                                 └──► Failed      (terminal walker error, no retry)

(After AwaitingResponse, the role progresses through ResponseReceived →
PhoneScreen / Test / CultureInterview / TechnicalInterview / FinalRound →
Offer → Accepted, OR a terminal Rejected / NoResponse / Expired. Those
later transitions are owned by /check-emails, not /auto-apply.)
```

The pipeline is **resumable from any point.** If the session crashes mid-run, the next `/auto-apply` invocation reads the tracker, picks up roles in `NeedsTailoring` or `ReadyToApply`, and continues. Idempotent throughout.

## Autonomy

At the start of every run, read `autonomy.level` from `data/search_config.json`. The level caps how far the pipeline goes:

| Level | Behaviour |
|---|---|
| `search` | Run the search phase only. Write scored roles to the tracker (status `ToReview` / `Apply`) and stop. The human reviews and applies. |
| `tailor` | Run search, then CV tailoring for accepted roles, then stop at `ReadyToApply`. The human submits the applications. |
| `full` | Run the entire pipeline end-to-end, including form submission. |

The Python side enforces this independently: `auto_apply.py apply` and `batch-apply` refuse to run when the configured level is below `full`. Do not attempt to bypass that check from the orchestrator; if the user asks for more autonomy, point them at `data/search_config.json`.

## Discover-mode flags

The orchestrator sizes the run from `--per-query` by default. Whatever the search phase produces is fully tailored and fully submitted in the same run, unless `--max-tailor` or `--max-apply` are passed to cap a specific phase. The user is responsible for picking values they're willing to see through end-to-end.

| Flag | Default | Effect |
|---|---|---|
| `--date` | `24h` | LinkedIn date filter: `24h`, `week`, `month`, `all` |
| `--location` | `search.default_locations` from `data/search_config.json` | Named location keys defined in `search.locations` in `data/search_config.json` (composable) |
| `--term` | `search.default_queries` from `data/search_config.json` | Named query keys defined in `search.queries` in `data/search_config.json`. Unknown values are passed through as literal natural-language phrases. Composable. |
| `--per-query` | `5` | Max APPLY rows accepted **per search URL**. Primary sizing knob — 3 queries × 2 locations = 6 URLs, so `--per-query 10` caps the run at ~60 roles. |
| `--max-tailor` | unset (uncapped) | Optional ceiling on roles handed to the CV-tailoring sub-agents this run. Excess sit in `NeedsTailoring` for the next run. The orchestrator enforces this by passing `--limit <n>` to `list-queue --status NeedsTailoring`. Omit to tailor everything. |
| `--max-apply` | unset (uncapped) | Optional ceiling on submissions this run. Excess sit in `ReadyToApply` for the next run. The orchestrator enforces this by passing `--limit <n>` to `list-queue --status ReadyToApply`. Omit to submit everything. |
| `--watchlist` | off | Use the watchlist company-IDs URL pattern instead of keyword search |
| `--dry-run` | off | Run search + filter only; do NOT tailor or apply |

### How the run is sized

A `/auto-apply` invocation does, in order:

1. **Search** up to `URL-count × --per-query` candidate roles. APPLY rows are written to the tracker. Watchlist matches → `NeedsTailoring`. Non-watchlist matches → fast-tracked to `ReadyToApply` with the variant template PDF (no per-role tailoring).
2. **Tailor** every `NeedsTailoring` row from this run via the role-tailorer sub-agent (or the first `--max-tailor` if specified).
3. **Submit** every `ReadyToApply` row via the form-walkers (or the first `--max-apply` if specified). Edge-case agent runs on escalation.

Cost note: each tailor sub-agent is a small Sonnet-class run; on a subscription plan it consumes usage allowance rather than billing per call. Use `--max-tailor` if you want a hard ceiling on the number of tailoring runs.

## Operating procedure (the orchestrator walkthrough)

### Step 0 — Pre-flight

1. Read `autonomy.level` from `data/search_config.json` (see the Autonomy section above). Note which phases this run is allowed to reach.
2. Verify `data/.linkedin-state.json` exists. If not, abort with: "Run `python scripts/save_linkedin_state.py` first."
3. Run `python scripts/auto_apply.py session-open`. The script opens the session, loads auth, navigates to feed, dismisses cookie banner, removes `#interop-outlet`. Aborts non-zero on auth failure.

### Step 1 — Search phase

```
python scripts/auto_apply.py search \
    --date <date> --location <loc> --term <term> --per-query <n>
```

`--per-query` controls per-URL fairness (default 5). Pass it through from the user's `/auto-apply` invocation. Do NOT pass `--max-roles` unless the user explicitly set it as a hard global ceiling.

The Python script writes APPLY rows to the tracker as `NeedsTailoring`, dismisses SKIP roles on LinkedIn, and prints a compact summary like:

```json
{"summary": {"scanned": 120, "title_skip": 24, "duplicate": 2,
             "jd_empty": 1, "jd_skip": 28, "apply": 47, "errors": 0},
 "apply_rows": [{"id": "...", "title": "...", "company": "...",
                 "apply_type": "...", "variant": "..."}, ...]}
```

**You (the orchestrator) print this summary verbatim** to the user, then proceed.

### Step 2 — Tailor phase

**Autonomy gate:** if `autonomy.level` is `search`, skip this step and Step 3, print the search summary, and end the run. The scored roles are in the tracker for human review (local backend: also print a compact table of the day's roles, since there is no Notion UI to open).

**CV backend gate:** if `cv.backend` in `data/search_config.json` is `pdf`, there is no tailoring; for each `NeedsTailoring` role run `prepare` then `mark-ready` directly (the master CV is the application CV) and continue to Step 3. The `docx` and `latex` backends both dispatch the role-tailorer sub-agent below; the agent adapts to the backend.

```
python scripts/auto_apply.py list-queue --status NeedsTailoring [--limit <max-tailor>]
```

If the user passed `--max-tailor`, append `--limit <n>`. Otherwise omit `--limit` and tailor every `NeedsTailoring` role from this run. Excess (when `--max-tailor` is set) stays in the queue for the next run.

For each role in the returned list:

1. `python scripts/auto_apply.py prepare --role <id>` (sets up folder + variant/master CV + fallback file; output includes `cv_backend`)
2. Spawn the `role-tailorer` sub-agent with prompt:

```
Tailor a CV for role <role-id>.

Inputs:
- role-folder: applications/<role-id>/ (repo-relative; the skill runs with the repo as cwd)
- variant: <variant-from-prepare-output>
- jd-path: <role-folder>/jd.txt
- role-context-path: <role-folder>/role-context.json
- fallback-pdf: <role-folder>/cv-template-fallback.pdf
- target-pdf: <tailored_pdf_target from prepare output>

Run /tailor-cv-light per the agent definition. Final output line must be
exactly one of: OK <id> <pdf> | FALLBACK <id> <pdf> <reason> | ERROR <id> <reason>.
```

3. Read the sub-agent's last line. On `OK` or `FALLBACK`, run `python scripts/auto_apply.py mark-ready --role <id>`. On `ERROR`, run `python scripts/auto_apply.py mark-failed --role <id> --reason <reason>`.

The orchestrator does NOT read JDs, snapshot CVs, edit documents, or compile LaTeX. All that happens inside the sub-agent's isolated context.

### Step 3 — Apply phase

**Autonomy gate:** if `autonomy.level` is `tailor`, skip this step; roles stay in `ReadyToApply` for the human to submit. Only `full` proceeds (and the Python side re-checks: `apply` / `batch-apply` refuse below `full`).

```
python scripts/auto_apply.py list-queue --status ReadyToApply [--limit <max-apply>]
```

If the user passed `--max-apply`, append `--limit <n>`. Otherwise omit `--limit`.

#### 3a — Walker pass (one Bash call via batch-apply)

```bash
python scripts/auto_apply.py batch-apply --status ReadyToApply [--limit <n>]
```

`batch-apply` runs all walkers serially (shared session), auto-marks applied/failed/expired inline, and writes an escalations JSON file. It prints **one summary line** — that is the only walker output the orchestrator reads. The results file path is printed in that line.

#### 3b — Edge-case agent pass (parallel batches of 10)

Each edge-case agent uses a session named `apply-<role-id>`, a completely independent browser process. Up to 10 agents run concurrently without collision.

**Agent routing — choose tier by escalation reason:**

Note: `batch-apply` now auto-skips escalations where `data/apply-intelligence.json` playbooks say `"action": "skip"` (e.g., `workday-account-creation-failed`, `needs_human`, `ashby-spam-flag-detected`, expired roles). These are marked as Failed directly in the walker pass and never appear in the escalation queue. The routing below only applies to escalations that survive the auto-skip filter.

Rules are checked top-to-bottom; first match wins. The video/essay payload checks are **ATS-agnostic** — apply to every escalation that carries a `payload["unfilled"]` (or equivalent) list, not just Ashby.

| Reason / payload pattern | Agent | Why |
|---|---|---|
| `needs_human`, `workday-account-creation-*` | None — mark-escalated directly | Not automatable (also auto-skipped by intelligence) |
| Payload field references a **video recording / video response** (any ATS) | None — mark-escalated directly | Not automatable; needs human |
| Payload has any **essay-style** field (any ATS): textarea, OR question >40 chars / contains `?` / starts with "Why"/"Tell us"/"Describe"/"What"/"How" | `edge-case-applicator` (Sonnet) | Requires nuanced writing |
| `lever-*`, `generate_cover_letter`, `long_form`, `compute_salary_per_role`, `low_confidence`, `radio_value_unmatched` | `edge-case-applicator` (Sonnet) | Requires essay writing or nuanced judgement |
| Everything else (`unknown-ats`, `ashby-*` mechanical-fields-only, `workday-*`, `greenhouse-*`, `modal_closed_unexpectedly`) | `edge-case-applicator-haiku` (Haiku) | Mechanical form-fill; ~4x cheaper |

Essay/video detection helpers (apply per-escalation on `payload["unfilled"]` for any ATS):

```python
def is_essay(label: str) -> bool:
    l = (label or "").strip().lower()
    if len(l) > 40 or "?" in l:
        return True
    return any(l.startswith(p) for p in ("why ", "tell us", "describe ", "what ", "how "))

def is_video(label: str) -> bool:
    l = (label or "").lower()
    return "video" in l or "record yourself" in l or "loom" in l
```

**Exception — Greenhouse roles:** run serially so the main session can relay the Gmail code between each submission.

**Batch loop:**

```
BATCH_SIZE = 10

skip = [e for e in escalate_queue if 'needs_human' in e['reason'] or 'workday-account-creation' in e['reason']]
gh   = [e for e in escalate_queue if 'greenhouse' in e['reason']]
sonnet_batch = [e for e in escalate_queue if e not in skip and e not in gh
                and any(r in e['reason'] for r in ['lever-', 'generate_cover_letter',
                        'long_form', 'compute_salary', 'low_confidence', 'radio_value'])]
haiku_batch  = [e for e in escalate_queue if e not in skip and e not in gh and e not in sonnet_batch]

# Mark non-automatable immediately (no agent needed)
for e in skip:
    mark-escalated --role e['id'] --reason e['reason']

# Parallel: haiku + sonnet roles together in one message
for batch in chunks(haiku_batch + sonnet_batch, BATCH_SIZE):
    # Send all in a single message — agents self-mark, return only status line
    results = [
        Agent(edge-case-applicator-haiku if e in haiku_batch else edge-case-applicator,
              prompt=brief(e))
        for e in batch
    ]
    # Agents already self-marked; orchestrator just reads status lines for the table

# Greenhouse: serial with Gmail relay
for e in gh:
    result = Agent(edge-case-applicator-haiku, prompt=brief(e, note="leave session open on email-verify"))
    if last_line == "HUMAN_REQUIRED <id> greenhouse-email-verification-pending":
        code = fetch_gmail_code()   # search_threads from:greenhouse newer_than:5m
        enter_code_via_playwright(e['id'], code)
        mark-applied
```

**Agent prompt template:**

```
Handle an auto-apply escalation for role <role-id>.

Inputs:
- role-folder: applications/<role-id>/ (repo-relative)
- role-context-path: applications/<role-id>/role-context.json
- cv-pdf: <cv-pdf-path>
- escalation-reason: <reason>
- escalation-payload: <payload JSON>

Drive the application end-to-end via a playwright-cli session UNIQUE to your
role (`apply-<role-id>`); start and stop your own session (unless instructed
to leave it open for email-verify relay). Final output line must be exactly:
APPLIED <id> <tag> | HUMAN_REQUIRED <id> <reason> | RETRY_LATER <id> <reason> | ERROR <id> <reason>.
```

Read each agent's last line:
- `APPLIED ...` → `mark-applied` with the channel tag as `--via`.
- `HUMAN_REQUIRED ...` or `RETRY_LATER ...` → `mark-escalated` with the reason.
- `ERROR ...` → `mark-failed` with the reason.

**On `failed`**: `python scripts/auto_apply.py mark-failed --role <id> --reason <reason>`.

### Step 4 — Summary + close

```
python scripts/auto_apply.py summary
python scripts/auto_apply.py session-close
```

Print the summary to the user.

### Step 5 — Post-run intelligence update

After the summary, regenerate the intelligence file so the next run benefits from today's data:

```
python scripts/retrospective.py --quick
```

This takes ~5 seconds (local data only; no Notion queries). It updates `data/apply-intelligence.json` with the latest escalation diagnostics and skip host lists. Print the delta summary it produces to the user.

The full Notion-aware retrospective can run weekly via a scheduled routine. The `--quick` mode here keeps the daily run fast while still updating skip hosts, escalation playbooks, and ATS success rates from local diagnostics data.

## Single-role mode (`/auto-apply <linkedin-url-or-page-id>`)

Skip Step 1. Resolve the role:
- If the URL is a LinkedIn job URL, ensure the role exists in the tracker (run a single-URL search if not), then begin from Step 2 for that one ID.
- If a tracker row ID is given (Notion page ID or local-... ID), look up its URL and proceed from Step 2.

## Failure modes and required behaviour

| Failure | Required action |
|---|---|
| `data/.linkedin-state.json` missing | Abort entire run; tell user to run `save_linkedin_state.py` |
| `session-open` reports auth expired | Abort; tell user to re-run `save_linkedin_state.py` |
| Search Bash returns non-zero | Surface the error; do not proceed |
| Role-tailorer returns `ERROR` | `mark-failed`; continue to next role |
| Walker apply returns `failed` with `linkedin-rate-limit` | Stop the entire run; print rate-limit message |
| Walker apply returns `failed` with `modal-did-not-open` | `mark-failed`; continue (LinkedIn likely changed selectors — flag in summary) |
| Edge-case sub-agent returns `RETRY_LATER` | `mark-escalated` with the reason; do NOT auto-retry in same run |
| Edge-case sub-agent returns `HUMAN_REQUIRED` | `mark-escalated` with the reason; user reviews via the tracker |
| Edge-case sub-agent times out / no recognisable last line | `mark-escalated` with `subagent-no-output`; continue |
| One agent in a parallel batch fails | Process remaining batch members normally; do not abort the batch |
| Greenhouse email-verify code expired between agent and main-session relay | Fetch the latest code from Gmail (there will be a newer one); enter it |

## What this skill MUST NOT do

- Do not parse JDs into the main session's context — call `auto_apply.py` and read only its summary.
- Do not call `playwright-cli` directly from the main session for form-walking — that belongs to walkers and sub-agents. The one exception is Greenhouse email-verify code relay: enter the security code into the sub-agent's still-open `apply-<id>` session using `playwright-cli -s=apply-<id> fill <ref> <char>`.
- Do not invoke `/tailor-cv-light` directly from the main session — only the role-tailorer sub-agent does.
- Do not read `applications/<id>/jd.txt` into the main session — never needed at orchestrator level.
- Do not write to the tracker directly (Notion MCP or editing data/tracker.json) — go through `auto_apply.py mark-*` so state transitions are validated and both backends stay consistent.

## What this skill MAY do

- Print compact progress to the user between phases ("Search done: 47 APPLY", "Tailored 12/47", "Submitted 8 / 47, 3 escalated").
- Show the final markdown summary table.
- Flag unusual things noticed across the run (e.g. "5 unknown ATS hosts hit, see HANDOFF.md").

## Files

| File | Purpose |
|---|---|
| `scripts/auto_apply.py` | The orchestrator. ALL deterministic work. |
| `scripts/walkers/linkedin_apply.py` | LinkedIn Apply form-walker (Python) |
| `scripts/walkers/greenhouse.py` | Greenhouse form-walker (core fields, custom dropdowns, voluntary self-ID; escalates on email-verification gate so the edge-case agent can fetch the code via Gmail MCP) |
| `scripts/walkers/workday.py` | Workday walker (best-effort; escalates on account-required and multi-page wizards) |
| `scripts/walkers/lever.py` | Lever form-walker (single-page; escalates on extra required fields) |
| `scripts/walkers/ashby.py` | Ashby form-walker (single-page; escalates on free-text questions or unknown fields) |
| `.claude/agents/role-tailorer.md` | CV-tailoring sub-agent definition |
| `.claude/agents/edge-case-applicator.md` | Edge-case sub-agent (Sonnet) — essays, Lever, cover letters |
| `.claude/agents/edge-case-applicator-haiku.md` | Edge-case sub-agent (Haiku) — mechanical form-fill only, ~4× cheaper |
| `data/.linkedin-state.json` | Persisted LinkedIn auth (gitignored) |
| `data/application_profile.json` | Canonical screening answers (read by `answer_screening.py`) |
| `applications/<id>/` | Per-role folder (jd.txt, role-context.json, `<employer_filename_base> - <Company> <Title>.pdf` where `employer_filename_base` comes from `data/search_config.json` `cv.employer_filename_base`, submission-log.json) |

## Tracker state machine reference

| Status | Meaning | Set by |
|---|---|---|
| `NeedsTailoring` | Search wrote the row; awaiting CV tailoring | `auto_apply.py search` |
| `ReadyToApply` | CV tailored (or fallback); awaiting form-walker | `auto_apply.py mark-ready` |
| `AwaitingResponse` | Submission verified by ATS confirmation; awaiting employer reply (replaces the old terminal `Applied`) | `auto_apply.py mark-applied` |
| `Escalated` | Edge-case agent said `HUMAN_REQUIRED` / `RETRY_LATER` | `auto_apply.py mark-escalated` |
| `Failed` | Terminal walker error or `ERROR` from a sub-agent | `auto_apply.py mark-failed` |

The full status set (Notion Status field or local tracker statuses, created during onboarding) has these grouped options:

- **to_do**: `ToReview`, `Consider`, `Apply`, `NeedsTailoring`, `ReadyToApply`, `Escalated`, `Failed`
- **in_progress**: `AwaitingResponse`, `ResponseReceived`, `PhoneScreen`, `Test`, `CultureInterview`, `TechnicalInterview`, `FinalRound`, `Offer`
- **complete**: `Expired`, `NoResponse`, `Rejected`, `Skip`, `Accepted`

Auto-apply only writes the five rows above; downstream transitions (response received → interview stages → terminal) are owned by `/check-emails` or manual review. In Notion the field is `type: "status"`; `scripts/notion_cli.py` and `scripts/local_tracker_cli.py` both validate against this set.

## Cost expectations (rough)

All LLM work runs inside the interactive Claude Code session and its sub-agents, so it consumes your subscription's usage allowance rather than metered API spend. Relative weight per 50-role run (assuming most roles are watchlist; non-watchlist roles fast-track with no per-role tailoring):

- Search phase: no LLM usage at all (pure Python).
- Tailor phase: one small Sonnet-class sub-agent per role — the dominant usage driver.
- Apply phase: no LLM usage for known ATS walkers; one Haiku- or Sonnet-class sub-agent per edge-case escalation.
- Orchestrator session: minimal (only compact summaries flow through the main context).

Sub-agent isolation means the main session never bloats, so a large run costs context only in proportion to its summary lines. If usage limits are a concern, `--per-query` and `--max-tailor` are the sizing knobs.
