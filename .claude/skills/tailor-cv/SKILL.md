---
name: tailor-cv
description: Create a tailored CV from master_cv.json for a specific job posting. Use when the user wants to customise their CV for a job application, provides a job URL, or discusses applying to a specific role.
argument-hint: "[job-url or job-description]"
---

# Tailor CV Skill

Generate a role-specific CV by copying the closest variant template and making surgical modifications.

## Formatting Rules (MUST follow)

**Bold (`\textbf{}` / `**...**`) is reserved for structural emphasis only.**

Allowed uses of bold:
- Section headers (driven by `\section{}` in cv.cls — no action needed)
- Experience company / role titles (driven by `\cventry` — no action needed)
- Education institution / degree (driven by `\cveducation` — no action needed)
- **The first term of each bullet in the Projects section only** (e.g., `\textbf{ProjectName} -- one-line project description ...`). This is the one place inline bold is expected.

Disallowed uses (strip these during tailoring):
- Bold anywhere in the Profile paragraph — prose only, no inline emphasis
- Bold inside `\cvbullet{}` text in the Experience section (numbers, company names, metrics: all plain)
- Bold inside Skills category values
- Bold on project names when they appear in the Profile paragraph (mentioned inline, not as a list heading)

Before running pdflatex, grep the tailored `.tex` for `\textbf`. Any match outside the Projects-section bullet-heading pattern is a violation — remove it. When in doubt, remove it.

## Usage

```
/tailor-cv https://example.com/job-posting
/tailor-cv [paste job description when prompted]
```

## Input Handling

1. **URL provided**: Use WebFetch to retrieve job description
2. **Text provided**: Parse the pasted job description directly
3. **No argument**: Ask user to provide URL or paste job description

---

## Workflow Phases

### Phase 1: Job Analysis

Read and analyse the job description. Produce a compact structured summary (~6 lines):

- **Required skills** (hard & soft) - must-haves
- **Desired skills** - nice-to-haves
- **Key responsibilities** - day-to-day duties
- **Seniority level** - junior, mid, senior, lead, principal
- **Domain** - AI/ML, data science, quant, software, finance, etc.
- **Company** - name + one-line context

This summary becomes the primary reference for all subsequent phases. Discard the full JD text from working memory after this point.

### Phase 2: Template Selection + Conditional Research

#### Select Template

Map the job to the closest variant:

| Variant | Role Types |
|---------|------------|
| `ai-ml` | ML Engineer, AI Engineer, GenAI, Applied Scientist |
| `data-science` | Data Scientist, Data Analyst, Analytics Engineer |
| `software-eng` | Software Engineer, Backend Developer, Full-stack |
| `portfolio-risk` | Portfolio Analyst, Risk Analyst, Performance Analyst |
| `quant-dev` | Quant Developer, Quant Analyst, Algo Trading |
| `research` | Research Analyst, Economist, Investment Research |
| `client-solutions` | Implementation, Solutions Engineer, Client-facing technical |
| `forward-deployed` | Forward Deployed Engineer, FDE, Field Engineer |
| `data-engineer` | Data Engineer, Platform Engineer, Data Pipeline |
| `applied-ai-solutions` | AI Solutions, Applied AI, AI Deployment |

**Copy** the variant to the build directory:
```bash
cp cv/variants/[variant].tex cv/output/tailored-build/[company]-[role-slug].tex
```

#### Conditional Company Research

Only do WebSearch for company context if BOTH conditions are true:
1. Company is **not** in the well-known list below
2. JD **lacks** an "About us" / company description section

**Well-known companies (skip research):** Anthropic, OpenAI, Google, DeepMind, Meta, Amazon, Apple, Microsoft, Netflix, Stripe, Palantir, Databricks, Snowflake, Cohere, Mistral, Goldman Sachs, JPMorgan, Morgan Stanley, BlackRock, Citadel, Two Sigma, Point72, Man Group, Jane Street, BCG, McKinsey, Bain, Revolut, Monzo, Wise, Deliveroo, Spotify, Bloomberg, LSEG, HSBC, BNP Paribas, Braze

If research IS needed, keep it to one WebSearch query focused on company values and product.

### Phase 3: Surgical Modifications

**First: Read `data/master_cv.json` in full.** It fits comfortably in context and is needed for profiles, skills, bullets, projects, and factual accuracy checks. Do this once at the start of Phase 3, not piecemeal.

Work on the copied template file. Make **only** the changes needed to align the CV with the job. Changes are listed below in order of likelihood.

#### Always modify:

**Profile rewrite** — The profile is the most error-prone section because it is rewritten from scratch each time. Use the full `master_cv.json` already in context as the source of truth for all factual claims.

The profile should sell the candidate's most valuable offering(s) for **this specific job**. Identify the 1-2 strongest selling points where the candidate's skills/experience intersect with the role's key requirements, and lead with those. Never include "seeking a role" or objective-style language. Keep to 3-4 sentences.

**Mandatory structure (each sentence must serve one of these roles):**
1. **Lead:** Professional identity + the most relevant selling point for this specific role (e.g. for a risk modelling role, lead with risk/derivatives experience; for an AI role, lead with RAG/LLM experience). See **Profile opener branding** below for how to choose the professional identity.
2. **Evidence:** 1-2 quantified achievements that demonstrate value in areas the job cares about
3. **Close:** A forward-looking statement framed as what the candidate brings to the employer, tied to the role. Example pattern: "Brings a strong quantitative foundation from [degree subject], with [relevant credential] for [role-relevant value]." **NOT** a static credential dump like "[Subject] graduate from [university] with [credential]." - that tells the employer nothing about what value those credentials bring. **Never name the target company in the Profile** - keep language generic (e.g. "client-facing environments" not "at [Company] [City]").

**Profile opener branding** — The professional identity in the Lead sentence does NOT have to match the official job title or the target role's title. It is independent from the Experience section job title (which follows its own rules below). Choose from three tiers based on how honestly the candidate can claim the target role's title:

**Tier 1 — Claim the title directly.** Use the target role's job title (or close synonym) when the candidate's experience in `master_cv.json` genuinely supports it. The test: could the candidate defend this identity in an interview, pointing at concrete work they have done?

Example pattern:
- Applying to a Data Engineer role, where the candidate has hands-on pipeline work → "Data Engineer with N years of experience..." (N from `master_cv.json` employment dates)

**Tier 2 — Use a compound or domain-first format.** For borderline titles where the candidate has strong adjacent experience but hasn't held the exact title. Claim the territory without pretending to have held the role.

Patterns (strongest to weakest):
- Compound identity: "[Target domain] and [actual domain] professional with N years..."
- Domain-first: "[Target domain] professional with N years in [actual domain]..."

Do NOT use weak qualifiers like "with X knowledge" — this undersells the candidate's hands-on experience.

**Tier 3 — Use a descriptive expertise label.** When the target role's title is too specific for the candidate to genuinely claim, or too different from their actual experience. Use a lowercase descriptor (e.g. "specialist", "professional") that honestly frames the candidate's relevant expertise.

Example pattern:
- Applying to an ML Researcher role, where the candidate is a strong quantitative practitioner but not a researcher → "Quantitative professional with N years..."

**Rules for all tiers:**
- Must be truthfully supported by `master_cv.json`
- Judge which tier applies by comparing the target title against the candidate's actual titles and responsibilities in `master_cv.json` — never from assumptions about the candidate
- Tier 3 labels must not claim a specific job title the candidate hasn't held (e.g. "Senior Data Engineer" is a title claim; "data engineering specialist" is a descriptor)
- When in doubt, drop one tier (claim → compound → descriptor) rather than overclaim

**Factual accuracy (non-negotiable):** Every specific claim must match `master_cv.json` or the variant template exactly. Never embellish language levels, years, metrics, job titles, or degree classifications. Read language proficiency levels from the `languages` section of `master_cv.json`, employment dates and total experience from the `experience` entries, and education details from `education`. Never claim anything not present there. If unsure about a fact, check the source before writing it.

**Skills adjustment** — Add, remove, or reorder skills to match JD keywords. Reference the skills section in `master_cv.json` (already in context) if the template is missing a required skill.

**Project selection** — Always evaluate whether the template's projects are the best fit for this specific job. Check the `relevance` ratings in each project's entry in `master_cv.json` `projects` and select the 2 most relevant projects. If the template already has the best projects, keep them. If a higher-relevance project exists, swap it in. The available project pool is whatever `master_cv.json` `projects` contains — never invent projects.

#### Conditionally modify:

**Bullet swap** (if 1-3 bullets are poorly aligned) — Swap with better matches from the primary employer's bullet pool in `master_cv.json` (`experience.<primary_employer_key>.bullets`, already in context). If >3 bullets need swapping, reconsider template selection.

**Bullet rewording** — Adjust wording of existing bullets to use JD terminology. Do not change the underlying facts.

**Secondary experience** (if needed) — Add or remove entries. Refer to the variant-specific focus table in `cv/CLAUDE.md` for guidance.

**Job title adjustments** — Only adjust titles when the official title is genuinely misleading for the target role. The default should be to **keep the original title**.

**When to adjust:**
- The original title would actively confuse recruiters screening for the target role (e.g. a broad internal title obscures directly relevant specialist work)
- The alternative title is a closer description of the actual day-to-day work for this specific application

**Rules (non-negotiable):**
- The new title must be **verifiable** — if the employer calls the candidate's former employer, the described responsibilities must match what HR would confirm
- Must reflect actual seniority level (no inflation or deflation)
- Must stay within the same broad domain as the actual work
- Preserve company name and dates
- **Never downgrade seniority** — do not use a title that understates the leadership, reporting lines, or strategic scope evidenced in `master_cv.json`

**Allowed title framings per employer** come from `experience.<key>.title_variants` in `master_cv.json`. Each experience entry may list pre-vetted alternative titles (with guidance on when each applies). Only ever use the official title or one of the entry's `title_variants` — never invent a new framing on the fly. If `title_variants` is absent for an entry, the official title is the only option.

Always report title changes in the modifications summary with justification.

**Education** — Add relevant modules from the education section in `master_cv.json` (already in context) if applicable.

#### Rarely modify:

**New bullet interview** — Only if the JD requires experience not present anywhere in `master_cv.json`. Use AskUserQuestion to interview the user for concrete details before writing a bullet. Never fabricate.

#### Holistic content evaluation (after all modifications above)

After making surgical changes, step back and evaluate the **overall content mix across ALL sections**. Every piece of content on the page should earn its place for this specific job. Ask:

1. **Is any content generic filler rather than role-relevant?** Interests, broad coursework, low-relevance secondary experience, and vague project descriptions are all candidates for replacement with more relevant content from another section.

2. **Would more Experience content serve the job better than expanded Projects/Education?** For roles that value depth of professional experience (operations, project management, client-facing), allocate more space to experience bullets and reduce project descriptions. For roles that value personal technical projects (software engineering, ML), keep 2 full project descriptions and trim experience.

3. **Should the primary employer be split into two entries?** If the candidate's `master_cv.json` records an earlier phase at the same employer (e.g. an internship that converted to a permanent role) and that earlier phase's bullets are directly relevant to the job AND the page needs ~2 more lines of content, separate the combined entry into its two roles with their respective date ranges from `master_cv.json`. This adds relevant content rather than generic filler. Keep the combined entry when the earlier-phase bullets add little relevance or page space is tight.

4. **Are there strong unused primary-employer bullets in `master_cv.json` that match better than current content?** If so, swap them in — even if the template bullets are acceptable. "Acceptable" is not the bar; "best available match" is.

**The key principle:** when page space is available, fill it with the most relevant content from ANY section in `master_cv.json`, not by expanding the nearest section with generic filler. A relevant experience bullet beats an interests line every time.

#### Key rule: master_cv.json is your source of truth

All content decisions (profile wording, skill selection, bullet swaps, project choices, factual claims) should reference the full `master_cv.json` loaded at the start of this phase. Never write claims from memory when the source data is in context.

### Phase 4: Build + Programmatic Verification

1. **Build PDF** (from the repo root; pdflatex must run with `cv/` as the working directory for its relative paths):
   ```bash
   cd cv && \
   export PATH="/Library/TeX/texbin:$PATH" && \
   pdflatex -interaction=nonstopmode -output-directory=output/tailored-build output/tailored-build/[filename].tex 2>&1
   ```

2. **Check page fill** (from the repo root):
   ```bash
   python scripts/check_page_fill.py cv/output/tailored-build/[filename].pdf
   ```

3. **Handle result:**
   - **FULL** (exit 0) → Proceed to Phase 5
   - **UNDERFILLED** (exit 1) → Add content. The script reports approximate lines to fill. **Prioritise relevance over convenience** — revisit the holistic evaluation from Phase 3:
     1. Add a stronger primary-employer bullet from `master_cv.json` that matches the JD
     2. Separate the primary employer into its two role entries (if the earlier-phase bullets are relevant, adds ~2 lines)
     3. Add or expand secondary experience entries from `master_cv.json` relevant to the role
     4. Expand project descriptions with role-relevant technical detail
     5. Add certifications to skills (if relevant to role)
     6. Add interests line (LAST RESORT — only if no relevant content remains)
   - **OVERFLOW** (exit 2) → Trim content. Remove the **least relevant** content first:
     1. Remove interests line (if present)
     2. Remove the least relevant bullet or secondary experience entry
     3. Shorten the weakest bullet for this role
     4. Trim project descriptions (remove least relevant technical detail)
   - **SHORT_LINES** (exit 3) → **Horizontal wrap tails below 50% fill are a blocker.** The script reports each flagged line with its section and fill percentage. Fix by rewording so either (a) the wrap tail lands ≥ 50%, or (b) the content fits on one line. See `cv/CLAUDE.md` section "Fixing Wrap Tails" for the ordered strategy:
     1. Shorten the sentence to fit on one line (remove filler words).
     2. Rebalance the wrap (trim the earlier part so the tail is longer).
     3. Extend with substantive content (only if factual; never pad).
     4. Move items between Skills categories so orphans fit on the primary line.
     5. Drop the low-signal item.
     **Common orphan patterns to watch:** trailing "annually" after a monetary value, single-word Skills tails like "pytest", project-description tails like "via LaTeX pipeline".

4. **Rebuild + recheck** after any changes. Iterate until exit code 0 — no SHORT_LINES remaining.

5. **Factual verification** — Before copying, re-read the final `.tex` file and cross-reference EVERY factual claim against `master_cv.json` (still in context from Phase 3). Check each of these:
   - **Modules/coursework** — every module name must exist in `master_cv.json` `education.modules` or `education.modules_by_year`. Do not invent module names.
   - **Metrics and numbers** — monetary amounts, percentages, team sizes, scale figures must match the source bullet exactly.
   - **Job titles and dates** — must match `master_cv.json` experience entries (or an entry's `title_variants`). No overlapping dates within the same employer.
   - **Skills and tools** — every item in the Skills section must appear somewhere in `master_cv.json` `skills` or be explicitly mentioned in the JD as something the candidate has.
   - **Project descriptions** — technical details (frameworks, languages, what the project does) must match `master_cv.json` `projects` entries.
   - **Profile claims** — language levels, experience duration, degree classification, and any grades must all match the `languages`, `experience`, and `education` sections of `master_cv.json` exactly.
   - **Certifications** — must exist in `master_cv.json` `certifications`.

   If ANY claim cannot be traced to `master_cv.json` or the JD, remove or correct it before proceeding. This check prevents hallucinated content from reaching the final CV.

6. **Copy final PDF:**
   ```bash
   cp cv/output/tailored-build/[filename].pdf cv/output/tailored/
   ```

### Phase 5: Review, Report + Notion Save

#### Independent Review

After building, re-read the Phase 1 summary and verify:
1. **Date consistency** - no overlapping dates between roles (especially split entries at the same employer)
2. **No redundancy** - profile should not duplicate experience bullets verbatim
3. **Gaps identified** - note any required skills not evidenced
4. **ATS compliance** - if specific formatting was requested, confirm

Report any issues and fix before finalising.

#### Report to User

After generating the CV, report:

1. **Template used**: Which variant was the base
2. **Modifications made**: What was changed from the template (profile, bullet swaps, skills changes)
3. **Skills matched**: Which job requirements map to experience
4. **Gaps identified**: Skills/experience not demonstrated
5. **Page fill**: Script output (status + gap)
6. **Output paths**: .tex and .pdf file locations

#### Save Job Description to Notion

**When:** After the user confirms they want to apply.

1. Search for existing entry with the connected Notion MCP server's search tool in the Jobs Database (the tool-name prefix varies per install; find it with ToolSearch)
2. Update or create the entry with the Notion MCP server's update-page tool:
   - Set "Job Description" property to the full JD text
   - Preserve section headers and bullet points
   - Trim boilerplate (legal text, cookie notices)
3. If Notion fails, save to `data/job_descriptions/[company]-[role-slug].md`

---

## Output Location & Naming

```
cv/output/
├── tailored/              # FINAL PDFs only - clean folder for applications
│   └── [company]-[role-slug].pdf
│
└── tailored-build/        # Source files + build artifacts
    ├── [company]-[role-slug].tex
    ├── [company]-[role-slug].aux
    ├── [company]-[role-slug].log
    └── [company]-[role-slug].out
```

**Naming:** `[company]-[role-slug]` — lowercase, hyphens for spaces, no special characters.
Examples: `citadel-quant-researcher`, `anthropic-ml-engineer`, `revolut-data-scientist`

---

## Content Guardrails

### Formatting Rules
- **No em-dashes** (—). Use commas, full stops, semicolons, or " - " (spaced hyphens). This is a telltale AI signal.
- **No LLM-sounding language.** Avoid formulaic phrasing and overly polished language. Bullets should read like a human wrote them.
- **No fabrication.** Interview the user (AskUserQuestion) for new bullets based on concrete details.

### Structural Rules
- **Experience duration.** Compute tenure from the employment dates in `master_cv.json` and always state it consistently (round down to whole years; never inflate, never understate an established round number).
- **Reverse-chronological experience order** (non-negotiable). Emphasise relevant roles via bullet count and wording, not reordering.
- **Recency weighting.** Experiences 5+ years old carry less weight even if topically relevant. Recent experience (last 2-3 years) is prioritised. Old achievements should not feature in the Profile; short, dated stints belong only in their own Experience section.
- **Split-role date handling.** When an employer entry is split into two roles, use the exact date ranges from `master_cv.json` for each. Never overlap.
- **Date format.** All experience entries must use `Start -- End` format, even single-month stints (`Aug 2020 -- Aug 2020`, not just `Aug 2020`). Single-date entries cause issues with CV parsers and application form auto-fill.
- **Section title rule.** `Projects \& Interests` if interests included, `Projects` if omitted.
- **Languages always as `\cvskillcatlast`.** List each language with its proficiency exactly as recorded in the `languages` section of `master_cv.json`.

### LaTeX Commands Reference

```latex
\cvprofile{...}           % Profile paragraph
\section{...}             % Section heading
\cvskillcat{Category}{items}      % Skill category with line after
\cvskillcatlast{Category}{items}  % Final skill category (no line)
\cventry{Company}{Title}{Dates}{Location}  % Experience entry
\cvbullet{...}            % Bullet point in itemize
\cveducation{Institution}{Degree}{Dates}{Location}  % Education
```

---

## Files Referenced

| File | Purpose |
|------|---------|
| `data/master_cv.json` | Source of all CV content (read selectively) |
| `cv/cv.cls` | LaTeX document class |
| `cv/variants/*.tex` | Template variants (starting point) |
| `cv/sections/header.tex` | Contact info (included via `\input`) |
| `data/learning_gaps.md` | Track missing skills |
| `data/job_descriptions/*.md` | Fallback storage for JDs |
| `scripts/check_page_fill.py` | Programmatic page fill verification |
