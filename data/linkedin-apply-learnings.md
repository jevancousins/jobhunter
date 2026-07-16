# LinkedIn Apply Automation — Learnings

## Date: 2026-02-15
## Role: a Data Engineer opening posted via a recruitment agency (details anonymised)

---

## End-to-End Workflow

1. **Review Job** (/review-job) — ~5 min
   - Scored in the CONSIDER band (borderline APPLY)
   - Captured JD via screenshots (get_page_text captured sidebar, not JD panel)

2. **Tailor CV** (/tailor-cv) — ~10 min
   - Selected `data-engineer` variant template
   - Made surgical modifications (profile, skills, bullets, projects, interests)
   - Built PDF with pdflatex, verified page fill (FULL), factual verification passed
   - Output: `cv/output/tailored/<company>-data-engineer.pdf`

3. **LinkedIn Apply** (Chrome) — ~5 min
   - Clicked LinkedIn Apply button — modal opened successfully
   - Step 1 (Contact Info): Pre-filled correctly, clicked Next ✅
   - Step 2 (Resume): User uploaded the tailored PDF manually ✅
   - Step 3+: User completed remaining steps manually

4. **Notion Update** — Blocked by serialization bug

---

## What Worked Well

- **CV tailoring was highly effective**: Surfacing niche master_cv.json content that matched the employer's domain (in both the profile and interests sections) made the CV uniquely suited to this role — a good example of why interests and extra-curriculars belong in the master file
- **Review-job scoring** provided clear analysis of strengths and gaps before investing time in tailoring
- **Page fill optimisation** worked perfectly — added certifications line to fill 1-line gap
- **Factual verification** caught no errors (all metrics matched master_cv.json)
- **LinkedIn Apply modal opened** correctly via Chrome click automation

## What Didn't Work

### Chrome Automation Limitations
- **LinkedIn Apply modal** is rendered in a way that makes it difficult for browser automation tools to interact with:
  - `read_page` returns empty for modal elements
  - `find` cannot locate modal buttons
  - JavaScript DOM queries find buttons with zero dimensions (hidden/shadow DOM)
  - Coordinate-based clicks on the "Next" button didn't register (modal overlay positioning issue)
  - The modal elements aren't accessible via standard DOM queries
- **Workaround**: User had to manually click through the modal steps after the initial LinkedIn Apply button click
- **get_page_text** captured the left sidebar (job recommendations list) instead of the right-panel JD content

### Notion MCP Bug (Ongoing)
- All tools with union-typed parameters (`parent`, `data`, `new_parent`) fail with ZodError
- Affects: `notion-create-pages`, `notion-update-page`, `notion-move-pages`
- Created standalone page with details as workaround; user must manually move to database

---

## Verdict: Is This Worth Doing More Often?

### Time Investment
| Step | Claude Time | User Time | Total |
|------|------------|-----------|-------|
| /review-job | 5 min | 0 min | 5 min |
| /tailor-cv | 10 min | 0 min | 10 min |
| LinkedIn Apply (Chrome) | 3 min | 2 min | 5 min |
| Notion update | 2 min | 3 min (manual) | 5 min |
| **Total** | **20 min** | **5 min** | **25 min** |

### Value Assessment
- **High value**: CV tailoring is the biggest time-saver. Manually tailoring a CV takes 30-60 min; Claude does it in ~10 min with full factual verification
- **Medium value**: Job scoring provides useful signal, especially for borderline roles
- **Low value (currently)**: Chrome automation for LinkedIn Apply is limited — the modal interaction requires manual intervention. If LinkedIn's modal becomes more accessible, this could improve significantly
- **Blocked**: Notion integration needs the serialization bug fixed to be useful

### Recommendation
**Yes, worth doing for roles you care about** — but focus Claude's effort on review + CV tailoring (the high-value steps) and do the LinkedIn Apply click-through manually (it's only 30 seconds). The end-to-end automation isn't seamless yet due to LinkedIn's modal implementation, but the CV tailoring alone justifies the workflow.

### Future Improvements
1. Fix Notion MCP serialization bug to enable automatic database updates
2. Investigate LinkedIn's modal rendering for better Chrome automation
3. Consider pre-filling common LinkedIn Apply fields (years of experience, etc.) via the automation
4. Add cover letter generation to the workflow for roles that request one
5. Build a `/apply-job` skill that orchestrates the full pipeline

---

## Update: 2026-04-21 — Re-test with current Chrome MCP

**Verdict reversed: LinkedIn Apply is now automatable end-to-end.**

### What works now
- `find` + `read_page` produce accurate DOM refs for modal elements
- Modal opens reliably when the job is selected in the detail panel and the LinkedIn Apply button is clicked via `computer.left_click` with a `ref` (not raw coordinates)
- Contact info (email, phone country code, phone number) is pre-filled by LinkedIn from the profile
- `Dismiss` button works, presents "Save this application?" confirmation, and `Discard` cleanly aborts without submitting

### Gotchas discovered
- **Direct navigation to `/apply/?openSDUIApplyFlow=true` does NOT open the modal reliably** — must go via job-search → click job card → click LinkedIn Apply in detail panel
- **Raw-coordinate clicks and `.click()` JS calls silently fail** — use `computer.left_click` with a `ref` from `find`/`read_page` (trusted-event path)
- **Many jobs in Notion "To Review" queue are stale** — several queued candidates returned "No longer accepting applications". Freshness matters; filter by `f_TPR=r86400` (past 24h) + `f_AL=true` (LinkedIn Apply)
- **JS tool may return `[BLOCKED: Cookie/query string data]`** if the result contains URLs — keep return values simple strings

### Updated workflow
1. `/search-jobs` or direct LinkedIn search with `?f_AL=true&f_TPR=r86400` to get a list of active LinkedIn Apply roles
2. Click the role card in the left list to populate the right detail panel
3. Find + click the LinkedIn Apply button via ref
4. Driver iterates through modal steps, filling fields from `application_profile.json` + `screening-answers.json`
5. Stop at the final "Submit application" step; human approves; one final click

### Next steps
- Run the first end-to-end `/apply-job` with human approval gate on a freshly discovered LinkedIn Apply role
- Document exact field-filling sequence the first time through so the driver can be codified
