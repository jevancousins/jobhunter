# CV System - Claude Instructions

## Critical Requirement: Page Fill

**CVs MUST fill 100% of a single page.** The goal is to maximize content to the point where adding one more line would cause overflow to page 2.
- Any CV with visible whitespace at the bottom looks unfinished
- Empty space signals to employers that the candidate lacks experience
- This is unacceptable and must be fixed before presenting to user

## Validation Process

1. Build PDF with pdflatex (requires `export PATH="/Library/TeX/texbin:$PATH"`)
2. Run programmatic page fill check:
   ```bash
   python scripts/check_page_fill.py cv/output/tailored-build/[filename].pdf
   ```
3. Script returns FULL (gap < 15pt), UNDERFILLED (with line estimate), or OVERFLOW (>1 page)
4. If UNDERFILLED: add content using the expansion levers below
5. If OVERFLOW: trim lowest-priority content (interests > shortest bullet > project detail)
6. Rebuild and recheck — usually 0-1 iterations when starting from a variant template
7. Never present CVs to user until the script reports FULL

## Content Expansion Levers

When a CV needs more content, use these in order:

1. **Add more bullets from the primary role** - master_cv.json usually holds more bullets than any single variant uses; pull in the most role-relevant unused ones
2. **Include earlier roles** - Add 1-2 bullets from earlier experience entries in master_cv.json where they support the target role
3. **Expand education** - Modules, dissertation, or awards from master_cv.json education
4. **Expand the Projects section** - Add projects from master_cv.json with technical detail relevant to the role
5. **Add a certifications line** - Certifications recorded in master_cv.json
6. **Expand skills** - Add more tools/libraries relevant to the role

## Content Sources

All content comes from `data/master_cv.json`.

## Variant-Specific Focus

Variant guidance lives in `cv/templates/` and `cv/variants/variants.json`: which roles, bullets, and projects each variant emphasises. Consult those rather than hard-coding a focus table here.

## LaTeX Tips for Page Fill

- Each `\cvbullet` adds ~1-3 lines depending on content length
- Projects section can be expanded with more technical detail
- Skills section can add more items per category
- Profile paragraph can be slightly longer if needed
