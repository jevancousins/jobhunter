---
name: tailor-cv-light
description: Locked "Light" tailoring — Profile rewrite + Skills reorder/swap + ≤2 bullet swaps, page-fill iterated to FULL. The cheap, surgical alternative to /tailor-cv-full. Used by /auto-apply per role.
argument-hint: "<variant> <jd-path-or-text> [<output-dir>]"
---

# Tailor CV (Light, locked definition)

This skill applies the locked Light methodology: matched variant + four surgical modifications, page-fill iterated to FULL. Cost target 7-11K tokens, 90-150s wall-clock, 2-3 iterations.

The methodology was locked after a controlled tailoring experiment ("Phase 0d") that compared modification strategies; this skill is the operational implementation of the winning definition.

## CV backend

Read `cv.backend` from `data/search_config.json` first; the four modifications are the same, the medium differs:

- **`latex`** (the documented flow below): edit the variant `.tex`, compile with pdflatex, iterate the page-fill gates to FULL.
- **`docx`**: copy `cv/master.docx` to `<output-dir>/cv.docx` and apply the same four modifications with python-docx via Bash (rewrite the profile paragraph, reorder/rename the skills lines, swap up to 2 bullet paragraphs; never touch the master file). Skip the pdflatex page-fill gates; instead, if `soffice` is on PATH, convert to `cv.pdf` (`soffice --headless --convert-to pdf`) and check with PyMuPDF that the page count matches the master's. Factual verification (Phase 4) applies in full. Print the same `LIGHT_TAILOR_OK` / `LIGHT_TAILOR_FAIL` contract.
- **`pdf`**: tailoring is not possible on a fixed PDF. Print `LIGHT_TAILOR_FAIL cv-backend-pdf-no-tailoring` immediately; the caller falls back to the master PDF.

## Inputs

- **`<variant>`** — variant name from `cv/variants/seniority_caps.json` (e.g. `ai-engineer`, `forward-deployed-engineer`). The variant `.tex` at `cv/variants/<variant>.tex` is the starting point.
- **`<jd-path-or-text>`** — either a path to a JD `.md` file or raw JD text inline.
- **`<output-dir>`** (optional, default `cv/output/tailored/`) — where to write the tailored `.tex` and `.pdf`. When invoked by /auto-apply, the orchestrator passes `applications/<job-id>/` so all per-application artefacts live together.

## Source-of-truth files

- `data/master_cv.json` — facts (years, titles, dates, modules, languages) and the canonical bullet pool for swaps.
- `cv/variants/<variant>.tex` — visual scaffolding starting point.
- `cv/variants/seniority_caps.json` — per-variant `max_years` cap. Profile must respect this cap.
- `cv/CLAUDE.md` — Profile rules (Lead/Evidence/Close, banned phrases, never name target company).

## The four modifications (and only these four)

### 1. Profile rewrite (Lead / Evidence / Close)

Per [cv/CLAUDE.md](../../../cv/CLAUDE.md): 40-110 words, 3-4 sentences, no first-person, no banned phrases, never name the target company.

- **Lead:** professional identity matching JD title + seniority. Capped by `seniority_caps.json[<variant>].max_years` — never claim more years than the cap allows.
- **Evidence:** 1-2 quantified achievements that hit the JD's headline priorities. Use JD-named technologies where they appear in `master_cv.json`.
- **Close:** value-framed, role-and-context specific. Swap-test: "would this close still make sense for a different opening?" If yes, rewrite. NEVER name the target company.

### 2. Skills section reorder + rename

Reorder the Skills categories so the JD-priority category comes first (e.g. AI/ML first for AI Engineer roles; Quant & Analytics first for Quant Researcher). May rename categories to mirror the JD's vocabulary if the new label still accurately covers the same items (e.g. "Programming" → "Languages" if JD uses that wording).

### 3. Skills keyword swap (≤3 additions)

Add up to 3 JD-named technologies that exist in `master_cv.json`. **Hard rule:** do NOT add a tech that doesn't appear in master_cv.json — that would be fabrication. If the JD demands a tech not in master_cv.json, leave it out silently (the recruiter will see the absence; better than a fake claim).

Equivalent-tech substitution is OK only when the equivalence is documented in `data/deep_experience.json` and the substitute name (not the JD name) is what gets added. Examples of the pattern: Snowflake → Databricks, Airflow → Power Automate. Substitutions must be grounded in the candidate's actual adjacent experience from `master_cv.json` / `deep_experience.json` — never inferred from the role alone.

### 4. Primary-employer bullet swap (≤2 swaps)

Swap at most 2 bullets in the primary employer's `\cventry` if the JD names a responsibility that the variant's default bullets don't cover. Each swap must:
- Pull the replacement bullet from `master_cv.json` `experience.<primary_employer_key>.bullets[]`.
- Be net-neutral or net-positive on the CV's overall thesis (do NOT drop a strong headline bullet to add a generic admin bullet — earlier experiments found this regressed quality).
- Preserve the primary-employer bullet count (the variant's count must stay within `check_cv_format.py`'s 5-8 cap).

If the variant already covers the JD's named responsibilities, **make zero bullet swaps.** This is the common case.

## What this skill does NOT do

| Excluded | Reason |
|---|---|
| Project re-selection | Variants curate per archetype; earlier experiments showed 0 to +0.2 lift, not worth the cost |
| New bullets / new cventries | Out of scope (factual risk) |
| Education module changes | Locked to `master_cv.json` per fact-check rules |
| Cover-letter style narrative | This is a CV; Profile carries the role-fit framing |
| Action-verb uniqueness rewrite | The variants are already deduped; trust the baseline |
| Naming the target company in Profile | Banned (rare exceptions only when candidate has genuine prior connection) |

## Tailoring intelligence (read-only context)

Before starting modifications, check if `data/apply-intelligence.json` exists. If it does, read the `tailoring_insights` and `variant_outcomes` sections. Use this data as soft guidance when making tailoring decisions:

- **Variant outcomes**: if the current variant has a high response rate (>15%), prefer conservative modifications (fewer bullet swaps, less aggressive skill additions). If it has a low response rate (<5% with 5+ resolved), be more willing to differentiate from the template.
- **Tailoring insights**: the `bullet_swap_correlation` and `skills_added_correlation` fields (when populated by the retrospective) indicate which specific modifications correlate with positive outcomes for this variant family. Prefer modifications that match patterns seen in successful applications.
- **Role family patterns**: if `variant_boosts` lists a preferred variant for this role type with better outcomes, note that the variant selection already handled the swap upstream; your job is to tailor the chosen variant well, not second-guess the variant choice.

This section is purely informational. It does NOT change the four-modification structure, the iteration discipline, or any hard rules. If the intelligence file is missing or empty, proceed normally with no change to behaviour.

## Workflow

### Step 1: Setup

1. Resolve `<jd-path-or-text>`: if it looks like a path that exists, read the file; otherwise treat as inline text.
2. Read `cv/variants/<variant>.tex` (starting point) and the variant's `seniority_caps.json` cap.
3. Read `data/master_cv.json` (full file — it fits easily in context).
4. Skim the JD end-to-end and pull a brief mental list of: JD title + seniority, top 3-5 technologies named, top 3 responsibilities. No need to persist this; Light is in-context.

### Step 2: Apply the four modifications

In order, edit `<output-dir>/cv.tex` (start by copying `cv/variants/<variant>.tex` there):

1. Rewrite the `\cvprofile{...}` block per Lead/Evidence/Close.
2. Reorder the `\cvskillcat` lines and rename categories if needed.
3. Add up to 3 JD-named techs to the appropriate `\cvskillcat` lines (only if present in master_cv.json).
4. Swap ≤2 bullets in the primary employer's `\cventry` block if needed (most roles: zero swaps).

### Step 3: Compile + verify

```bash
cd cv && export PATH="/Library/TeX/texbin:$PATH" && \
  pdflatex -interaction=nonstopmode -output-directory=<abs-output-dir> <abs-output-dir>/cv.tex
```

Then run the deterministic gates:

```bash
python scripts/check_page_fill.py <output-dir>/cv.pdf      # must return FULL (exit 0)
python scripts/check_cv_format.py <output-dir>/cv.tex      # must pass
python scripts/check_cv_facts.py <output-dir>/cv.tex       # must pass
```

`check_page_fill.py` exit codes:

| Exit | Verdict | Meaning |
|---|---|---|
| `0` | `FULL` | Page is full (gap < 10pt) AND no short lines. Pass. |
| `1` | `UNDERFILLED` | Vertical gap > 10pt. Stdout reports `~N lines to fill` (gap ÷ 12). |
| `2` | `OVERFLOW` | Content spills beyond one page. Drop a bullet or trim Profile. |
| `3` | `SHORT_LINES_DETECTED` | Vertically FULL but at least one wrap tail < 50% line width. Either extend (preferred when FULL) or trim the offending bullet. |

### Step 4: Plan edits deterministically, then iterate to FULL

**Plan before compiling.** Each LaTeX element has a known, measured line cost — you can compute the net line-change of any edit set before running `pdflatex`. Iterating blindly (edit → compile → re-check → edit again) is an anti-pattern that wastes Opus tokens and rarely converges in fewer than 5 cycles. With deterministic planning the typical good run is 1-2 compiles total, even on tricky variants.

#### Measured line heights (cv.cls, A4, 9pt body)

| Element | Height per line | Notes |
|---|---|---|
| Profile line (wrapped prose) | ~12pt | Each line in `\cvprofile{}` |
| Skills category line | ~12-13pt | Per `\cvskillcat{Cat}{...}` row |
| Section header `\section{X}` | ~14pt | Bold ALL-CAPS, e.g. EXPERIENCE |
| Cventry header (company + title row) | ~20pt | Two lines: company + dates / title + location |
| Bullet, 1 line, no wrap | ~12pt | `\cvbullet{...}` fitting on one line |
| Bullet wrap continuation | +~12pt per line | Wrapped bullet costs 12pt × wrap count |
| Education modules line | ~12pt | Each line in `\cveducation{}` body |
| Project line (entries separated by `\\`) | ~12pt | One single-line project entry |
| Spacing between cventries | ~6-8pt | Implicit padding |

Page content area: ~813pt. `check_page_fill.py` returns FULL when gap < 10pt. The "~N lines to fill" figure in UNDERFILLED output is `gap // 12`.

#### Net line cost of common edits

| Edit | Net cost (lines) | When to use |
|---|---|---|
| Add 1-line bullet to existing cventry | +1 | Most cost-effective +1 |
| Extend a bullet so it wraps to one more line | +1 | Use when SHORT_LINES wrap tail needs to be pushed past 50% |
| Add a new project line | +1 | Cheap +1; works for any role |
| Split a wrapped bullet into 2 separate bullets | +0 to +1 | If original was 2-line wrap, splitting yields 2 single-line bullets = +0; if original was 1 line, splitting always adds +1 |
| Add a new cventry with 1 bullet | +3 | Only when 3+ lines short; usually too expensive |
| Drop a 1-line bullet | -1 | Cheapest way to free space |
| Trim a wrapping bullet to fit on 1 line | -1 | Fixes SHORT_LINES, costs 1 line |
| Trim Profile content (removes 1 wrap line) | -1 | Removes one wrapped Profile line |
| Add a Profile sentence | +1 to +2 | Length-dependent; Profile cap is 4 sentences / 130 words |

#### Fixing SHORT_LINES (wrap tail < 50%)

A wrap tail below 50% means the bullet is N+ε lines long with an orphaned tail. Two fixes:

1. **Trim** the bullet so the entire content fits on one fewer line. Net: **-1 line** (page becomes more underfilled).
2. **Extend** the bullet with substantive factual content so the wrap tail is pushed past 50%. Net: **0 lines** (same wrap count, longer tail).

When the page is already FULL → prefer **extend**. When the page is OVERFLOW → prefer **trim**. To estimate words needed: if current tail is X% with N words, push to ~50% by adding ≈ N(0.5/X − 1) more words. (e.g. 30% tail with 5 words → ≈ 3 more words.)

#### Iteration discipline (the loop)

For every compile after the first:

1. **State the current state**: FULL / SHORT_LINES / UNDERFILLED / OVERFLOW, gap in pt, and any wrap tails flagged with their %.
2. **Plan the full edit set**: list each edit and its predicted net line change, sum to a total. Goal: end at FULL with no SHORT_LINES.
3. **Apply all planned edits in one pass, then compile once.** Do NOT compile between individual edits within the same plan — that's the anti-pattern.
4. **Re-check.** Iterate only if your prediction was off. A correct prediction should land within ±1 line.
5. If after a planned edit set the page is still off, the gap is usually small (1-2 lines). One more planned edit set should converge.

#### Iteration ceilings (generous; intended to catch only true pathology)

- Maximum **8 total `pdflatex` compilations** per skill invocation. With deterministic planning, 1-3 compiles is typical; 8 is the upper bound for unusual variants.
- Maximum **6 page-fill adjustment cycles**. Same caveat: each cycle is a planned edit set + one compile, not a single tweak.
- If a single element has been edited and re-edited **3 times in different directions** (e.g. extended → trimmed → re-extended) and is still flagged, switch to a different lever (different bullet, different section). Don't keep poking the same element.
- Hit-the-ceiling outcome: emit `LIGHT_TAILOR_FAIL <variant> reason=iteration-ceiling-hit` and exit code 1. The orchestrator's role-tailorer wrapper will translate this into a `FALLBACK` line and the application still ships with the template-only PDF.

The ceilings above exist so a genuinely pathological case can't run unbounded — they are NOT a budget you should aim to hit. Plan first, compile once per planned edit set, and most roles should land in 1-3 compiles.

#### Anti-patterns to avoid

- **Edit-then-compile-then-edit single-tweak loops.** Plan all edits in the set first.
- **Padding the Profile to fill space.** Profile has hard caps; add lines elsewhere instead.
- **Adding a new cventry to fix a 1-line gap.** Too expensive (+3 lines); use a single bullet instead.
- **Extending a wrap tail AND adding a new bullet simultaneously without re-summing.** Predict each edit's effect first.
- **Trimming a wrap to 1 line without compensating elsewhere.** Leaves the page UNDERFILLED.

#### Notes that have caught past sessions out

- Languages line is exempt from SHORT_LINES (always flagged at ~37% but per cv/CLAUDE.md it's not a real issue).
- `€` renders as `C` in pdftotext output (e.g. `€5M` appears as `C5M`) — it's correctly rendered as € in the actual PDF.
- "Pages: 1 | gap: -2.1pt" means content slightly overshoots into the bottom margin but is still 1 page. That is still FULL (gap < 10pt threshold).

### Step 5: Format / facts violations

If `check_cv_format.py` or `check_cv_facts.py` fail → fix the specific violation, recompile. Do NOT make additional content changes beyond what the violation requires.

## Output contract

After all gates pass, the output directory contains:
- `cv.tex` — the tailored source
- `cv.pdf` — the compiled PDF (pdflatex build artefact). The calling agent (role-tailorer or orchestrator) is responsible for renaming this to the employer-facing filename (`<employer_filename_base> - <Company> <Title>.pdf`, where `employer_filename_base` comes from `data/search_config.json` `cv.employer_filename_base`) before `mark-ready`.
- `cv.aux`, `cv.log`, `cv.out` — LaTeX build artefacts (safe to leave; .gitignored at the project level)

Print one line to stdout on success:
```
LIGHT_TAILOR_OK <variant> -> <output-dir>/cv.pdf (iterations=N, gates=PASS)
```

On failure (any gate didn't pass after the iteration budget):
```
LIGHT_TAILOR_FAIL <variant> reason=<verdict>:<short detail>
```

The `<verdict>` MUST be the terminal `check_page_fill.py` status from the LAST compile (`UNDERFILLED` / `OVERFLOW` / `SHORT_LINES_DETECTED` / `FORMAT_FAIL` / `FACTS_FAIL`), followed by a colon and a short human-readable detail. Examples:

```
LIGHT_TAILOR_FAIL data-scientist reason=UNDERFILLED:1-line gap after 4 compiles
LIGHT_TAILOR_FAIL solution-architect reason=OVERFLOW:trim-attempts-exhausted
LIGHT_TAILOR_FAIL ai-engineer reason=SHORT_LINES_DETECTED:42pct-tail-on-experience-bullet-3
LIGHT_TAILOR_FAIL data-analyst reason=oscillation:UNDERFILLED-OVERFLOW-x3
```

This way the orchestrator's Notion note records the actual gate that wouldn't close, not just `iteration-ceiling-hit`. If the failure isn't gate-related (e.g. agent tool-call ceiling hit before any gate ran), use `reason=ceiling:<detail>` instead.

Exit code 0 on success, 1 on failure. The orchestrator falls back to `cv/output/<variant>.pdf` if this skill fails.

## Discipline rules (carried from CLAUDE.md / memory)

- British English. No em-dashes.
- Profile NEVER names the target company.
- Profile close must be role-and-context specific (swap-test).
- Year claims in Profile must respect `seniority_caps.json` cap.
- Every factual claim traces to `master_cv.json`.
- Primary-employer bullet count: 5-8 (enforced).
- Action verb uniqueness across Experience bullets — already enforced in the variants; don't introduce duplicates when swapping.

## Files referenced

| File | Purpose |
|------|---------|
| `data/master_cv.json` | Source of truth for facts and the bullet pool for swaps |
| `cv/variants/<variant>.tex` | Visual scaffolding starting point |
| `cv/variants/seniority_caps.json` | Per-variant `max_years` cap |
| `scripts/check_page_fill.py` | Page fill gate |
| `scripts/check_cv_format.py` | Format + Profile + action-verb-uniqueness gate |
| `scripts/check_cv_facts.py` | Facts gate |
| `cv/CLAUDE.md` | Profile + format spec |
| `.claude/skills/tailor-cv-full/SKILL.md` | Heavier sibling: Full (JD-driven) tailoring |
| `.claude/skills/auto-apply/SKILL.md` | Daily orchestrator that invokes this skill |
