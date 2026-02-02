"""AI prompt templates for JobHunter."""

JOB_SCORING_PROMPT = """You are an expert career advisor evaluating job opportunities.

## Candidate Profile
{master_cv_summary}

## Career Goals & Preferences
{job_goals_summary}

## Dealbreakers (auto-reject if any match)
{dealbreakers}

## Job Posting
Title: {job_title}
Company: {company}
Location: {location}
Description:
{job_description}

## Scoring Task
First check dealbreakers. If any match, return total_score: 0 with dealbreaker_triggered set.

Otherwise, score on each dimension:
1. Growth Potential (0-25): Learning opportunities, technical challenges, skill development, mentorship signals, new vs maintenance work
2. Role Alignment (0-20): Skills match to candidate profile + target role fit
3. Founder Relevance (0-20): Product exposure, ownership, autonomy, user-facing work, breadth of responsibility, entrepreneurial skills
4. Location Fit (0-15): Use location scores - Paris=15, Lyon=14, France(Other)=13, London=12, Remote=11, Switzerland=11, Luxembourg=10, Canada cities=10, US cities=10, Tokyo=8, Other=4
5. Compensation Signal (0-10): Salary range indicators, seniority signals, equity mentions (if not stated, estimate from role level)
6. Industry Fit (0-10): Alignment with Finance/FinTech/Tech/Startups/AI-ML

## Output Format (JSON only, no markdown)
{{
  "dealbreaker_triggered": null,
  "scores": {{
    "growth_potential": {{"score": X, "reason": "..."}},
    "role_alignment": {{"score": X, "reason": "..."}},
    "founder_relevance": {{"score": X, "reason": "..."}},
    "location_fit": {{"score": X, "reason": "..."}},
    "compensation_signal": {{"score": X, "reason": "..."}},
    "industry_fit": {{"score": X, "reason": "..."}}
  }},
  "total_score": X,
  "verdict": "Apply",
  "summary": "2-3 sentence assessment",
  "key_requirements": ["req1", "req2"],
  "potential_concerns": ["concern1"],
  "questions_to_ask": ["question1", "question2"]
}}

If dealbreaker triggered, use this format instead:
{{
  "dealbreaker_triggered": "Crypto/Web3 industry",
  "scores": {{}},
  "total_score": 0,
  "verdict": "Skip",
  "summary": "Role is in dealbreaker industry.",
  "key_requirements": [],
  "potential_concerns": [],
  "questions_to_ask": []
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

CAREER_PAGE_EXTRACTION_PROMPT = """You are an expert at extracting structured job listing data from career pages.

## Task
Extract all job postings from the following career page HTML. Focus on extracting jobs that are relevant to:
- Data Science / Machine Learning / AI
- Quantitative Finance / Portfolio Management / Risk
- Software Engineering / Python Development
- Product / Solutions Architecture

## Company Information
Company Name: {company_name}
Base URL: {base_url}

## HTML Content
{html_content}

## Instructions
1. Identify all job listings on the page
2. For each job, extract: title, location, URL, department (if available), posted date (if available)
3. Resolve relative URLs to absolute URLs using the base URL
4. If no jobs are found or the page appears blocked, indicate this
5. Look for pagination links if present

## Output Format (JSON only, no markdown)
{{
  "jobs": [
    {{
      "title": "Job Title",
      "location": "City, Country or Remote",
      "url": "https://full-url-to-job-posting",
      "department": "Engineering",
      "posted_date": "2024-01-15"
    }}
  ],
  "pagination": {{
    "has_more_pages": true,
    "next_page_url": "https://..."
  }},
  "blocked": false,
  "blocked_reason": null,
  "extraction_confidence": "high"
}}

Notes:
- If a field is not available, use null
- posted_date should be in YYYY-MM-DD format if extractable, otherwise null
- extraction_confidence: "high" if clear job listings found, "medium" if some ambiguity, "low" if uncertain
- blocked: true if the page shows a CAPTCHA, access denied, or similar blocking
- Only include jobs that appear to be open positions (not blog posts, news, etc.)"""

PROMPTS = {
    "job_scoring": JOB_SCORING_PROMPT,
    "cv_tailoring": CV_TAILORING_PROMPT,
    "cover_letter": COVER_LETTER_PROMPT,
    "company_research": COMPANY_RESEARCH_PROMPT,
    "interview_questions": INTERVIEW_QUESTIONS_PROMPT,
    "career_page_extraction": CAREER_PAGE_EXTRACTION_PROMPT,
}
