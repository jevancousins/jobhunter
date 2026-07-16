---
name: interview-prep
description: Create tailored interview preparation documents for specific job roles. Use when preparing for an upcoming interview, generating STAR-style responses, or practising common interview questions. Takes job description and role details as input, produces structured prep document with tailored responses, technical talking points, and questions to ask.
argument-hint: "[company-role or 'mock']"
---

# Interview Prep Skill

Generate a comprehensive, tailored interview preparation document — or run a mock interview session.

## Usage

```
/interview-prep                          # Interactive — prompts for details
/interview-prep Rokos Data Specialist    # Quick start with company + role
/interview-prep mock                     # Mock interview mode (requires existing prep doc)
```

---

## Input Handling

1. **Company + role provided**: Start Phase 1 with provided context
2. **No argument**: Ask user for company, role, and interview date
3. **"mock"**: Enter mock interview mode (see Phase 6)

---

## Workflow Phases

### Phase 1: Gather Inputs

Collect the following. Ask the user for anything not provided:

| Input | Required | Source |
|-------|----------|--------|
| Job title | Yes | User |
| Company | Yes | User |
| Job description | Yes | User paste, URL (WebFetch), or Notion (MCP) |
| Interview date | Yes | User |
| Interview type | Yes | HR / HM / Culture / Technical / Panel |
| Interviewer names | If known | User |
| Interviewer LinkedIn URLs | If known | User |
| Specific concerns | Optional | User |
| Areas to emphasise | Optional | User |

**If the job exists in Notion**, fetch the JD and score from there using `mcp__notion__notion-fetch`.

#### Check the Interview Prep DB

Query the Interview Prep DB (data source ID from `data/notion_ids.json`, key `interview_prep_db`; if absent, offer to create the database and record its ID there) for an existing entry matching the company name. If one exists, read it to pull in any prior Company Research, Interviewers, Likely Questions, My Talking Points, and Notes. Use these as a starting point rather than researching from scratch; update and extend during Phases 2-3 rather than duplicating.

If no entry exists, create one at the start of the workflow using the Notion MCP create-pages tool with parent `{"data_source_id": "<interview_prep_db from data/notion_ids.json>"}`. Set:
- **Title**: "[Company] : [Role]"
- **Interview Date**: the interview date
- **Job**: relation to the Jobs DB entry if one exists

This entry will be updated progressively through the workflow.

Produce a compact summary:
- **Role**: Title @ Company
- **Interview**: Type, date, interviewer(s)
- **Key requirements**: 5-8 bullet points from JD
- **Interview focus**: What this interview type typically assesses

---

### Phase 2: Research

Run research in parallel where possible:

#### Company Research
Use WebSearch to find:
- Company overview (what they do, size, funding/AUM, recent news)
- Culture and values (Glassdoor, company careers page)
- Recent developments (last 6 months of news)
- Engineering/data blog if applicable
- Industry context (competitors, market position)
- Tech stack if relevant (job postings, engineering blog, StackShare)

#### Conversation Starter Research
From the company research above, identify **one specific recent news item, product launch, blog post, or social media announcement** (ideally from the last 3 months) that:
- Connects naturally to the candidate's experience or the role
- Is specific enough to show genuine awareness (not a generic fact)
- Can be woven into conversation organically (e.g. during "why this company?", a technical discussion, or as a closing question hook)

Draft a natural one-sentence reference the candidate can use. Not "I read that you..." but a way to demonstrate awareness while connecting it to personal experience (e.g. "I noticed you recently expanded into a new data domain; that's interesting because my current team hit exactly that coverage gap", adapted to the candidate's real experience from deep_experience.json).

#### Interviewer Research (if names provided)
Use WebSearch to find:
- Career history (LinkedIn summary, previous companies)
- Shared connections with the candidate (especially shared past employers)
- Publications, talks, or public profiles
- Current role and likely focus areas
- **Notable career achievements or transitions** (e.g. "built the data platform from scratch", "led migration from on-prem to cloud", "grew the team from 3 to 20")
- **Recent LinkedIn posts, articles, or conference talks** with specific topics
- **Opinions or projects that overlap with the candidate's experience** (shared technologies, similar problems solved, common industry challenges)

For each interviewer, identify:
1. One aspect of their career that would make a good conversation topic
2. One question that would prompt them to talk about a career success or something they're clearly passionate about
3. Any overlap with the candidate's background that could create natural rapport

#### Role Research
- What this role typically looks like at this type of company
- Common interview questions for this role type
- Technical expectations for the seniority level

#### Question Bank and Skills Tracker Consultation
1. Query the **Question Bank** (data source ID from `data/notion_ids.json`, key `question_bank_db`; skip this step gracefully if not configured) for questions tagged with the relevant Role Type and Interview Stage. Prioritise questions with high "Times Asked" as likely to appear. For any question the candidate scored below 7 in a previous debrief, flag it as a rehearsal priority.
2. Query the **Interview Skills Tracker** (data source ID from `data/notion_ids.json`, key `skills_tracker_db`; skip gracefully if not configured) for active entries at P0 or P1 priority. Cross-reference against JD requirements. If a known weakness overlaps with a JD requirement, escalate it in the prep document's "Weak Points" section with the specific action from the tracker.

**Output:** Structured research summary for use in Phase 3.

---

### Phase 3: Strategy

#### Load Source Material
1. Read `data/master_cv.json` for experience and skills
2. Read `data/job_goals.json` for "why this role" framing
3. Read `data/star_stories.json` for the STAR story bank
4. Read `data/interview_frameworks.json` for the matching interview type template
5. Read `data/deep_experience.json` for deep project narratives with architecture decisions, trade-offs, and challenges
6. Read `data/technical_inventory.json` for confidence levels per skill (can_explain_deeply / can_discuss / surface_only / gap)

#### Gap Analysis (CRITICAL)
Cross-reference JD requirements against `technical_inventory.json`:
- For each required skill, check the candidate's confidence level
- **can_explain_deeply**: Prepare to lead with this; it is a strength
- **can_discuss**: Prepare talking points but expect follow-ups may be tricky
- **surface_only**: Prepare a framing that is honest ("I've worked with X at a conceptual level but my hands-on experience is in Y, which is closely related")
- **gap**: Prepare a defence ("I haven't used X directly, but I've done Y which shares the same principles, and I'm actively learning X through Z")

Also check the Skills Tracker results from Phase 2: if any P0/P1 weakness overlaps with a JD requirement, flag it prominently.

List the gaps explicitly in the prep document so the candidate knows where they are vulnerable.

#### Select Deep Experience Stories
From `deep_experience.json`, select projects based on JD relevance. For each selected project, note:
- The architecture decisions and WHY (not just WHAT)
- Specific challenges and how they were solved
- What went wrong and what was learned
- Technical depth available (can the candidate go deep if probed?)

Use the `interview_angles` field in each project to select the right framing for this specific role type.

#### Define Narrative Angle
One sentence connecting the candidate to this specific role. Pattern:
> "I bring [specific relevant experience] combined with [technical skills] and a track record of [key achievement relevant to this role]"

#### Select STAR Stories
From `data/star_stories.json`, select stories based on:
- JD requirements → match to story themes
- Interview type → use framework's `star_themes_to_prioritise`
- Interviewer background → stories that resonate with their experience
- Typically 6-10 stories for a Hiring Manager interview, 2-4 for HR screen

#### Identify Weak Points
Cross-reference JD requirements against `master_cv.json` and `technical_inventory.json`:
- Skills mentioned in JD but not in CV, or at `surface_only`/`gap` level
- Experience gaps (years, seniority, specific domains)
- Education requirements not met (BSc vs Master's: prepare the standard defence)
- Any P0/P1 items from the Skills Tracker that overlap with JD requirements
- For each weak point, prepare an honest defence using deep_experience.json evidence where possible

---

### Phase 4: Generate Prep Document

Create a markdown document with the following sections:

```markdown
# Interview Prep: [Company] — [Role]

**Date:** [date and time]
**Format:** [Virtual/In-person, platform]
**Interviewers:** [names and titles]
**Interview type:** [type]

## 1. Company Brief
[Overview, recent developments, why this matters for the role]

## 2. Conversation Starter
**News item:** [specific recent event/announcement/post from the last 3 months]
**Natural reference:** [one sentence connecting it to the candidate's experience]
**When to use:** [e.g. during "why this company?", a technical discussion, or as a closing question hook]

## 3. Interviewer Profiles
[For each interviewer:]
### [Name] — [Title]
- **Background:** [career history, previous companies, current focus]
- **What they care about:** [inferred priorities from their background]
- **Shared connections:** [common past employers, mutual contacts, shared interests]
- **Notable achievement:** [a specific career success or transition worth noting]
- **Recent activity:** [LinkedIn posts, articles, talks, if any]

## 4. Narrative Angle
[One-sentence positioning statement + 3-4 key themes to thread throughout]

## 5. "Tell Me About Yourself" (90 seconds)
[Tailored pitch. Must be 60-90 seconds when read aloud. Opening hook, key achievements mapped to role, closing with why this company.]

## 6. Gap Analysis
[Table: JD requirement -> candidate confidence level -> preparation strategy]
| JD Requirement | Confidence | Strategy |
|---------------|------------|----------|
| Python | can_explain_deeply | Lead with the strongest matching project from deep_experience.json |
| Spark | gap | Frame via the nearest adjacent technology actually used, acknowledge gap honestly |

**Known weaknesses from Skills Tracker:**
[Any P0/P1 items that overlap with JD requirements, with the specific action from the tracker]

## 7. Deep Experience Talking Points
[For each relevant project from deep_experience.json:]
### [Project Name]
- **Lead with:** [1-2 sentence hook]
- **Architecture:** [Key components and WHY]
- **Challenge:** [Most relevant challenge for this role]
- **Result:** [Quantified outcome]
- **If probed deeper:** [What you can/can't go into; be honest about limits]

## 8. STAR Responses
[6-10 stories from star_stories.json, each with:]
- Question it answers
- S/T/A/R (adapted for this company)
- **Deep follow-up ready?** [Yes/Partial/No, from technical_inventory]

## 9. Likely Questions from Question Bank
[Questions from the Question Bank that match this Role Type and Interview Stage, ordered by Times Asked. For any where the candidate previously scored below 7, mark as a rehearsal priority.]

## 10. Questions to Ask
[Structured per interviewer. Each question grounded in research, not generic curiosity.]

### [Interviewer Name] — [Title]
**Connection angle:** [What you have in common or find genuinely interesting about their background]

1. [Question grounded in their career/background, designed to prompt them to talk about a success or something they are passionate about]
   *Why this works:* [What it signals about your research + what you would learn]
2. [Question grounded in a recent post/talk/project of theirs]
   *Why this works:* [...]
3. [Role/team question only they can answer given their position]

### General (any interviewer)
[2-3 fallback questions from the interview framework that show genuine interest in the role/team]

## 11. Potential Weak Points & Defences
[Each weakness with honest, prepared response. Include deep_experience.json evidence where possible.]

## 12. Logistics
[Practical notes: arrival time, dress code, materials to bring, platform/link if virtual]
```

#### Factual Verification (CRITICAL)
Before finalising, cross-reference ALL claims against `master_cv.json`:
- Experience durations and dates
- Specific metrics (savings figures, platform sizes, team counts)
- Skills and technologies actually used
- Language levels exactly as recorded in master_cv.json languages (never upgrade a proficiency)
- Total experience matches the employment dates in master_cv.json

---

### Phase 5: Output

1. Save to `interview-prep/[company]-[role]-[date].md`
   - Company and role in lowercase, hyphenated
   - Date in YYYY-MM-DD format
2. **Update the Interview Prep DB entry** (created in Phase 1) using the Notion MCP update-page tool:
   - **Company Research**: the company brief from section 1 of the prep doc
   - **Interviewers**: names, titles, and key notes
   - **Likely Questions**: the most likely questions based on research and interview type
   - **My Talking Points**: narrative angle and key themes
   - **Notes**: any user-provided concerns or special context
3. Optionally update the Notion job entry with "Interview Prep" status using the Notion MCP update-page tool
4. Print a summary of the prep document to the user with key highlights

---

### Phase 6: Mock Interview Mode

**Trigger:** `/interview-prep mock`

#### Setup
1. Check for existing prep documents in `interview-prep/`
2. Ask user which prep to load (or auto-detect if only one recent one)
3. Read the prep document
4. Ask user which interview type to simulate (HR / HM / Technical)
5. **If interviewer profiles exist in the prep doc**, offer **persona mode**: adopt the interviewer's likely style and focus based on their background. For example, a CTO would probe architecture depth and system design trade-offs; a Head of Data Quality would probe governance and SLAs; a VP of Engineering would focus on team dynamics and delivery. If the user declines, use a generic interviewer persona.

#### Mock Interview Flow
1. **Claude plays the interviewer** — uses the prep document to ask realistic questions
2. **In persona mode**, adopt the interviewer's communication style and focus areas based on their profile. Ask questions they would plausibly ask given their background. Reference their domain naturally (e.g. a data engineering lead would ask about pipeline architecture, not about front-end design).
3. **Ask 5-8 questions** drawn from:
   - The prep document's STAR questions and deep experience talking points
   - The Question Bank (prioritise high-frequency questions for this role type)
   - The interview framework's typical questions
   - Follow-up questions based on user's answers
   - In persona mode: questions specific to what the interviewer cares about
4. **After each answer, provide feedback on:**
   - Clarity and structure (did they use STAR format?)
   - Specificity (did they include metrics and concrete details?)
   - Relevance (did they connect the answer to the role?)
   - Follow-up readiness (would a follow-up question expose gaps?)
   - Depth (could they go deeper if probed, based on technical_inventory?)
   - Length (too short, just right, too long?)
5. **After all questions, provide overall assessment:**
   - Strongest answers
   - Areas to improve
   - Specific suggestions for each weak answer
   - Overall interview readiness score (1-10)
   - Recommend drill mode for areas at `can_discuss` or `surface_only` level

#### Mock Interview Guidelines
- Be realistic — ask the hard questions, not just softballs
- Push back on vague answers with follow-ups
- If the candidate claims something at `surface_only` level in their technical_inventory, probe deeper to test
- Note when the candidate uses filler or hedging language
- Praise specific, metrics-backed answers
- Stay in character as interviewer until the mock is complete

---

## Notion Database IDs

Database and data source IDs are per-user. The Jobs DB ID comes from `NOTION_JOBS_DB_ID` in `.env`; the optional prep databases are recorded in `data/notion_ids.json` (created during onboarding or on first use of this skill) under the keys:

- `interview_prep_db` (persistent prep record per company/role)
- `question_bank_db` (questions from past interviews)
- `skills_tracker_db` (improvement areas from debriefs)

If a key is missing, offer to create the corresponding database under the user's JobHunter Notion page and record its data source ID, or skip that step gracefully.

## Data Sources

| File | Purpose |
|------|---------|
| `data/master_cv.json` | Experience, skills, education, projects |
| `data/job_goals.json` | Career goals, target roles, "why this role" framing |
| `data/star_stories.json` | STAR story bank with pre-drafted stories |
| `data/interview_frameworks.json` | Interview type templates and question banks |
| `data/deep_experience.json` | Deep project narratives, architecture decisions, trade-offs, challenges |
| `data/technical_inventory.json` | Confidence levels for all skills with evidence links |
| Interview Prep DB (Notion) | Persistent record of prep sessions per company/role |
| Jobs DB (Notion) | Job entries with JD, score, and status |
| Question Bank (Notion) | Questions from past interviews with frequency and best answer frameworks |
| Skills Tracker (Notion) | Improvement areas from debriefs with priority and actions |

---

## Quality Checklist

Before delivering the prep document, verify:

- [ ] All facts cross-referenced against master_cv.json
- [ ] "Tell me about yourself" is 60-90 seconds when read aloud
- [ ] STAR stories have specific metrics, not vague claims
- [ ] Gap analysis table covers all JD requirements against technical_inventory
- [ ] Deep experience talking points include honest "if probed deeper" assessment
- [ ] Conversation starter is specific, recent (last 3 months), and naturally connected to candidate experience
- [ ] Questions to ask are per-interviewer, grounded in research, not generic curiosity
- [ ] At least one question per interviewer is designed to prompt them to discuss a career success or passion
- [ ] Question Bank high-frequency questions are flagged as likely to appear
- [ ] Skills Tracker P0/P1 items are cross-referenced against JD and escalated if overlapping
- [ ] Weak points have prepared, honest defences (not dismissals)
- [ ] Language proficiencies match master_cv.json languages exactly (never upgraded)
- [ ] Total experience matches the employment dates in master_cv.json
- [ ] No embellished or invented claims
