# CV System - Claude Instructions

## Critical Requirement: Page Fill

**CVs MUST fill 95-100% of a single page.** The goal is to maximize content to the point where adding one more line would cause overflow to page 2.

- **Minimum acceptable: 95% page fill**
- Any CV with visible whitespace at the bottom looks unfinished
- Empty space signals to employers that the candidate lacks experience
- This is unacceptable and must be fixed before presenting to user

## Validation Process

1. Build PDFs with `make all` (requires `export PATH="/Library/TeX/texbin:$PATH"`)
2. Read each PDF in `output/` using Claude's Read tool
3. Visually assess page fill percentage
4. **If any variant has >5% whitespace at bottom, add more content**
5. Rebuild and re-validate until ALL variants pass 95% threshold
6. Never present CVs to user until all pass validation

## Content Expansion Levers

When a CV needs more content, use these in order:

1. **Add more AGI bullets** - There are 9 available in master_cv.json; use 7-8 per variant
2. **Include NF Capital** - Relevant research/fixed income experience (1-2 bullets)
3. **Expand UCL Innovation Lab** - 2 bullets (ML exercises + presentation)
4. **Expand Amplify Trading** - Up to 3 bullets (algo strategy, ranking, diploma)
5. **Add All M&A** - For research variant (macroeconomist role)
6. **Expand Projects section** - Include both Lineup and NutriPlan with technical details
7. **Add certifications line** - DataCamp, LIBF diploma
8. **Expand skills** - Add more tools/libraries relevant to role

## Content Sources

All content comes from `data/master_cv.json`.

## Variant-Specific Focus

| Variant | Primary Bullets | Secondary Experience | Projects |
|---------|-----------------|---------------------|----------|
| data-science | Analytics, AI, data reconciliation | NF Capital, UCL, Amplify | NutriPlan + Lineup |
| ai-ml | AI adoption, training, vendor review | NF Capital, UCL, Amplify | NutriPlan (detailed) + Lineup |
| software-eng | Engineering, automation, systems | NF Capital, UCL, Amplify | Lineup (detailed) + NutriPlan |
| portfolio-risk | BarraOne, attribution, team mgmt | NF Capital, Amplify | Lineup |
| quant-dev | Attribution, quantitative, data | NF Capital, Amplify (3) | Lineup |
| research | Analysis, stakeholder, vendor | NF Capital, All M&A, Amplify | - |
| client-solutions | Implementation, stakeholder, training | NF Capital, UCL | Lineup |

## LaTeX Tips for Page Fill

- Each `\cvbullet` adds ~1-3 lines depending on content length
- Projects section can be expanded with more technical detail
- Skills section can add more items per category
- Profile paragraph can be slightly longer if needed
