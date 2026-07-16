---
name: check-emails
description: >
  Check Gmail for job application responses and job alert emails, then update Notion and inform the user.
  Use whenever the user says "check my emails", "any responses?", "check for job updates",
  "any rejections?", "any interview invites?", "check Gmail", or similar.
  Also trigger if the user mentions email in the context of job hunting or applications.
  This skill handles both application responses (rejections, interview invites, offers)
  and job alert digest emails (LinkedIn, BNP Paribas, Indeed, etc.).
---

# Check Emails Skill

Scan Gmail for job-related emails since the last check, categorize them, update the Notion Jobs Database, and present a clear summary to the user.

## Usage

```
/check-emails                # Check all job emails since last check
/check-emails --responses    # Only check application responses
/check-emails --alerts       # Only check job alert digests
/check-emails --since 3d     # Override time range (3 days)
```

## Argument Handling

1. **No argument**: Check both responses and alerts since last check
2. **`--responses`**: Only check application response emails
3. **`--alerts`**: Only check job alert digest emails
4. **`--since Nd`**: Override time range to last N days (e.g., `--since 7d`)

---

## Workflow Overview

```
1. Load last-check timestamp
2. Search Gmail for application responses
3. Search Gmail for job alert digests
4. Categorize and extract information from each email
5. Match responses to existing Notion entries
6. Update Notion statuses
7. Present summary to user
8. Save new last-check timestamp
```

---

## Step 1: Load Last-Check Timestamp

Read the timestamp file at `data/last_email_check.json`:

```json
{
  "last_check": "2026-02-13T14:30:00Z",
  "last_check_human": "Feb 13, 2026 at 2:30 PM"
}
```

If the file doesn't exist, this is the first run. Default to checking the last 7 days and inform the user: "This is the first email check — scanning the last 7 days."

Convert the timestamp to Gmail's `after:` date format: `after:YYYY/MM/DD`

---

## Step 2: Search Gmail for Application Responses

Use `search_gmail_messages` with these queries. Run them as separate searches and combine results, deduplicating by message ID.

### Query 1 — Direct application responses
```
subject:(application OR applied OR candidature) after:{DATE} -category:promotions
```

### Query 2 — Rejection signals
```
(subject:(unfortunately OR regret OR "not selected" OR "other candidates" OR "not progressing" OR "not successful") OR ("decided not to move forward" OR "not be progressing" OR "does not match")) after:{DATE} -category:promotions
```

### Query 3 — Interview invitations
```
subject:(interview OR "phone screen" OR "next steps" OR "invite" OR assessment) after:{DATE} -category:promotions
```

### Query 3b — Calendly/scheduling confirmations (interview bookings)
```
from:(calendly.com OR goodtime.io OR cronofy.com) subject:(confirmed OR scheduled OR interview) after:{DATE}
```

### Query 4 — Offers
```
subject:(offer OR "congratulations" OR "pleased to" OR "delighted to") after:{DATE} -category:promotions
```

For each message returned, read the full message using `read_gmail_message` to get the body content.

### Distinguishing LinkedIn Notification Types

LinkedIn sends several email types via `jobs-noreply@linkedin.com`. Distinguish them by subject line pattern:

- **Application confirmation**: Subject contains "your application was sent to {Company}" → Application Confirmation
- **Rejection via LinkedIn**: Subject contains "Your application to {Role} at {Company}" AND body says just "Your update from {Company}" → Rejection (LinkedIn's rejection notification is deliberately vague but this is always a rejection)
- **Job alert digest**: Subject starts with `"Data Scientist":` or `Explore new jobs for` → Job Alert (handle in Step 3)

This matters because all three come from the same sender address. Parse the subject line to categorize correctly.

---

## Step 3: Search Gmail for Job Alert Digests

### Query 5 — LinkedIn job alerts
```
from:jobalerts-noreply@linkedin.com after:{DATE}
```

Note: LinkedIn job **alerts** come from `jobalerts-noreply@linkedin.com` (with "jobalerts" prefix), while application confirmations and rejections come from `jobs-noreply@linkedin.com`. Use the correct sender to avoid mixing alerts with application notifications.

### Query 5b — LinkedIn job recommendations
```
from:jobs-noreply@linkedin.com subject:("Explore new jobs" OR "jobs you might") after:{DATE}
```

### Query 6 — Other job alert platforms
```
from:(indeed.com OR glassdoor.com) subject:(job OR alert OR role OR opportunity) after:{DATE}
```

Extend the `from:` list with any senders in `data/search_config.json` `notifications.alert_senders` (optional key: the user's own job boards, bank/company career alerts, local platforms such as welcometothejungle.com or talent.io).

For alert emails, read the full message body to extract job listings.

---

## Step 4: Categorize Each Email

For each email found, classify it into one of these categories:

### Application Response Categories

| Category | Status Update | Signals in Email |
|----------|--------------|-----------------|
| **Rejection** | → "Rejected" | "unfortunately", "regret", "not selected", "other candidates", "decided not to move forward", "does not match our current needs", "not be progressing" |
| **Interview Invite** | → "Phone Screen" or "Technical Interview" | "interview", "phone screen", "assessment", "would like to invite you", "next steps", "schedule a call" |
| **Application Confirmation** | → No change (already "Applied") | "received your application", "thank you for applying", "application has been submitted" |
| **Offer** | → "Offer" | "pleased to offer", "offer letter", "congratulations" |
| **Interview Scheduled (Calendly)** | → "Phone Screen" | Calendly/scheduling tool confirmation with company name. Extract the company from the body. |
| **Follow-up / Other** | → "Response Received" | Anything that doesn't fit above but is clearly about a specific application |

### Alert Categories

| Category | Action |
|----------|--------|
| **LinkedIn Job Alert** | Extract job titles and companies. Present to user as potential leads. |
| **Platform Alert** | Extract job titles and companies. Present to user as potential leads. |

### Extraction Rules for Responses

From each response email, extract:
- **Company name**: Look in the "From" address domain, email signature, and body text
- **Role title**: If mentioned in the email subject or body
- **Response type**: Classification from the table above
- **Key quote**: A one-line excerpt that captures the decision (for user's reference)
- **Date**: When the email was sent

### Extraction Rules for Alerts

From each alert email, extract a list of:
- **Job title**
- **Company name**
- **Location** (if available)
- **URL** (if a direct link is available in the email)

Only extract roles that might pass basic pre-screening (skip obvious mismatches like marketing, design, sales, HR roles). Use the same dealbreaker list from `data/job_goals.json`.

---

## Step 5: Match Responses to Notion Entries

For each application response, try to match it to an existing entry in the Notion Jobs Database.

### Matching Strategy

1. **Search by company name** using `notion-search` with the company name as the query, scoped to the database data source
2. If multiple matches, narrow by role title similarity
3. If no match found, note it as "unmatched" — the user may have applied outside of the tracked system

Use fuzzy matching for company names since email senders often use abbreviated or different names than what's in Notion:
- an email from "Acme Consulting Group" matches a Notion row named "Acme"
- "noreply@acmeapp.com" matches "Acme" via the From domain
- Look at the From address domain for clues

### Database Details

- **Database ID**: `NOTION_JOBS_DB_ID` from `.env`
- Resolve the data source ID dynamically (fetch the database, take its first data source), or read it from `data/notion_ids.json` key `jobs_db_data_source` if recorded during onboarding.

---

## Step 6: Update Notion

For matched entries, update using `notion-update-page`:

```json
{
  "page_id": "<matched-page-id>",
  "command": "update_properties",
  "properties": {
    "Status": "<new status from category table>",
    "AI Analysis": "<existing analysis>\n\n---\nEMAIL UPDATE ({date}): {category} — {key quote}"
  }
}
```

### Update Rules

- **Only update Status forward** — never regress a status. The progression is:
  `To Review → Consider → Apply → Applied → Response Received → Phone Screen → Technical Interview → Final Round → Offer → Accepted`
  Also: `→ Rejected` and `→ Expired` are terminal states from any point.

- **Rejections**: Set Status to "Rejected". This is always appropriate regardless of current status.

- **Interview invites**:
  - If the email mentions "phone screen" or "initial call" → "Phone Screen"
  - If the email mentions "technical" or "assessment" or "coding" → "Technical Interview"
  - If unclear, default to "Phone Screen"

- **Offers**: Set Status to "Offer"

- **Application confirmations**: Only update if current status is "Apply" or "Consider" → set to "Applied"

- **Append to AI Analysis** — don't overwrite existing analysis. Add a separator and the email update.

### Unmatched Responses

For application responses that don't match any Notion entry, **do not create a new entry**. Instead, include them in the summary report for the user with the note: "No matching Notion entry found — you may have applied outside the tracked system."

---

## Step 7: Present Summary to User

Always present a clear summary, even if nothing was found. The user explicitly asked to always be informed.

### When emails are found:

```
## Email Check Summary
Checked emails since {last_check_date}.

### Application Responses
| Company | Role | Response | Status Updated | Date |
|---------|------|----------|----------------|------|
| Front | - | Rejection | → Rejected | Feb 13 |
| BCG Platinion | AI Architect | Rejection | → Rejected | Feb 13 |

### Unmatched Responses
- Email from {company}: "{key quote}" — no matching Notion entry found.

### Job Alerts
Found {N} new roles in alert emails:
| Title | Company | Location | Source |
|-------|---------|----------|--------|
| Data Scientist | BNP Paribas | Paris | LinkedIn Alert |

{If any alert roles look promising based on pre-screening}:
"2 roles from alerts look worth reviewing — want me to run /review-job on them?"

### No Updates
If no relevant emails were found: "No new job-related emails since {last_check_date}."
```

### Tone

Keep it concise and factual. Rejections are normal in job searching — don't add unnecessary consolation or commentary. Just present the facts and move on.

---

## Step 8: Save Updated Timestamp

After completing the check, update `data/last_email_check.json`:

```json
{
  "last_check": "2026-02-13T16:45:00Z",
  "last_check_human": "Feb 13, 2026 at 4:45 PM"
}
```

Use the current time (from `date -u +%Y-%m-%dT%H:%M:%SZ` in bash) as the new timestamp.

---

## Edge Cases

### Duplicate Emails
The same rejection might appear in multiple Gmail queries (e.g., it matches both "application" and "unfortunately" queries). Deduplicate by message ID before processing.

### Bulk LinkedIn Alerts
LinkedIn job alert digests can contain 10-20+ roles. Don't try to review all of them. Extract the list, apply basic pre-screening (skip obvious mismatches), and present the shortlist to the user. Let them decide which to pursue.

### Non-English Emails
If the user applies to roles in non-English markets, responses may arrive in other languages; classify them the same way. Example (French): rejection signals include "malheureusement", "votre candidature", "nous avons le regret"; interview signals include "entretien". Apply the equivalent pattern for the user's target-market languages.

### Already-Processed Emails
The timestamp mechanism should prevent re-processing, but if an email was already reflected in Notion (e.g., status is already "Rejected"), skip the update and don't report it again.

### Rate Limiting
If there are many emails to process, batch the Notion updates. Use `notion-update-page` for each update (batch creation isn't applicable for updates to existing pages).

---

## Files Referenced

| File | Purpose |
|------|---------|
| `data/last_email_check.json` | Timestamp of last email check (created on first run) |
| `data/job_goals.json` | Dealbreaker industries for alert pre-screening |

## Gmail Tool Reference

| Tool | Purpose |
|------|---------|
| `search_gmail_messages` | Search Gmail with standard query syntax |
| `read_gmail_message` | Read full message content by message ID |

## Notion Tool Reference

| Tool | Purpose |
|------|---------|
| `notion-search` | Find existing job entries by company name |
| `notion-update-page` | Update Status and AI Analysis for matched entries |
| `notion-fetch` | Fetch full page details if needed for matching |
