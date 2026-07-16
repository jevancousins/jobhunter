---
name: cover-letter
description: Write a tailored cover letter for a job posting. Uses master_cv.json, job_goals.json, and company research.
argument-hint: "[job-url] [--french] [--auto]"
---

# Cover Letter Skill

Generate a tailored cover letter for a job posting, using content from `data/master_cv.json`, career goals from `data/job_goals.json`, and company research.

## Usage

```
/cover-letter https://example.com/job-posting
/cover-letter https://example.com/job-posting --french
/cover-letter https://example.com/job-posting --auto       # autonomous: no user interview
/cover-letter [paste job description when prompted]
```

---

## Autonomous mode (`--auto`)

Used by `/auto-apply` for high-volume daily runs. Skips the user interview entirely and produces a serviceable letter from JD + master_cv.json signal alone.

**When `--auto` is set:**

- **Skip Phase 4 (User Interview) entirely.** No AskUserQuestion calls.
- **Skip Phase 2 (Company Research) if WebSearch is unavailable or costly.** Use only the JD text and any obvious company signals (industry, stated mission, named products).
- **Story selection (deterministic):**
  - Pick the story whose tags best overlap the JD's top 5 keywords.
  - If multiple tie, prefer the most recent role-relevant story.
  - Skip the rotation check against last 5 letters (volume mode tolerates some repetition).
- **Opener strategy (default):** Direct Relevance. The safest choice and least likely to misfire without user signal.
- **"Why this company" line:** one sentence drawn from the company name + industry + any stated mission in the JD. If genuinely unknown, drop the line rather than fabricate.
- **"Why this candidate" paragraph:** one concrete example from the chosen story, sourced from master_cv.json.
- **Target length:** 220-300 words (slightly shorter than interactive default).
- **Tone:** professional, factual, no hedging. Same anti-LLM-fingerprint rules as Phase 6 (no em-dashes, no "leverage", no "passionate about", no "sitting at the intersection", no "most satisfying thing", British English).

**Output:** same artefacts as interactive mode (`cover-letter.md`, optional `cover-letter.pdf`). Log "auto mode" at the top of the .md file as a comment so the user can identify auto-generated letters in review.

**Quality bar for autonomous mode:** if the resulting letter feels generic / could apply to any company → that's acceptable for v1. The alternative is no letter and the role gets skipped. Volume > polish for the daily pipeline.

**Caller responsibility:** `/auto-apply` must check `cover_letter_required == true` before invoking. Don't generate optional letters in autonomous mode (per user policy).

---

## Input Handling

1. **URL provided**: Use WebFetch to retrieve job description (Playwright scraper fallback if needed)
2. **Notion URL**: Extract job details from Notion database
3. **Text provided**: Parse the pasted job description directly
4. **No argument**: Ask user to provide URL or paste job description

**French flag**: Use `--french` or request "en français" / "in French" to generate in formal French.

---

## Workflow Phases

### Phase 1: Job Analysis

Read and analyse the job description to extract:

- **Job title** - exact role name
- **Company** - employer name
- **Location** - office location and work mode (hybrid/remote/onsite)
- **Required skills** - must-haves from the posting
- **Key responsibilities** - what the role does day-to-day
- **Seniority level** - junior, mid, senior, lead, principal
- **Key themes** - recurring language and priorities to mirror

Create a structured summary before proceeding.

### Phase 2: Company Research

Use WebSearch to gather:

- **Mission & values** - what the company stands for
- **Recent news** - funding rounds, product launches, expansions
- **Engineering culture** - blog posts, tech talks, open source
- **Industry positioning** - competitive landscape, reputation
- **Team structure** - if discernible from posting or research

This is critical for writing a compelling "why this company" section.

### Phase 3: Context Loading

Read these files for personal context:

| File | Purpose |
|------|---------|
| `data/master_cv.json` | Source of experience, achievements, skills |
| `data/job_goals.json` | Career vision, priorities, motivation |
| `data/deep_experience.json` | Rich per-project evidence for story selection |
| `data/star_stories.json` | Pre-drafted STAR story bank |

Extract:
- Most relevant achievements for this role
- Quantified impact figures (%, £, team size)
- Career motivation aligned with role

**Story Rotation Check:**

Before selecting a primary story, read the last 5 cover letters in `cv/output/cover-letters/` to check which stories were recently featured. Then:
1. Select the most relevant story that was NOT used as the primary example in the last 3 letters
2. Priority: role-relevance > novelty > quantifiable outcome
3. If the most relevant story was used recently, find a different angle or secondary story

**Story Pool (build at runtime):**

Construct the candidate's story pool from `data/deep_experience.json` (project narratives, challenges, quantified results) and `data/star_stories.json` (pre-drafted STAR stories). Each entry becomes one candidate story: a one-line label plus its strongest quantified outcome. Do not use any story or metric that cannot be traced to those files or to `master_cv.json`.

### Phase 4: User Interview (CRITICAL)

**ALWAYS interview the user.** A cover letter that just echoes CV achievements is generic and inauthentic. The interview uncovers genuine motivations that make the letter compelling.

**Required questions (use AskUserQuestion):**

1. **Why this industry/type of role?**
   - What draws them to this field over alternatives?
   - What frustrates them about their current situation that this role solves?

2. **Why this specific company?**
   - Be honest—location, size, stage, reputation are all valid
   - Don't force generic "mission alignment" if it doesn't exist

3. **What's the most relevant thing you've done for THIS specific role?**
   - Not necessarily the proudest moment - the most directly applicable experience
   - What did you build, fix, or deliver that maps to what this role needs?
   - This becomes the evidence in the letter, not necessarily the opening

4. **What would you want to be doing day-to-day in this role, and how does your current work prepare you?**
   - Forward-looking: what excites them about the actual work
   - Reveals whether they understand what the job involves
   - Connects present capability to future contribution

**Interview flow:**
- Start with 2-3 multi-select questions to quickly gather context
- Follow up with 1-2 targeted questions based on answers
- Look for the emotional truth, not just the professional positioning

### Phase 5: Cover Letter Generation

**Core Principle: Authenticity Over Structure**

The cover letter should sound like a real person explaining why they want this job - not a marketing document. Use the interview answers to write in the user's authentic voice.

**Word count:** 250-400 words, British English by default.

#### Step 1: Select Opening Strategy

Choose the opener that best serves THIS application. Do not default to story-based openings.

| Strategy | When to use | Opens with... |
|----------|-------------|---------------|
| **Direct relevance** | Senior/specialist roles where experience match is the strongest signal | Strongest experience-to-role match, mirroring the job spec |
| **Company insight** | Startups, fintechs, or companies with a distinctive approach | Specific, researched observation about the company's challenge or product |
| **Career trajectory** | Career-pivot applications or roles in a new domain | Where you are now and where you want to go, framed as deliberate progression |
| **Evidence-first** | Quant roles, data-heavy positions, results-oriented cultures | A concrete, quantified result that proves capability |
| **Story opener** | Use sparingly (max 1 in every 4 letters). Only when the story is genuinely unique and directly relevant | A specific moment that reveals character or capability |

#### Step 2: Select Tone Register

Calibrate formality to the company type. Judge the type from the per-role company research in Phase 2, not from a memorised list:

| Company Type | Tone | Emphasis |
|---|---|---|
| Established finance / large corporate | Professional, precise | Quantified impact, domain expertise |
| Fintech / Scale-up | Direct, energetic | Product thinking, initiative |
| Tech company | Engineering-focused | Technical depth, building at scale |
| Consultancy | Client-focused | Stakeholder management, structured thinking |

#### Step 3: Anti-Repetition Check

Before writing, enforce variety:
1. Read the last 5 cover letters in `cv/output/cover-letters/`
2. Choose a DIFFERENT opening strategy from the last 2 letters
3. Rotate the primary story - do not reuse within the last 3 letters
4. If the best strategy was used recently, find the next-best fit

#### Step 4: Write the Letter

**Paragraph structure:**

1. **Hook + Relevance** (1 para) - Using the selected opener, establish why this role interests you AND why you're credible. Get to the point in 2 sentences max before expanding.
2. **Evidence** (1 para) - ONE concrete example proving your claim. The story lives HERE, serving the argument - not as a standalone anecdote.
3. **Why this company** (1 para) - Honest, specific reasons. Location, size, stage, and product are all valid. Don't force mission alignment that doesn't exist.
4. **Close** (2-3 sentences) - Brief credentials summary + call to action. Vary the closing format.

**Authenticity Principles:**

- Write in conversational first person - like talking to a smart friend
- Honest motivations (location, salary, growth) are more compelling than fake passion
- ONE story told well beats five bullet points
- Show personality through specificity, not through formulaic self-reflection. Concrete details about what you built reveal more than declarative statements about what you enjoy.
- Match your register to your audience. A quant fund wants precision; a startup wants energy. Neither wants the same letter everyone else sends.
- Metrics belong in the CV; the letter is about motivation and fit

**DO NOT:**
- List achievements from the CV (the recruiter has the CV)
- Use corporate speak: "leverage", "synergy", "passionate about"
- Force mission alignment that doesn't exist
- Open with "I am writing to apply for..." (boring and wastes space)
- Open with "The most satisfying thing...", "What I enjoy most...", or "The project I keep coming back to..." - these are formulaic patterns that signal AI authorship
- Default to a narrative/anecdote opening - choose the opener type that best serves THIS application
- Reuse the same primary story as any of the last 3 cover letters
- Use the same opening strategy as either of the last 2 cover letters
- Use "That intersection of X and Y is what draws me to Z" or "sitting at the intersection of" (LLM fingerprints)
- Always close with "More importantly, I bring the mindset of someone who..." - vary the closing
- Quantify everything - some things are better expressed as feelings
- Exceed 400 words
- Use em-dashes (-). This is a telltale sign of AI-generated text. Use commas, full stops, semicolons, or " - " (spaced hyphens) instead. Rewrite sentences to avoid needing dashes where possible.
- Sound like an LLM. Avoid formulaic structures, overly polished phrasing, and patterns that signal AI authorship. Vary sentence structure, use imperfect natural phrasing, and write like a real person drafting a letter - not like a language model completing a prompt.

### Phase 6: Output & Save

1. **Save markdown version** to: `cv/output/cover-letters/[company]-[role-slug].md`
2. **Generate PDF version** (see PDF Generation below)
3. **Display formatted version** in terminal
4. **Highlight** which experiences were emphasised
5. **Note any gaps** or areas user should verify

---

## PDF Generation

After saving the markdown, convert to PDF using LaTeX for professional formatting.

### Step 1: Create LaTeX File

Create a `.tex` file at `cv/output/cover-letters/[company]-[role-slug].tex`:

```latex
\documentclass[11pt,a4paper]{article}
\usepackage[margin=2.5cm]{geometry}
\usepackage{parskip}
\usepackage{hyperref}
\usepackage{eurosym}

\pagestyle{empty}

\begin{document}

\begin{flushright}
\today
\end{flushright}

\vspace{1em}

Dear Hiring Manager,

[COVER LETTER BODY - convert markdown paragraphs to LaTeX]

Best regards,\\
[CANDIDATE NAME - read from master_cv.json personal.name]

\end{document}
```

**Formatting notes:**
- Replace any `%` with `\%` (LaTeX escaping)
- Replace any `&` with `\&`
- Replace any `£` with `\pounds{}`
- Replace any `€` with `\euro{}`
- Never use em-dashes (—) in the text. Use commas, semicolons, or " - " (spaced hyphens) instead. In LaTeX, use ` -- ` for any remaining dashes.
- Convert **bold** to `\textbf{}`
- Preserve paragraph breaks with blank lines

### Step 2: Build PDF

From the repo root:

```bash
cd cv && \
export PATH="/Library/TeX/texbin:$PATH" && \
pdflatex -output-directory=output/cover-letters output/cover-letters/[filename].tex
```

### Step 3: Clean Up Build Artifacts

```bash
cd cv/output/cover-letters && \
rm -f [filename].aux [filename].log [filename].out
```

Keep only the `.md`, `.tex`, and `.pdf` files.

---

## French Language Support

**Trigger:** `--french` flag or explicit request ("en français", "in French")

When writing in French:

- Use formal French (vouvoiement - "vous" not "tu")
- Follow French business letter conventions
- Slightly more formal tone than English equivalent
- Appropriate greetings ("Madame, Monsieur,") and closings
- Keep structure similar but adapt phrasing

**File naming:** Save as `[company]-[role-slug]-fr.md`, `.tex`, and `.pdf`

---

## Output Location & Naming

**File Structure:**
```
cv/output/
├── tailored/              # Final CVs
├── tailored-build/        # CV source files
└── cover-letters/         # Cover letters (markdown, LaTeX source, and PDF)
    ├── [company]-[role-slug].md
    ├── [company]-[role-slug].tex
    └── [company]-[role-slug].pdf
```

**Naming convention:** `[company]-[role-slug]`
- Lowercase, hyphens for spaces, no special characters
- Examples: `citadel-quant-researcher`, `anthropic-ml-engineer`
- French: `citadel-quant-researcher-fr`

**Output files:**
- `.md` - Markdown source (for editing/review)
- `.tex` - LaTeX source (for PDF generation)
- `.pdf` - Final PDF (for applications)

---

## Response Format

After generating the cover letter, report:

1. **Company researched**: Key findings used
2. **Key tailoring decisions**: What was emphasised
3. **Achievement featured**: The main story told
4. **Word count**: Should be 250-400
5. **Output location**: Paths to `.md` and `.pdf` files
6. **Gaps noted**: Any areas to verify or clarify

---

## Example Openings by Strategy

Each example shows the first paragraph only, demonstrating how different openers serve different applications. These use the fictional "Alex Example" persona; the real letters must draw every fact from the candidate's own data files.

### Example A: Direct Relevance (Operations Analyst at Established Firm)

```markdown
Dear Hiring Manager,

Your posting asks for someone who can build reporting pipelines and work directly with operations leads on process analytics. That is precisely what I have spent the last three years doing. At ExampleCorp, I built the SQL and Python reporting stack the operations team runs on, automated the month-end reconciliation that used to take two days, and became the person team leads called when their numbers didn't tie out.
```

**Why this works:** Mirrors the job spec in the first sentence, proves the claim with specifics immediately. No preamble. A results-oriented reviewer scanning quickly sees direct relevance.

### Example B: Company Insight (Analyst at Fintech)

```markdown
Dear Hiring Manager,

[Company] processes millions of SME transactions and has built its competitive advantage on making business banking feel effortless. That kind of product, where the operational complexity is invisible to the user, is where I want to work. I have spent the last year building internal tools that share that philosophy: a self-serve reporting layer that replaced a weekly analyst queue, and a data-quality monitor that catches issues before customers see them.
```

**Why this works:** Opens with a researched fact about the company that shows genuine understanding. Positions the candidate's work as evidence of shared product values, not just technical skills.

### Example C: Career Trajectory (Strategy Role at Growth Company)

```markdown
Dear Hiring Manager,

I have spent three years at ExampleCorp translating messy operational data into decisions that leadership actually acts on. I led the migration of our core reporting from spreadsheets to a governed warehouse, a project that had stalled twice before, largely because no one had bridged the gap between what the engineers built and what the business needed. That experience, making technical work land with non-technical stakeholders, is exactly the work I want to do full-time.
```

**Why this works:** Frames current experience as deliberate preparation for the target role. Honest about wanting career change without being negative. The story serves the trajectory argument rather than standing alone as an anecdote.

---

## WebFetch Limitations & Playwright Fallback

WebFetch may fail on JavaScript-heavy job sites (Lever.co, Greenhouse, Databricks).

**When WebFetch fails, use the playwright-cli skill** to open the posting in a browser session and extract the page text (for example `playwright-cli open "<job-url>"` then snapshot/read the description region). Only ask the user to paste the job description as a last resort.

---

## Files Referenced

| File | Purpose |
|------|---------|
| `data/master_cv.json` | Source of experience and achievements |
| `data/job_goals.json` | Career vision, motivation, priorities |
| `cv/output/cover-letters/` | Output directory |
