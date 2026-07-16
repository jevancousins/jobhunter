---
name: drain-queue
description: Process one batch of ReadyToApply (or Escalated) roles end-to-end with minimal orchestrator context bloat. Runs the Python walker pass via batch-apply, then dispatches up to 10 edge-case agents in parallel. Agents self-mark Notion; only their single status lines return to the main session. Greenhouse email-verify roles are handled serially with inline Gmail code relay. Invoke as `/drain-queue` (ReadyToApply, limit 15) or `/drain-queue --status Escalated --limit 10`.
---

# drain-queue

One batch, end-to-end, minimal context. The only thing the main session sees is:
1. One `batch-apply` summary line from the walker pass.
2. Up to 10 single status lines from parallel edge-case agents.
3. A compact results table.

## Flags

| Flag | Default | Effect |
|---|---|---|
| `--status` | `ReadyToApply` | Which Notion queue to drain |
| `--limit` | `15` | How many roles to process this batch |
| `--output` | auto (`/tmp/batch-apply-*.json`) | Override the results file path |

## Procedure

### Step 0 — Pre-flight

Verify `data/.linkedin-state.json` exists; if not, abort. Open the session:

```bash
python scripts/auto_apply.py session-open
```

### Step 1 — Walker pass (one Bash call)

```bash
python scripts/auto_apply.py batch-apply \
    --status <status> --limit <limit>
```

This runs all walkers serially, auto-marks applied/failed/expired inline, and prints **one line**:

```
batch-apply: 15 roles | applied=2 escalated=10 failed=1 expired=2 | results=/tmp/batch-apply-20260507-120000.json
```

Print this line to the user. Then close the playwright session (walkers are done):

```bash
python scripts/auto_apply.py session-close
```

### Step 2 — Read and partition escalations (one Bash call, minimal output)

```bash
python -c "import json; d=json.load(open('<results-file>')); print(json.dumps(d['escalated']))"
```

Partition into five groups. **The video/essay payload check is ATS-agnostic** — apply it to every escalation that carries a `payload["unfilled"]` list, regardless of whether the reason starts with `ashby-`, `greenhouse-`, `lever-`, `workday-`, `unknown-ats`, etc.

- `skip_now` — `needs_human` or `workday-account-creation-*`, OR **any** escalation whose payload requests a **video recording / video response** (cannot be automated): mark-escalated immediately, no agent
- `gh_roles` — reason contains `greenhouse` AND no video/essay rule already matched: serial (email-verify relay needed)
- `sonnet_roles` — reason contains `lever` OR `generate_cover_letter` OR `long_form` OR `compute_salary` OR `low_confidence` OR `radio_value_unmatched` OR `additional-page-not-advancing` OR `unknown-page`, **OR any escalation whose payload has any essay-style field** (textarea, OR any textbox whose label is a question >40 chars / contains a question mark / starts with "Why"/"Tell us"/"Describe"/"What"/"How"): use `edge-case-applicator` (Sonnet)
- `haiku_roles` — everything else: use `edge-case-applicator-haiku`

**Routing table:** (rules are checked top-to-bottom; first match wins)

| Reason / payload pattern | Agent |
|---|---|
| `needs_human`, `workday-account-creation-*` | Skip (mark-escalated directly) |
| Payload contains a video-recording / video-response field (any ATS) | Skip (mark-escalated, reason `video-response-required`) |
| Payload contains an essay-style textarea / long question (any ATS) | Sonnet (`edge-case-applicator`) |
| `greenhouse-*` | Serial Greenhouse relay (Step 4) |
| `lever-*` | Sonnet (`edge-case-applicator`) |
| `generate_cover_letter`, `long_form`, `compute_salary_per_role`, `low_confidence`, `radio_value_unmatched` | Sonnet (`edge-case-applicator`) |
| `additional-page-not-advancing`, `unknown-page` | Sonnet (`edge-case-applicator`) — LinkedIn Apply, requires auth |
| `unknown-ats`, `ashby-*` (mechanical fields only), `workday-*`, `unknown_field`, `modal_closed_unexpectedly` | Haiku (`edge-case-applicator-haiku`) |

**Essay / video detection (apply to every escalation that has `payload["unfilled"]`):**

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

For every escalation:

1. Look at `payload.get("unfilled", [])` (a list of `[field_type, label]` pairs). Also inspect any other payload field that carries a question label (e.g. `payload["question"]`, `payload["fields"]`).
2. If **any** label matches `is_video` → put in `skip_now`.
3. Else if **any** label matches `is_essay` → put in `sonnet_roles`.
4. Else fall through to the reason-based routing above.

For `skip_now` entries: mark-escalated immediately without dispatching an agent:

```bash
python scripts/auto_apply.py mark-escalated --role <id> --reason <reason>
```

### Step 3 — Parallel agent dispatch (up to 10 at once)

Send ALL parallel agents in a **single message** so they run concurrently. Each agent self-marks Notion and returns only one status line. Dispatch haiku_roles and sonnet_roles together in the same message — they use different sub-agent types but can run simultaneously.

Agent prompt template (same for both tiers):

```
Handle an auto-apply escalation for role <id> (<title> @ <company>).

- role-folder: <repo-root>/data/applications/<id>/  (use the absolute path of the current repo)
- role-context-path: <role-folder>/role-context.json
- cv-pdf: <cv-path>
- escalation-reason: <reason>
- escalation-payload: <payload-json>

Self-mark Notion before returning your status line (mark-applied / mark-escalated / mark-failed).
Use session apply-<id>. Final line only: APPLIED <id> <tag> | HUMAN_REQUIRED <id> <reason> | RETRY_LATER <id> <reason> | ERROR <id> <reason>.
```

Use `subagent_type: edge-case-applicator-haiku` for haiku_roles and `subagent_type: edge-case-applicator` for sonnet_roles.

If the combined batch has more than 10 entries, split into batches of 10 and process sequentially.

### Step 4 — Greenhouse serial relay (if any)

For each `gh_roles` entry, one at a time:

1. Dispatch edge-case agent with instruction to leave session open on email-verify.
2. If agent returns `HUMAN_REQUIRED <id> greenhouse-email-verification-pending`:
   - Fetch code: run `python scripts/fetch_greenhouse_code.py`, or use the connected Gmail MCP server's `search_threads` tool (the tool-name prefix varies per install; find it with ToolSearch) with `from:greenhouse newer_than:5m`.
   - Enter code directly via `playwright-cli -s=apply-<id> fill <ref> <char>` (one char per box).
   - Click Submit, verify confirmation, close session.
   - `python scripts/auto_apply.py mark-applied --role <id> --via greenhouse-with-email-verification --confirmation "<phrase>"`
3. If agent returns anything else, parse normally.

### Step 5 — Print results table

```
## Batch results

| Role | Company | Result |
|---|---|---|
| <title> | <company> | ✅ Applied / ⚠️ Escalated / ❌ Failed |
...

Applied: N  Escalated: N  Failed: N  Expired: N
```

## What this skill MUST NOT do

- Do not read JDs, CV content, or application_profile.json into the main session.
- Do not call `playwright-cli` directly except for Greenhouse email-verify code relay.
- Do not call mark-* commands after agent results — agents self-mark.
- Do not print agent prose — if an agent outputs more than one line, read only the last line.
