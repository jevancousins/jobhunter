"""AI prompt templates for JobHunter."""

JOB_SCORING_PROMPT = """You are an expert career advisor helping evaluate job opportunities.

## Candidate Profile
{master_cv_summary}

## Target Preferences
- Primary location: Paris, France (girlfriend in Lyon)
- Acceptable locations: London, Remote, Switzerland, Luxembourg, Montreal, Toronto, New York, Boston, San Francisco, Los Angeles, San Diego, Tokyo, anywhere in France
- Target roles: Quantitative Analyst, Data Scientist (Finance), Investment Analyst, Solution Architect, Product Manager (FinTech), Software Engineer (Finance/Trading), Automation Engineer, BI Developer, Quantitative Developer
- Industries: Finance, FinTech, Tech, Startups
- Experience level: ~3.5 years
- Languages: English (Native), French (Proficient)

## Job Posting
Title: {job_title}
Company: {company}
Location: {location}
Description:
{job_description}

## Scoring Task
Score this job on each factor (provide score and brief reasoning):

1. Location Match (0-25): Paris=25, Lyon=24, France(Other)=22, London=20, Remote=18, Switzerland/Luxembourg=17, North America cities=17, Tokyo=16, Other=7
2. Role Alignment (0-25): How well does this match the candidate's skills and target roles?
3. Industry Fit (0-15): Finance/FinTech/Tech/Startup alignment
4. Seniority Match (0-10): Appropriate for ~3.5 years experience?
5. Skills Match (0-15): Python, SQL, data analysis, fixed income, Power BI, MSCI BarraOne, performance attribution, etc.
6. Impact Potential (0-10): Does this role offer meaningful work with business impact?

## Output Format (JSON only, no markdown)
{{
  "scores": {{
    "location": {{"score": X, "reason": "..."}},
    "role_alignment": {{"score": X, "reason": "..."}},
    "industry_fit": {{"score": X, "reason": "..."}},
    "seniority": {{"score": X, "reason": "..."}},
    "skills_match": {{"score": X, "reason": "..."}},
    "impact_potential": {{"score": X, "reason": "..."}}
  }},
  "total_score": X,
  "summary": "2-3 sentence overall assessment",
  "key_requirements": ["req1", "req2", "req3"],
  "potential_concerns": ["concern1", "concern2"]
}}"""

CV_TAILORING_PROMPT = """You are an expert CV writer specialising in finance and technology roles.

## Task
Tailor the candidate's CV for the following job application.

## Master CV
{master_cv_json}

## Target Job
Title: {job_title}
Company: {company}
Description:
{job_description}

Key Requirements Identified:
{key_requirements}

## Instructions
1. Select the most relevant profile summary (or adapt one)
2. Choose 3-4 most relevant roles from experience
3. For each role, select 3-5 most relevant bullets
4. Reframe bullets to emphasise skills matching the job requirements
5. Ensure keywords from the job description appear naturally
6. Keep total CV to 1-2 pages

## Output Format (JSON only, no markdown)
{{
  "profile": "Tailored profile summary...",
  "experience": [
    {{
      "company": "...",
      "title": "...",
      "dates": "...",
      "location": "...",
      "bullets": ["Reframed bullet 1", "Reframed bullet 2"]
    }}
  ],
  "skills_to_highlight": ["skill1", "skill2"],
  "keywords_incorporated": ["keyword1", "keyword2"]
}}"""

COVER_LETTER_PROMPT = """You are an expert cover letter writer.

## Task
Write a compelling cover letter for this job application.

## Candidate
{candidate_summary}

## Target Job
Company: {company}
Title: {job_title}
Description: {job_description}

## Company Research
{company_research}

## Instructions
1. Opening: Hook that shows genuine interest in this specific role
2. Why this company: Reference something specific about the company
3. Why me: 2-3 achievements that directly address job requirements
4. Closing: Confident call to action

## Constraints
- 250-400 words
- Professional but personable tone
- No generic phrases like "I am writing to apply for..."
- Show personality while remaining professional

## Output
Write the cover letter as plain text."""

COMPANY_RESEARCH_PROMPT = """Research the following company to prepare for a job application/interview.

Company: {company}
Role Applied For: {job_title}

Provide:
1. Company overview and mission (2-3 sentences)
2. Recent news or developments (last 3-6 months)
3. Products/services relevant to the role
4. Company culture signals (from job posting, reviews, etc.)
5. Key competitors and market position
6. Suggested talking points for interview

Output as structured text with clear sections."""

INTERVIEW_QUESTIONS_PROMPT = """Generate likely interview questions for this role.

Job Title: {job_title}
Company: {company}
Job Description: {job_description}

Candidate Background:
{candidate_summary}

Generate:
1. 5 Technical questions specific to the role
2. 5 Behavioural questions (STAR format expected)
3. 3 Questions about the company/industry
4. 5 Questions the candidate should ask the interviewer

For each question, provide a brief note on what the interviewer is looking for."""

PROMPTS = {
    "job_scoring": JOB_SCORING_PROMPT,
    "cv_tailoring": CV_TAILORING_PROMPT,
    "cover_letter": COVER_LETTER_PROMPT,
    "company_research": COMPANY_RESEARCH_PROMPT,
    "interview_questions": INTERVIEW_QUESTIONS_PROMPT,
}
