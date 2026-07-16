# Worked examples: configuring JobHunter for different searches

JobHunter was built for one person's search and then genericised. Every search has quirks that generic defaults cannot anticipate, so this document walks through three realistic personas end to end. Use them as patterns for your own `data/search_config.json` and `data/job_goals.json` during `/onboard`. Note how each persona keeps their existing tools: the tracker and CV backends bend to the user, never the other way round.

## Persona A: cross-border relocator (France to London)

A French citizen working as a cybersecurity consultant in Lyon, looking for a role in or around London to relocate. Open to adjacent career paths if they enable the move. Three angles matter: roles that want a French speaker, V.I.E. placements (the French international corporate volunteering scheme, which places EU candidates with French companies abroad), and roles at employers who sponsor UK Skilled Worker visas.

Key insight: **visa need is a search dimension, not a filter**. The wrong configuration treats "needs UK sponsorship" as a reason to skip; the right one targets the subset of the market where sponsorship or a scheme makes the move possible.

Tooling: keeps her CV in Word, does not use Notion. So: `"tracker": {"backend": "local"}`, `"cv": {"backend": "docx"}` with `cv/master.docx` exported from Word; tailored copies are produced per role and she reviews her pipeline in `data/tracker.csv`.

```json
{
  "candidate": {
    "display_name": "Marie Exemple",
    "summary": "Marie Exemple, 4 years as a cybersecurity consultant in Lyon (GRC audits, ISO 27001, SOC tooling). Native French, fluent English. EU citizen; needs UK sponsorship or a V.I.E. placement to work in London.",
    "total_experience_years": 4,
    "languages": ["French", "English"],
    "home_countries": ["France"],
    "right_to_work_labels": ["EU citizen", "French citizen", "citizen of the European Union"],
    "needs_sponsorship_in": ["United Kingdom"]
  },
  "search": {
    "locations": {
      "london": { "linkedin_geo_id": "102257491", "label": "London", "country": "United Kingdom" },
      "paris": { "linkedin_geo_id": "90009659", "label": "Paris", "country": "France" }
    },
    "default_locations": ["london"],
    "queries": {
      "cyber": "cybersecurity consultant",
      "grc": "information security GRC analyst",
      "french": "french speaking security analyst",
      "vie": "V.I.E cybersecurity",
      "vie_london": "VIE London",
      "adjacent": "security compliance analyst"
    },
    "default_queries": ["cyber", "french", "vie_london"]
  },
  "filters": {
    "title_blacklist": ["head of", "director", "intern"],
    "company_blacklist": ["<current employer>"],
    "required_language_ok": ["English", "French"],
    "skip_contract_types": ["stage", "alternance", "internship"]
  }
}
```

Notes for this persona:

- Because the United Kingdom is in `needs_sponsorship_in`, London roles are kept and only skipped when an application form has a hard right-to-work gate with no sponsorship path. The JD-level checks and the edge-case agent handle the grey areas.
- The `french` and `vie` queries surface the part of the London market where being French is an advantage rather than a visa complication: French banks and consultancies, subsidiaries of French groups, and V.I.E. postings.
- "Open to changing career path slightly" is expressed twice: an `adjacent` query here, and a wider `target_roles` list with matching `title_variants` in `master_cv.json` so tailoring can honestly reframe consulting experience for analyst and compliance roles.
- In `job_goals.json`, London gets a location score of 100 and everything else drops sharply, so scoring reflects that the move is the point of the search.

## Persona B: multi-board search with a transfer goal (Canada, business ops)

A strategy and operations lead at a startup design agency, looking for a business ops or strategy role in Canada at a company with a US presence, aiming for an internal transfer to Los Angeles later. Wants discovery beyond LinkedIn, especially startup-heavy boards and Ashby-hosted listings.

Key insights: **the transfer goal shapes company selection, not the role filter**, and **multi-board discovery is a watchlist plus ad-hoc URLs, not just the LinkedIn crawl**.

Tooling: an active Notion user who is non-technical. So: `"tracker": {"backend": "notion"}` (she reviews and moves roles in her own Notion workspace) and `"cv": {"backend": "docx"}`; LaTeX would be a barrier, not a feature.

```json
{
  "candidate": {
    "display_name": "Casey Example",
    "summary": "Casey Example, 5 years in strategy and operations at a design agency (client ops, pricing, hiring processes, exec support). Canadian citizen; long-term goal is an internal transfer to the US.",
    "total_experience_years": 5,
    "languages": ["English"],
    "home_countries": ["Canada"],
    "right_to_work_labels": ["Canadian citizen", "authorised to work in Canada"],
    "needs_sponsorship_in": ["United States"]
  },
  "search": {
    "locations": {
      "toronto": { "linkedin_geo_id": "100025096", "label": "Toronto", "country": "Canada" },
      "canada_remote": { "linkedin_geo_id": "101174742", "label": "Canada", "country": "Canada" }
    },
    "default_locations": ["toronto", "canada_remote"],
    "queries": {
      "bizops": "business operations strategy",
      "chief_of_staff": "chief of staff",
      "ops_manager": "operations manager startup",
      "strategy": "strategy and operations lead"
    },
    "default_queries": ["bizops", "strategy"]
  },
  "tracker": { "backend": "notion" },
  "cv": { "backend": "docx" },
  "filters": {
    "title_blacklist": ["vp ", "vice president", "director", "coordinator", "intern"],
    "industry_dealbreakers": [],
    "company_blacklist": ["<current agency>"]
  }
}
```

Notes for this persona:

- **Multi-board coverage.** LinkedIn discovery runs daily; her `data/watchlist.json` holds 15 target companies with their career-board URLs (Ashby, Greenhouse and Lever boards all work), built during onboarding and extended whenever she hears of a company she likes ("add <company> to my watchlist"). Any individual posting from any board can also be pushed through the pipeline directly with `/auto-apply <url>`; the ATS walkers already handle Ashby, Greenhouse, Lever, Workday, SmartRecruiters, BambooHR, Teamtailor, Jobvite and Welcome to the Jungle forms.
- **The US transfer angle** lives in `job_goals.json`: `target_role_philosophy` notes that companies with US offices (especially LA) score higher, and the scoring pass is told to weight multinational footprint under `founder_relevance`/`growth_potential` style weights. It is a company attribute, so it belongs in scoring, not in the deterministic title filter.
- During review weeks, this persona would typically run at `autonomy.level: "search"` or `"tailor"`, because ops and strategy applications often carry bespoke questions where a personal touch wins.

## Persona C: zero-setup local search (same city, better role)

A non-technical marketing coordinator looking for a step up in the same city. Does not use Notion, keeps a single PDF CV a friend helped design, and mainly wants the discovery and filtering done for her; she applies personally to the handful of roles that survive review.

```json
{
  "tracker": { "backend": "local" },
  "cv": { "backend": "pdf" },
  "autonomy": { "level": "search" },
  "candidate": {
    "display_name": "Jordan Example",
    "summary": "Jordan Example, 4 years in marketing coordination and campaign ops at two agencies. Strong on campaign delivery and analytics reporting; no people-management experience.",
    "total_experience_years": 4,
    "languages": ["English"],
    "home_countries": ["United Kingdom"],
    "right_to_work_labels": ["British citizen"],
    "needs_sponsorship_in": []
  },
  "search": {
    "locations": {
      "manchester": { "linkedin_geo_id": "<from a manual LinkedIn search URL>", "label": "Manchester", "country": "United Kingdom" }
    },
    "default_locations": ["manchester"],
    "queries": {
      "marketing": "marketing manager campaigns",
      "digital": "digital marketing executive"
    },
    "default_queries": ["marketing"]
  }
}
```

Notes for this persona:

- **Nothing to install or sign up for** beyond Claude Code and Python. The pipeline lives in `data/tracker.json`; every change refreshes `data/tracker.csv`, which she opens in Excel. Asking Claude "show me my pipeline" renders it as a table in chat.
- Her fixed PDF sits at `cv/master.pdf`. No tailoring happens, which is fine at `search` autonomy: she reviews each surviving role, applies herself with her own CV, and tells Claude "mark <company> as applied" so the tracker stays true.
- If she later wants tailored CVs, onboarding can be re-run to switch `cv.backend` to `docx`; nothing else changes.

## Adapting to your own situation

The pattern in both cases:

1. Say honestly who you are in `candidate.summary`; the realism filter uses it to protect you from wasted applications.
2. Express constraints in the right layer: hard nevers go in `filters`, market angles go in `search.queries`, aspirations and soft preferences go in `job_goals.json` scoring.
3. Visa and language situations are usually angles, not blockers: hunt the part of the market where your situation is an advantage.
4. Start at `search` autonomy, look at a week of results, tune, then decide how much to delegate.
5. Keep your own tools: pick the tracker and CV backends that match what you already use, and add depth (deep experience files, tailoring, more autonomy) only when you feel the need.
