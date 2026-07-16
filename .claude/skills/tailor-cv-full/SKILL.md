---
name: tailor-cv-full
description: JD-driven Full tailoring (optional advanced mode). Treats the JD as a prioritised checklist and constructs the CV by mapping each item to evidence in data/deep_experience.json (or a user-built experience wiki under Second Brain/ if present). Strict deterministic gates on Profile structure, action-verb uniqueness, page-fill, format, and facts.
argument-hint: "[role-variant] [jd-path]"
---

# Tailor CV (Full, JD-driven)

This is the heavyweight, JD-driven tailoring methodology — an **optional advanced mode** alongside the cheaper `/tailor-cv-light`, which remains the default for the auto-apply pipeline.

Historical design note: an earlier "full" methodology inherited too much variant scaffolding and didn't drive content from the JD; controlled comparisons found it matched Light on quality at 5-8x the cost. This methodology fixes that by making the JD the structural anchor.

## Inputs

- **Role variant** (e.g. `ai-engineer`) — used as visual scaffolding only. Per-variant `seniority_caps.json` cap is binding.
- **JD** at `data/job_descriptions/<filename>.md` — the structural anchor.
- **Primary source for evidence:** `data/deep_experience.json` (rich narrative + STAR-level evidence per experience unit). If the user has built an experience wiki under `Second Brain/` (one markdown file per experience unit plus an `_index.md`), prefer that instead — it holds the same kind of information in navigable per-file form. Load via the protocol in Phase B.
- **Fallback for evidence:** `data/master_cv.json` bullets (summary level) when the evidence pool has nothing relevant.
- **Source of truth for facts:** `data/master_cv.json` (years, titles, dates, language levels, modules, certifications).

## Phase A: JD decomposition (one-shot)

Read the JD end-to-end. Extract four ordered lists:

### A1. Action verbs (verbatim)
Pull the verbs that start each Responsibility/Requirement bullet. Note their JD frequency. **Order by frequency descending.** This is the candidate verb pool for Experience bullet starts.

### A2. Required keywords + named technologies
Pull every named tech, framework, language, system, domain term from the JD. Tag each with priority:
- **P0:** in JD title
- **P1:** in Required Qualifications / "must have"
- **P2:** in Responsibilities or repeated 2+ times
- **P3:** in Nice-to-Have / Preferred Qualifications

### A3. Responsibilities checklist
Each bulleted Responsibility becomes one checklist item. Preserve JD wording for fidelity. Order = JD order (the JD's own ordering is the recruiter's priority).

### A4. Requirements + Nice-to-haves checklist
Same treatment for the Required Qualifications and Preferred Qualifications sections. Required > Preferred in priority.

**Output:** persist this decomposition to `<output-dir>/checklist.json` (the working directory for this tailoring run) so subsequent steps reference it without re-reading the JD.

```json
{
  "jd_action_verbs": [{"verb": "Architect", "frequency": 2, "context": "..."}, ...],
  "keywords": [{"term": "Python", "priority": "P0"}, ...],
  "responsibilities": ["...", "..."],
  "requirements": ["...", "..."],
  "nice_to_have": ["...", "..."]
}
```

## Phase B: Evidence mapping

Evidence comes from the candidate's evidence pool. **First check whether a `Second Brain/` directory exists at the repo root.** If it does, use the wiki protocol (B0 + B1). If it does not, skip B0 and use `data/deep_experience.json` as the evidence pool in B1 — read it once and search its entries the same way.

### B0. Wiki index scan (only when `Second Brain/` exists)
Read `Second Brain/_index.md`. It lists the experience entries with one-line summaries and their key themes/skills. Use it to identify the 2-4 most relevant files for this JD's keyword set. Do NOT load the full directory — load only the files that match.

**Selection heuristics:**
- Match on P0/P1 keywords first (technologies, domain terms from JD title and required quals)
- Match on cv_targets in the frontmatter (e.g. `data-engineer`, `ai-ml`, `quant-dev`)
- Prefer files whose `themes` overlap the JD's domain
- Always load the file for the most recent/prominent role if it is at all relevant

### B1. Evidence lookup (per JD checklist item)
For each item across A2/A3/A4 (in priority order: P0 > P1 > P2 > P3, then JD order within each tier):

1. Search the loaded evidence (wiki files, or `deep_experience.json` entries) for the strongest support (project narrative, STAR story, metric, technical detail). In wiki files the `## Technical Detail`, `## Results`, and `## STAR Story` sections are the most evidence-rich; in `deep_experience.json` the per-project narrative, challenge, and results fields serve the same role.
2. Fall back to `data/master_cv.json` bullets if the loaded evidence has nothing relevant. If a different wiki file would clearly have better evidence, load it now.
3. If no evidence exists, mark as **SKIP**. Do not invent. Do not pad. Silent omission is the rule.
4. **Equivalent-tech substitution:** if the JD demands a specific tech the candidate lacks but a clear equivalent exists, note the substitution. Examples of the pattern: Snowflake → Databricks, Airflow → GitHub Actions, Kafka → Azure Event Hubs. Substitutions are only valid where the evidence pool supports the equivalent — grounded in the candidate's actual adjacent experience, never inferred. Substitutes go in Skills as the equivalent name (do not claim the JD-named tech).
5. **Equivalent does not mean fabricate.** If the candidate has neither the JD tech nor a defensible equivalent, mark SKIP.

**Output:** persist to `<output-dir>/evidence.json`.

```json
{
  "checklist_item_idx": 0,
  "checklist_item_text": "...",
  "evidence_source": "deep_experience.json#<project-key> (or Second Brain/<file>.md#Results)",
  "evidence_summary": "One-line summary of the strongest matching evidence.",
  "verdict": "MAPPED" | "SKIP" | "EQUIVALENT",
  "equivalent_note": "JD says Snowflake; using Databricks as equivalent."
}
```

## Phase C: CV construction

Start from the matched variant template (copy `cv/variants/<variant>.tex` to `<output-dir>/cv.tex` if the caller has not already). The variant gives visual scaffolding (section structure, formatting macros, page-fill calibration). Overwrite the content section by section.

### C1. Profile
Per [cv/CLAUDE.md](../../../cv/CLAUDE.md) Lead/Evidence/Close, 40-110 words, 3-4 sentences.
- **Lead:** professional identity matching JD title (subject to per-variant seniority cap; never claim more years than the cap permits).
- **Evidence:** 1-2 quantified achievements that hit the JD's #1-2 priorities (P0 keywords + first Responsibility).
- **Close:** role-and-context specific. NEVER name the target company. Use role archetype + location + named tech + posture (client-facing/internal) + scope + stage to make the close non-reusable.

### C2. Skills
Reorder + rename categories to mirror the JD's vocabulary. JD-priority terms first within each category. Apply equivalent-tech substitutions from Phase B. Drop variant skills that don't appear in the evidence map (they're filler for this JD).

### C3. Experience bullets
For each Experience entry in `master_cv.json`, order bullets by the JD-priority of what they evidence. The primary employer's cap stays at 5-8 bullets per `check_cv_format.py`. Within the cap, the bullet order is:

1. Strongest evidence for the JD's #1 priority (P0 keyword or first Responsibility) — bullet #1
2. Strongest evidence for #2 priority — bullet #2
3. ... and so on

**Action verb rule (deterministic gate):** the first word of each bullet is an action verb. Use JD-extracted verbs verbatim where they fit the actual evidence. **Each opening verb must appear EXACTLY ONCE across all Experience bullets in the CV.** When you exhaust the JD's distinct verbs, fall back to the master_cv.json bullet's original verb or a synonym. The check is enforced by `scripts/check_cv_format.py`'s `ACTION_VERB_DUPLICATE` rule.

### C4. Projects
Pick projects that demonstrate the most JD checklist items. The variants curate projects per archetype, but Full overrides this with the JD's own priority. Order projects by JD relevance descending. Use the variant's project section size (typically 2-4 projects) but swap content as needed, drawing only from `master_cv.json` `projects`.

### C5. Education
Tailor module list to JD relevance. Modules are constrained to those in `master_cv.json` `education.modules` or `modules_by_year` — never invent.

## Phase D: Verify

Run all five gates from the repo root:

1. **Page fill:** `python scripts/check_page_fill.py <output-dir>/cv.pdf` → must return FULL with no non-Languages SHORT_LINES.
2. **Format:** `python scripts/check_cv_format.py <output-dir>/cv.tex` → must pass all checks including `ACTION_VERB_DUPLICATE`.
3. **Facts:** `python scripts/check_cv_facts.py <output-dir>/cv.tex` → must pass.
4. **Keyword overlap:** `python scripts/keyword_overlap.py --cv <output-dir>/cv.tex --jd <jd>` → record `overlap_ratio` and `missing_terms` in metrics.json. No hard threshold; this is a measurement.
5. **Manual cross-check:** scan the final cv.tex against `evidence.json`. Every bullet must trace to a SOURCE entry. Any bullet that drifted from the evidence is fabrication; remove or correct.

## Phase E: Iterate

If any gate fails:
- **Page fill underfilled:** add the next-highest-priority evidence from the checklist that wasn't included. Do not pad.
- **Page fill overflow:** drop the lowest-priority bullet or trim the longest project description.
- **Action verb duplicate:** swap one of the duplicates for a synonym from the JD's pool or the master_cv.json bullet's original verb.
- **Format/facts violation:** fix the specific violation and recompile.

Stop when all gates pass.

## Output to metrics.json

After all gates pass, update `<output-dir>/metrics.json`:

```json
{
  "token_cost_estimate": <int>,
  "wall_clock_seconds": <int>,
  "iterations": <int>,
  "page_fill_verdict": "FULL",
  "page_fill_short_lines_count": 0,
  "format_check": "passed",
  "facts_check": "passed",
  "action_verb_duplicates": 0,
  "keyword_overlap": {
    "jd_terms_total": <int>,
    "jd_terms_found": <int>,
    "overlap_ratio": <float>
  },
  "checklist_items_mapped": <int>,
  "checklist_items_skipped": <int>,
  "equivalent_substitutions": [<list of {jd_term, used_term}>],
  "status": "complete",
  "notes": "..."
}
```

## Discipline rules (carried from CLAUDE.md / memory)

- British English. No em-dashes.
- Profile NEVER names the target company (rare exceptions only when candidate has genuine prior connection).
- Profile close must be role-and-context specific (the swap-test: "would the close still make sense for a different opening?" If yes, rewrite).
- Year claims in Profile must respect the variant's `seniority_caps.json` cap.
- Every factual claim traces to `master_cv.json`.
- Primary-employer bullet count: 5-8 (enforced).
- Action verb uniqueness across Experience bullets (enforced).

## What this skill does NOT do

- Does not name the target company in the Profile.
- Does not invent JDed-but-unsupported claims to fill checklist items.
- Does not exceed the variant's bullet caps (would inflate page beyond 1).
- Does not modify Education dates or degree class — those are facts.
- Does not save the JD to Notion or move PDFs to `cv/output/tailored/` — those are auto-apply pipeline steps; this skill only produces the tailored artefacts in its output directory.

## Files referenced

| File | Purpose |
|------|---------|
| `data/deep_experience.json` | Default evidence pool for checklist mapping |
| `Second Brain/_index.md` | Optional — if a user-built experience wiki exists, read this index first for file selection |
| `Second Brain/<file>.md` | Optional — per-experience wiki files (load 2-4 relevant files only) |
| `data/master_cv.json` | Source of truth for facts (years, titles, dates, modules, languages) and bullet-level fallback |
| `cv/variants/<role>.tex` | Visual scaffolding starting point |
| `cv/variants/seniority_caps.json` | Per-variant max-claimable-years cap |
| `scripts/check_page_fill.py` | Page fill gate |
| `scripts/check_cv_format.py` | Format + Profile + action-verb-uniqueness gate |
| `scripts/check_cv_facts.py` | Facts gate |
| `scripts/keyword_overlap.py` | Keyword overlap measurement |
| `cv/CLAUDE.md` | Canonical Profile + format spec |
| `.claude/skills/tailor-cv/SKILL.md` | Interactive tailoring skill (lighter sibling for single-role, user-driven runs) |

> **Evidence-pool note:** `data/deep_experience.json` is the standard evidence source and is populated during onboarding. A `Second Brain/` wiki is an optional upgrade for users who want richer, navigable per-experience files; when present, it takes precedence and `deep_experience.json` becomes the fallback.
