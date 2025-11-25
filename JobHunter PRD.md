# JobHunter AI
## Product Requirements Document

**Version:** 1.0  
**Date:** 25 November 2025  
**Author:** Jevan Cousins  
**Status:** Draft

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Problem Statement](#2-problem-statement)
3. [Goals & Success Metrics](#3-goals--success-metrics)
4. [User Profile](#4-user-profile)
5. [Scope](#5-scope)
6. [Functional Requirements](#6-functional-requirements)
7. [Technical Architecture](#7-technical-architecture)
8. [Data Models](#8-data-models)
9. [AI Integration](#9-ai-integration)
10. [Target Companies](#10-target-companies)
11. [Development Phases](#11-development-phases)
12. [Cost Estimates](#12-cost-estimates)
13. [Risks & Mitigations](#13-risks--mitigations)
14. [Future Enhancements](#14-future-enhancements)
15. [Appendices](#15-appendices)

---

## 1. Executive Summary

**JobHunter AI** is a personal job search automation platform designed to streamline the job discovery, application, and interview preparation process. The system uses AI to intelligently score job opportunities, tailor application materials, and provide interview preparation support.

### Key Value Propositions

- **Automated Discovery:** Daily scraping of job postings from multiple sources with AI-powered suitability scoring
- **Smart Prioritisation:** Weighted scoring system with Paris as the primary location preference
- **One-Click Applications:** Automated CV tailoring and cover letter generation
- **Interview Preparation:** Automated research on companies and interviewers
- **Zero Frontend Development:** Notion serves as the user interface and database

### Target User

Single user (Jevan Cousins) — a Solution Architect at Allianz Global Investors with 3+ years of experience, seeking technical roles in finance, tech, or startups, with a strong preference for Paris-based opportunities.

---

## 2. Problem Statement

### Current Pain Points

1. **Time-Consuming Search:** Manually checking multiple job boards daily is inefficient
2. **Inconsistent Applications:** Tailoring CVs and cover letters for each role is tedious and often skipped
3. **Missed Opportunities:** Good roles are missed due to delayed discovery or poor keyword matches
4. **Role Pigeonholing:** Being labelled as "Solution Architect" when skills apply to many role types (analyst, developer, product manager)
5. **Location Complexity:** Balancing Paris preference with openness to other cities requires manual filtering
6. **Interview Preparation:** Researching companies and interviewers is time-consuming

### Desired Outcome

A fully automated system that:
- Discovers relevant jobs daily across multiple role types and locations
- Scores opportunities based on personalised criteria
- Generates tailored application materials on demand
- Tracks application status and provides interview preparation support

---

## 3. Goals & Success Metrics

### Primary Goals

| Goal | Description |
|------|-------------|
| **G1** | Reduce daily job search time from 60+ minutes to <10 minutes |
| **G2** | Increase application rate by 3x through automated material generation |
| **G3** | Improve application quality through AI-tailored CVs |
| **G4** | Never miss a high-quality opportunity at target companies |
| **G5** | Be fully operational within 2 weeks |

### Success Metrics

| Metric | Target | Measurement |
|--------|--------|-------------|
| Jobs discovered per day | 20-50 relevant postings | Count in Notion |
| Time to review daily feed | <10 minutes | Self-reported |
| CV generation time | <2 minutes per application | Script execution time |
| Application conversion rate | Track and optimise | Applications → Interviews |
| System uptime | 99% (daily job runs) | GitHub Actions logs |

---

## 4. User Profile

### Primary User: Jevan Cousins

**Current Role:** Solution Architect at Allianz Global Investors (3+ years)

**Education:** BSc Natural Sciences (Physics & Mathematics), UCL — 2:1

**Technical Skills:**
- Programming: Python, SQL, R, VBA, JavaScript, Swift
- Platforms: Microsoft Power Platform, Azure, Databricks, JIRA
- Data: Power BI, DAX, Jupyter Notebook
- Domain: Fixed Income, Performance Attribution, MSCI BarraOne

**Key Achievements:**
- Led global MSCI BarraOne implementation for Fixed Income teams
- Engineered custom performance attribution models saving £25K+ per report
- Pioneered AI adoption with 50+ use cases identified
- Automated reconciliation processes saving £200K+ annually

**Target Role Types:**
- Quantitative Analyst / Portfolio Analyst
- Data Scientist / Data Analyst (Finance)
- Investment Analyst / Research Analyst
- Solution Architect / Technical Architect
- Product Manager (FinTech)
- Software Engineer (Finance/Trading)
- Automation Engineer
- Business Intelligence Developer
- Quantitative Developer

**Location Preferences:**
1. Paris, France (Primary — girlfriend in Lyon)
2. London, UK (Current location)
3. Remote roles
4. Other: Montreal, Toronto, New York, Boston, Los Angeles, San Diego, San Francisco, Tokyo, Switzerland, Luxembourg, anywhere in France

**Languages:** English (Native), French (Proficient)

---

## 5. Scope

### In Scope (MVP)

| Feature | Priority |
|---------|----------|
| Job scraping from Indeed, LinkedIn, Welcome to the Jungle | P0 |
| Company career page monitoring (watchlist) | P0 |
| AI suitability scoring with weighted criteria | P0 |
| Notion integration (push jobs, read status changes) | P0 |
| CV tailoring engine | P0 |
| Cover letter generation | P0 |
| Google Drive integration for document storage | P0 |
| Scheduled daily runs via GitHub Actions | P0 |
| Status-based automation (Apply → Generate materials) | P1 |
| Interview preparation notes | P1 |
| Company research summaries | P1 |

### Out of Scope (MVP)

| Feature | Rationale |
|---------|-----------|
| Automated job application submission | Risk of errors; requires human review |
| Gmail integration for response monitoring | Phase 2 feature |
| Mobile app | Notion mobile app suffices |
| Multi-user support | Single user tool |
| Salary negotiation features | Out of initial scope |

### Future Scope

- Gmail API integration for application tracking
- LinkedIn profile optimisation suggestions
- Networking recommendations (connections at target companies)
- French CV translation
- Application A/B testing

---

## 6. Functional Requirements

### 6.1 Job Discovery Engine

#### FR-1.1: Multi-Source Job Scraping

**Description:** The system shall scrape job postings from multiple sources daily.

**Sources:**
| Source | Method | Priority |
|--------|--------|----------|
| Indeed | RSS feed + web scraping | P0 |
| LinkedIn Jobs | Web scraping (Playwright) | P0 |
| Welcome to the Jungle | API/scraping | P0 (France-focused) |
| Company career pages | Custom scrapers per company | P1 |
| Glassdoor | Web scraping | P2 |
| AngelList/Wellfound | API | P2 |

**Acceptance Criteria:**
- [ ] System scrapes all P0 sources daily at 07:00 UTC
- [ ] Duplicate jobs (same URL or title+company) are not added
- [ ] Failed scrapes are logged and retried once
- [ ] New jobs are pushed to Notion within 30 minutes of discovery

#### FR-1.2: Search Criteria Configuration

**Description:** The system shall support flexible, configurable search criteria stored in Notion.

**Configurable Parameters:**
- Role keywords (list)
- Locations with weights
- Industries
- Excluded companies
- Minimum suitability score threshold

**Acceptance Criteria:**
- [ ] Search criteria can be modified in Notion without code changes
- [ ] Multiple active search criteria sets can run simultaneously
- [ ] Changes take effect on next scheduled run

#### FR-1.3: Company Watchlist

**Description:** The system shall maintain a list of target companies and check their career pages daily.

**Acceptance Criteria:**
- [ ] User can add/remove companies via Notion
- [ ] System checks career pages of all "Check Daily = true" companies
- [ ] Last checked date is updated after each run

---

### 6.2 AI Suitability Scoring

#### FR-2.1: Composite Scoring Algorithm

**Description:** Each job posting shall receive a composite suitability score (0-100) based on weighted factors.

**Scoring Factors:**

| Factor | Weight | Description | Scoring Logic |
|--------|--------|-------------|---------------|
| Location Match | 25% | How well location matches preferences | Paris=100, London=80, Other preferred=70, Remote=75, Other=30 |
| Role Alignment | 25% | Match to target role types and responsibilities | AI analysis of job description |
| Industry Fit | 15% | Finance/FinTech/Tech/Startup alignment | Keyword and company analysis |
| Seniority Match | 10% | Appropriate for ~3.5 years experience | Title and requirements analysis |
| Skills Match | 15% | Python, SQL, data analysis, fixed income, etc. | Keyword extraction and matching |
| Impact Potential | 10% | Signals of meaningful work and business impact | AI sentiment analysis |

**Acceptance Criteria:**
- [ ] All jobs receive a score between 0-100
- [ ] Score breakdown is stored as JSON for transparency
- [ ] AI provides 2-3 sentence reasoning for each score
- [ ] Scoring completes within 5 seconds per job

#### FR-2.2: Score Thresholds

**Description:** Jobs shall be filtered and categorised based on score thresholds.

| Threshold | Action |
|-----------|--------|
| Score ≥ 60 | Add to Notion with status "New" |
| Score < 60 | Discard (do not add to Notion) |
| Score ≥ 80 | Flag as "Strong Match" in Notion |
| Score ≥ 90 | Send push notification (future) |

---

### 6.3 Notion Integration

#### FR-3.1: Jobs Database

**Description:** Jobs shall be stored in a Notion database with the following schema.

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| Title | Title | Job title |
| Company | Select | Company name |
| Location | Select | City/Remote |
| Score | Number | Suitability score (0-100) |
| Status | Select | New / Reviewing / Apply / Applied / Interview / Offer / Rejected / Pass |
| Source | Select | LinkedIn / Indeed / WTFJ / Company Page |
| URL | URL | Link to job posting |
| Posted Date | Date | When job was posted |
| Discovered Date | Date | When system found it |
| Salary | Text | Salary range if available |
| Score Breakdown | Text | JSON breakdown of scoring |
| AI Analysis | Text | AI reasoning for score |
| Tailored CV | URL | Google Drive link |
| Cover Letter | URL | Google Drive link |
| Notes | Text | User's personal notes |
| Interview Prep | Relation | Link to Interview Prep database |

**Views:**
- **Daily Feed:** Filter: Discovered = Today, Sort: Score desc
- **To Review:** Filter: Status = New AND Score ≥ 60
- **Strong Matches:** Filter: Score ≥ 80
- **Paris Jobs:** Filter: Location = Paris
- **Applied:** Filter: Status = Applied
- **Kanban:** Group by Status
- **By Company:** Group by Company

#### FR-3.2: Company Watchlist Database

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| Name | Title | Company name |
| Careers URL | URL | Link to careers page |
| Priority | Select | High / Medium / Low |
| Locations | Multi-select | Offices of interest |
| Check Daily | Checkbox | Include in daily scrape |
| Last Checked | Date | Auto-updated |
| Notes | Text | Why interested |

#### FR-3.3: Search Criteria Database

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| Name | Title | Criteria set name |
| Active | Checkbox | Is this search active |
| Keywords | Multi-select | Role keywords |
| Locations | Multi-select | Target cities |
| Location Weights | Text | JSON: {"Paris": 100, "London": 80} |
| Min Score | Number | Threshold to add to Notion |
| Excluded Companies | Multi-select | Companies to skip |

#### FR-3.4: Interview Prep Database

**Properties:**

| Property | Type | Description |
|----------|------|-------------|
| Job | Relation | Link to Jobs database |
| Company Research | Text | AI-generated company summary |
| Interviewers | Text | Names and research |
| Likely Questions | Text | AI-generated questions |
| My Talking Points | Text | Personalised responses |
| Notes | Text | User notes |

#### FR-3.5: Status Change Detection

**Description:** The system shall poll Notion every 15 minutes to detect status changes and trigger appropriate actions.

| Status Change | Action Triggered |
|---------------|------------------|
| Any → "Apply" | Generate tailored CV + cover letter, upload to Drive, update Notion with links |
| Any → "Interview" | Generate interview prep notes, create Interview Prep entry |
| Any → "Applied" | Log application date (future: start Gmail monitoring) |

**Acceptance Criteria:**
- [ ] Polling runs every 15 minutes via GitHub Actions
- [ ] Status changes are detected within 15 minutes
- [ ] Materials are generated and linked within 5 minutes of detection

---

### 6.4 CV Tailoring Engine

#### FR-4.1: Master CV Management

**Description:** The system shall maintain a structured JSON representation of the user's master CV.

**Master CV Structure:**
```json
{
  "personal": {
    "name": "Jevan Cousins",
    "email": "jevan.cousins@gmail.com",
    "phone": "+44 7860 606 662",
    "linkedin": "linkedin.com/in/jevancousins"
  },
  "profiles": {
    "default": "Profile text...",
    "analyst": "Analyst-focused profile...",
    "technical": "Technical-focused profile...",
    "product": "Product-focused profile..."
  },
  "experience": [
    {
      "company": "Allianz Global Investors",
      "title": "Solution Architect",
      "location": "London, UK",
      "start_date": "Jun 2022",
      "end_date": "Present",
      "bullets": [
        {
          "text": "Led technical implementation of MSCI BarraOne...",
          "tags": ["leadership", "project-management", "fixed-income", "analytics"],
          "metrics": "completed project attempted 2 times in 7 years"
        }
      ]
    }
  ],
  "education": [...],
  "skills": {...},
  "certifications": [...],
  "interests": [...]
}
```

#### FR-4.2: AI-Powered Tailoring

**Description:** The system shall use AI to tailor CVs based on job descriptions.

**Tailoring Process:**
1. Analyse job description for key requirements and keywords
2. Select most relevant experiences and bullets from master CV
3. Reframe bullet points to emphasise relevant skills
4. Generate role-appropriate profile summary
5. Optimise for ATS (keyword matching)
6. Output as both DOCX and PDF

**Acceptance Criteria:**
- [ ] Tailored CV matches job requirements
- [ ] Keywords from job description appear in CV
- [ ] CV is 1-2 pages maximum
- [ ] Output available in DOCX and PDF formats
- [ ] Generation completes within 60 seconds

#### FR-4.3: Cover Letter Generation

**Description:** The system shall generate personalised cover letters for each application.

**Cover Letter Structure:**
1. Opening: Reference to specific role and company
2. Why this company: Research-based company connection
3. Why me: 2-3 relevant achievements mapped to job requirements
4. Closing: Call to action

**Acceptance Criteria:**
- [ ] Cover letter references specific job requirements
- [ ] Company-specific research is included
- [ ] Length is 250-400 words
- [ ] Professional but personable tone
- [ ] Output in DOCX and PDF formats

---

### 6.5 Document Storage

#### FR-5.1: Google Drive Integration

**Description:** Generated documents shall be stored in Google Drive with organised folder structure.

**Folder Structure:**
```
JobHunter/
├── CVs/
│   ├── 2025-11/
│   │   ├── Bloomberg_Quant_Analyst_CV.pdf
│   │   ├── Bloomberg_Quant_Analyst_CV.docx
│   │   └── ...
├── Cover_Letters/
│   ├── 2025-11/
│   │   ├── Bloomberg_Quant_Analyst_CL.pdf
│   │   └── ...
├── Interview_Prep/
│   ├── Bloomberg/
│   │   └── research_notes.md
└── Master_CV/
    └── master_cv.json
```

**Acceptance Criteria:**
- [ ] Files are uploaded automatically after generation
- [ ] Notion is updated with shareable Drive links
- [ ] Files are named consistently: {Company}_{Role}_{Type}.{ext}
- [ ] Monthly folders keep storage organised

---

### 6.6 Interview Preparation

#### FR-6.1: Company Research

**Description:** The system shall generate company research summaries when status changes to "Interview".

**Research Contents:**
- Company overview and mission
- Recent news (last 3 months)
- Products/services relevant to role
- Company culture signals
- Recent funding/financial performance (if available)
- Competitors and market position

#### FR-6.2: Interviewer Research

**Description:** The system shall research interviewers when names are provided.

**Research Contents:**
- Current role and tenure
- Career background
- Shared connections or interests
- Published content or talks
- Suggested conversation topics

#### FR-6.3: Question Preparation

**Description:** The system shall generate likely interview questions and suggested responses.

**Question Categories:**
- Technical questions (role-specific)
- Behavioural questions
- Company-specific questions
- Questions to ask the interviewer

---

## 7. Technical Architecture

### 7.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              NOTION                                      │
│  ┌────────────┐ ┌────────────┐ ┌────────────┐ ┌────────────┐           │
│  │    Jobs    │ │  Company   │ │   Search   │ │ Interview  │           │
│  │  Database  │ │  Watchlist │ │  Criteria  │ │    Prep    │           │
│  └────────────┘ └────────────┘ └────────────┘ └────────────┘           │
└──────────────────────────────┬──────────────────────────────────────────┘
                               │ Notion API
                               ▼
┌──────────────────────────────────────────────────────────────────────────┐
│                    PYTHON SCRIPTS (GitHub Actions)                        │
│                                                                          │
│  ┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐      │
│  │  daily_discover │    │ process_status  │    │    generate     │      │
│  │                 │    │                 │    │                 │      │
│  │ • Scrape jobs   │    │ • Poll Notion   │    │ • Tailor CV     │      │
│  │ • Score with AI │    │ • Detect status │    │ • Cover letter  │      │
│  │ • Push to Notion│    │   changes       │    │ • Interview prep│      │
│  │                 │    │ • Trigger tasks │    │ • Upload Drive  │      │
│  │ Cron: 0 7 * * * │    │ Cron: */15 * * *│    │ On-demand       │      │
│  └─────────────────┘    └─────────────────┘    └─────────────────┘      │
└──────────────────────────────────────────────────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
┌──────────────────┐ ┌──────────────────┐ ┌──────────────────┐
│    Claude API    │ │   Google Drive   │ │   Job Sources    │
│                  │ │                  │ │                  │
│ • Job scoring    │ │ • CV storage     │ │ • Indeed         │
│ • CV tailoring   │ │ • Cover letters  │ │ • LinkedIn       │
│ • Cover letters  │ │ • Prep notes     │ │ • WTFJ           │
│ • Interview prep │ │                  │ │ • Company pages  │
└──────────────────┘ └──────────────────┘ └──────────────────┘
```

### 7.2 Technology Stack

| Component | Technology | Rationale |
|-----------|------------|-----------|
| User Interface | Notion | Zero development time, mobile access, flexible views |
| Backend | Python 3.11+ | Strong language skills, excellent library ecosystem |
| Job Scraping | Playwright, BeautifulSoup, httpx | Handles JavaScript-rendered pages |
| AI | Claude API (Anthropic) | Superior technical analysis and writing |
| Document Generation | python-docx, WeasyPrint | CV and cover letter creation |
| Storage | Google Drive API | Free, accessible, shareable links |
| Scheduling | GitHub Actions | Free tier, reliable cron jobs |
| Version Control | GitHub | Code hosting and CI/CD |

### 7.3 Repository Structure

```
jobhunter/
├── README.md
├── requirements.txt
├── .env.example
├── .github/
│   └── workflows/
│       ├── daily_discover.yml      # 07:00 UTC daily
│       └── process_status.yml      # Every 15 minutes
│
├── config/
│   ├── __init__.py
│   ├── settings.py                 # Environment variables, constants
│   └── prompts.py                  # AI prompt templates
│
├── src/
│   ├── __init__.py
│   ├── scrapers/
│   │   ├── __init__.py
│   │   ├── base.py                 # Abstract base scraper
│   │   ├── indeed.py               # Indeed scraper
│   │   ├── linkedin.py             # LinkedIn scraper
│   │   ├── wtfj.py                 # Welcome to the Jungle
│   │   └── company_pages.py        # Custom company scrapers
│   │
│   ├── scoring/
│   │   ├── __init__.py
│   │   └── ai_scorer.py            # Claude API scoring logic
│   │
│   ├── notion/
│   │   ├── __init__.py
│   │   ├── client.py               # Notion API wrapper
│   │   └── sync.py                 # Push/pull operations
│   │
│   ├── generation/
│   │   ├── __init__.py
│   │   ├── cv_tailor.py            # CV tailoring with AI
│   │   ├── cover_letter.py         # Cover letter generation
│   │   ├── interview_prep.py       # Interview preparation
│   │   └── templates/
│   │       ├── cv_template.docx
│   │       └── cover_letter_template.docx
│   │
│   └── storage/
│       ├── __init__.py
│       └── gdrive.py               # Google Drive operations
│
├── scripts/
│   ├── daily_discover.py           # Main entry: discover + score + push
│   ├── process_status.py           # Poll Notion, trigger generations
│   └── manual_generate.py          # CLI for manual generation
│
├── data/
│   ├── master_cv.json              # Structured CV data
│   ├── location_weights.json       # Location scoring config
│   └── companies_backup.json       # Backup of watchlist
│
└── tests/
    ├── __init__.py
    ├── test_scrapers.py
    ├── test_scoring.py
    └── test_generation.py
```

### 7.4 Environment Variables

```bash
# .env
NOTION_API_KEY=secret_xxxxx
NOTION_JOBS_DB_ID=xxxxx
NOTION_COMPANIES_DB_ID=xxxxx
NOTION_CRITERIA_DB_ID=xxxxx
NOTION_INTERVIEW_PREP_DB_ID=xxxxx

ANTHROPIC_API_KEY=sk-ant-xxxxx

GOOGLE_DRIVE_CREDENTIALS={"type": "service_account", ...}
GOOGLE_DRIVE_FOLDER_ID=xxxxx

# Optional
LINKEDIN_EMAIL=xxxxx
LINKEDIN_PASSWORD=xxxxx
```

---

## 8. Data Models

### 8.1 Job Model

```python
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Optional

class JobStatus(Enum):
    NEW = "New"
    REVIEWING = "Reviewing"
    APPLY = "Apply"
    APPLIED = "Applied"
    INTERVIEW = "Interview"
    OFFER = "Offer"
    REJECTED = "Rejected"
    PASS = "Pass"

class JobSource(Enum):
    LINKEDIN = "LinkedIn"
    INDEED = "Indeed"
    WTFJ = "Welcome to the Jungle"
    COMPANY_PAGE = "Company Page"
    GLASSDOOR = "Glassdoor"

@dataclass
class Job:
    id: str
    title: str
    company: str
    location: str
    description: str
    url: str
    source: JobSource
    posted_date: Optional[datetime]
    discovered_date: datetime
    salary: Optional[str]
    
    # Scoring
    score: float
    score_breakdown: dict  # {"location": 25, "role": 22, ...}
    ai_analysis: str
    
    # Application
    status: JobStatus = JobStatus.NEW
    tailored_cv_url: Optional[str] = None
    cover_letter_url: Optional[str] = None
    notes: Optional[str] = None
    
    # Notion
    notion_page_id: Optional[str] = None
```

### 8.2 Score Breakdown Model

```python
@dataclass
class ScoreBreakdown:
    location: float      # 0-25
    role_alignment: float  # 0-25
    industry_fit: float   # 0-15
    seniority: float      # 0-10
    skills_match: float   # 0-15
    impact_potential: float  # 0-10
    
    @property
    def total(self) -> float:
        return (self.location + self.role_alignment + self.industry_fit + 
                self.seniority + self.skills_match + self.impact_potential)
```

### 8.3 Master CV Model

```python
@dataclass
class Experience:
    company: str
    title: str
    location: str
    start_date: str
    end_date: str
    bullets: list[dict]  # {"text": str, "tags": list, "metrics": str}

@dataclass
class MasterCV:
    personal: dict
    profiles: dict[str, str]  # {"default": "...", "analyst": "..."}
    experience: list[Experience]
    education: list[dict]
    skills: dict
    certifications: list[dict]
    interests: list[str]
```

---

## 9. AI Integration

### 9.1 AI Provider

**Primary:** Claude API (Anthropic)
- Model: claude-sonnet-4-20250514 (for speed/cost balance)
- Fallback: claude-sonnet-4-20250514 for complex tailoring

**Rationale:** Claude excels at technical analysis and professional writing, both critical for this use case.

### 9.2 Prompt Templates

#### Job Scoring Prompt

```
You are an expert career advisor helping evaluate job opportunities.

## Candidate Profile
{master_cv_summary}

## Target Preferences
- Primary location: Paris, France
- Acceptable locations: {location_list}
- Target roles: {role_types}
- Industries: Finance, FinTech, Tech, Startups
- Experience level: ~3.5 years

## Job Posting
Title: {job_title}
Company: {company}
Location: {location}
Description:
{job_description}

## Scoring Task
Score this job on each factor (provide score and brief reasoning):

1. Location Match (0-25): Paris=25, London=20, Other preferred=17, Remote=18, Other=7
2. Role Alignment (0-25): How well does this match the candidate's skills and target roles?
3. Industry Fit (0-15): Finance/FinTech/Tech/Startup alignment
4. Seniority Match (0-10): Appropriate for ~3.5 years experience?
5. Skills Match (0-15): Python, SQL, data analysis, fixed income, Power BI, etc.
6. Impact Potential (0-10): Does this role offer meaningful work with business impact?

## Output Format (JSON)
{
  "scores": {
    "location": {"score": X, "reason": "..."},
    "role_alignment": {"score": X, "reason": "..."},
    "industry_fit": {"score": X, "reason": "..."},
    "seniority": {"score": X, "reason": "..."},
    "skills_match": {"score": X, "reason": "..."},
    "impact_potential": {"score": X, "reason": "..."}
  },
  "total_score": X,
  "summary": "2-3 sentence overall assessment",
  "key_requirements": ["req1", "req2", "req3"],
  "potential_concerns": ["concern1", "concern2"]
}
```

#### CV Tailoring Prompt

```
You are an expert CV writer specialising in finance and technology roles.

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

## Output Format (JSON)
{
  "profile": "Tailored profile summary...",
  "experience": [
    {
      "company": "...",
      "title": "...",
      "dates": "...",
      "location": "...",
      "bullets": ["Reframed bullet 1", "Reframed bullet 2"]
    }
  ],
  "skills_to_highlight": ["skill1", "skill2"],
  "keywords_incorporated": ["keyword1", "keyword2"]
}
```

#### Cover Letter Prompt

```
You are an expert cover letter writer.

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
Write the cover letter as plain text.
```

### 9.3 API Usage Estimates

| Operation | Tokens (approx) | Frequency | Monthly Cost (est) |
|-----------|-----------------|-----------|-------------------|
| Job scoring | ~2,000 tokens | 30/day × 30 = 900 | ~$4.50 |
| CV tailoring | ~3,000 tokens | 20/month | ~$0.60 |
| Cover letter | ~1,500 tokens | 20/month | ~$0.30 |
| Interview prep | ~2,000 tokens | 5/month | ~$0.10 |
| **Total** | | | **~$5-10/month** |

---

## 10. Target Companies

### 10.1 Primary Watchlist

#### Tier 1: Bloomberg & Direct Competitors (Financial Data)

| Company | Paris Office | Careers URL | Priority |
|---------|--------------|-------------|----------|
| Bloomberg | Yes | bloomberg.com/careers | High |
| Refinitiv (LSEG) | Yes | refinitiv.com/careers | High |
| FactSet | Yes | factset.com/careers | High |
| S&P Global | Yes | spglobal.com/careers | High |
| MSCI | Yes | msci.com/careers | High |
| Moody's Analytics | Yes | moodys.com/careers | Medium |
| Morningstar | Yes | morningstar.com/careers | Medium |
| ICE | Yes | ice.com/careers | Medium |

#### Tier 2: FinTech & Trading Technology

| Company | Paris Office | Careers URL | Priority |
|---------|--------------|-------------|----------|
| Murex | HQ Paris | murex.com/careers | High |
| Finastra | Yes | finastra.com/careers | Medium |
| SimCorp | Yes | simcorp.com/careers | Medium |
| SS&C Technologies | Yes | ssctech.com/careers | Medium |
| Broadridge | Yes | broadridge.com/careers | Medium |

#### Tier 3: Asset Managers (Paris HQ)

| Company | Notes | Priority |
|---------|-------|----------|
| Amundi | Largest European AM | High |
| BNP Paribas AM | Large, Paris HQ | High |
| AXA Investment Managers | Paris HQ | High |
| Natixis IM | Paris HQ | Medium |
| Société Générale | Strong quant teams | Medium |

#### Tier 4: Tech Companies (Paris)

| Company | Notes | Priority |
|---------|-------|----------|
| Dataiku | AI/ML platform, HQ Paris | High |
| Algolia | Search tech, HQ Paris | Medium |
| Qonto | Business banking, HQ Paris | Medium |
| Pennylane | Accounting/FinTech, HQ Paris | Medium |
| Alan | InsurTech, HQ Paris | Medium |

### 10.2 Search Keywords

**Role Keywords:**
```
quantitative analyst, quant analyst, portfolio analyst, data analyst finance,
data scientist finance, investment analyst, research analyst, 
solution architect finance, technical architect, product manager fintech,
software engineer trading, automation engineer, BI developer,
quantitative developer, quant developer, python developer finance,
fixed income analyst, credit analyst, risk analyst
```

**Skill Keywords:**
```
python, sql, power bi, tableau, data analysis, machine learning,
fixed income, portfolio management, performance attribution,
financial modeling, quantitative analysis, automation, api,
databricks, azure, aws, pandas, numpy
```

---

## 11. Development Phases

### Phase 0: Setup (Day 1)
**Duration:** 2-3 hours

| Task | Owner | Status |
|------|-------|--------|
| Create Notion databases (Jobs, Companies, Criteria, Interview Prep) | Jevan | ☐ |
| Set up GitHub repository | Claude | ☐ |
| Create Anthropic API account | Jevan | ☐ |
| Set up Google Cloud project for Drive API | Jevan | ☐ |
| Parse Master CV into structured JSON | Claude | ☐ |
| Populate initial company watchlist | Jevan | ☐ |

### Phase 1: Job Discovery MVP (Days 2-5)
**Duration:** 4 days

| Task | Deliverable | Priority |
|------|-------------|----------|
| Indeed scraper | `src/scrapers/indeed.py` | P0 |
| LinkedIn scraper | `src/scrapers/linkedin.py` | P0 |
| Welcome to the Jungle scraper | `src/scrapers/wtfj.py` | P0 |
| AI scoring module | `src/scoring/ai_scorer.py` | P0 |
| Notion client | `src/notion/client.py` | P0 |
| Daily discovery script | `scripts/daily_discover.py` | P0 |
| GitHub Actions workflow | `.github/workflows/daily_discover.yml` | P0 |

**Milestone:** Daily job feed appearing in Notion

### Phase 2: Application Support (Days 6-10)
**Duration:** 5 days

| Task | Deliverable | Priority |
|------|-------------|----------|
| Master CV JSON structure | `data/master_cv.json` | P0 |
| CV tailoring engine | `src/generation/cv_tailor.py` | P0 |
| Cover letter generator | `src/generation/cover_letter.py` | P0 |
| Google Drive integration | `src/storage/gdrive.py` | P0 |
| Status polling script | `scripts/process_status.py` | P0 |
| GitHub Actions polling workflow | `.github/workflows/process_status.yml` | P0 |

**Milestone:** Change status to "Apply" → CV and cover letter generated

### Phase 3: Interview Preparation (Days 11-14)
**Duration:** 4 days

| Task | Deliverable | Priority |
|------|-------------|----------|
| Company research module | `src/generation/interview_prep.py` | P1 |
| Interviewer research (LinkedIn) | Integration in interview_prep.py | P1 |
| Question generation | Integration in interview_prep.py | P1 |
| Interview Prep database integration | `src/notion/sync.py` | P1 |

**Milestone:** Full interview preparation workflow

### Phase 4: Refinement (Ongoing)
**Duration:** Continuous

| Task | Priority |
|------|----------|
| Add company career page scrapers | P1 |
| Tune AI prompts based on results | P1 |
| Add more job sources (Glassdoor, AngelList) | P2 |
| Gmail integration for response tracking | P2 |
| French CV generation | P2 |

---

## 12. Cost Estimates

### Monthly Operating Costs

| Service | Cost | Notes |
|---------|------|-------|
| Notion | $0 | Free personal plan |
| GitHub Actions | $0 | Free tier (2,000 min/month) |
| Claude API | $5-15 | Based on usage estimates |
| Google Drive | $0 | Free tier (15GB) |
| **Total** | **$5-15/month** | |

### One-Time Setup Costs

| Item | Cost | Notes |
|------|------|-------|
| Domain | $0 | Not required |
| Cloud hosting | $0 | GitHub Actions sufficient |
| **Total** | **$0** | |

### Comparison to Alternatives

| Alternative | Monthly Cost | Limitations |
|-------------|--------------|-------------|
| Huntr (job tracker) | $0-40 | No AI tailoring, no auto-discovery |
| Teal | $0-29 | Limited AI, no scraping |
| JobScan | $50+ | CV optimisation only |
| Custom web app | $50-100 | Frontend development time |
| **JobHunter AI** | **$5-15** | **Full automation, AI-powered** |

---

## 13. Risks & Mitigations

### Technical Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| LinkedIn blocking scrapers | High | Medium | Use Playwright with stealth, rate limiting, fallback to other sources |
| Job site structure changes | Medium | Medium | Modular scraper design, easy to update |
| Claude API rate limits | Low | Low | Batch processing, caching |
| Notion API rate limits | Low | Low | Batch operations, retry logic |
| Google Drive quota | Low | Low | Compress files, periodic cleanup |

### Operational Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| False positive job matches | Medium | Low | Tune scoring, manual review step |
| Missed jobs (false negatives) | Medium | Medium | Multiple sources, broad keywords |
| Poor CV tailoring | Low | High | Human review before submission |
| Stale job postings | Medium | Low | Check posting date, exclude old |

### Mitigation Strategies

1. **Scraping resilience:** Use multiple sources so failure of one doesn't stop discovery
2. **Human in the loop:** All applications require manual status change (no auto-apply)
3. **Iterative improvement:** Log all AI outputs, review periodically, tune prompts
4. **Backup:** Export Notion data weekly, version control all code

---

## 14. Future Enhancements

### Phase 5+ Features (Post-MVP)

| Feature | Value | Effort | Priority |
|---------|-------|--------|----------|
| Gmail integration | Auto-track responses | Medium | P1 |
| LinkedIn profile optimiser | Improve discoverability | Medium | P2 |
| Networking suggestions | Find connections at targets | High | P2 |
| French CV translation | Apply to French-only roles | Medium | P2 |
| Salary benchmarking | Negotiate better | Medium | P3 |
| Application A/B testing | Optimise conversion | High | P3 |
| Mobile app (iOS) | Better UX | High | P3 |
| Multi-user support | Productise | High | P4 |

### Integration Opportunities

| Integration | Benefit |
|-------------|---------|
| Calendar (Google/Outlook) | Auto-add interview events |
| Slack/Discord | Push notifications |
| Notion AI | Native AI summaries |
| LinkedIn API (official) | Better data, if approved |

---

## 15. Appendices

### Appendix A: Notion Database Setup Guide

#### Step 1: Create Jobs Database
1. Open your Notion workspace
2. Create a new database (Table view)
3. Add properties as specified in FR-3.1
4. Create views: Daily Feed, To Review, Strong Matches, Paris Jobs, Applied, Kanban

#### Step 2: Create Company Watchlist Database
1. Create a new database
2. Add properties as specified in FR-3.2
3. Populate with initial companies from Section 10

#### Step 3: Create Search Criteria Database
1. Create a new database
2. Add properties as specified in FR-3.3
3. Create initial criteria set with your preferences

#### Step 4: Create Interview Prep Database
1. Create a new database
2. Add properties as specified in FR-3.4
3. Add relation to Jobs database

#### Step 5: Get Database IDs
1. Open each database as a full page
2. Copy the URL: `notion.so/{workspace}/{database_id}?v=...`
3. The database_id is the 32-character string before the `?`

### Appendix B: API Setup Guides

#### Anthropic Claude API
1. Go to console.anthropic.com
2. Create account / sign in
3. Navigate to API Keys
4. Create new key
5. Store securely (never commit to git)

#### Google Drive API
1. Go to console.cloud.google.com
2. Create new project "JobHunter"
3. Enable Google Drive API
4. Create Service Account
5. Download JSON credentials
6. Share target folder with service account email

#### Notion API
1. Go to notion.so/my-integrations
2. Create new integration
3. Give it a name (e.g., "JobHunter")
4. Copy the Internal Integration Token
5. Share each database with the integration

### Appendix C: Location Scoring Reference

```json
{
  "Paris": 100,
  "Lyon": 95,
  "France (Other)": 90,
  "Remote": 75,
  "London": 80,
  "Switzerland": 70,
  "Luxembourg": 70,
  "Montreal": 70,
  "Toronto": 70,
  "New York": 70,
  "Boston": 70,
  "San Francisco": 70,
  "Los Angeles": 65,
  "San Diego": 65,
  "Tokyo": 65,
  "Other": 30
}
```

### Appendix D: Glossary

| Term | Definition |
|------|------------|
| ATS | Applicant Tracking System — software used by companies to filter CVs |
| WTFJ | Welcome to the Jungle — French job board popular with startups |
| Suitability Score | Composite score (0-100) indicating job fit |
| Master CV | Complete CV with all experiences, used as source for tailoring |
| Tailored CV | Customised version of CV for a specific job application |

---

## Document History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 25 Nov 2025 | Jevan Cousins | Initial draft |

---

## Approval

| Role | Name | Date | Signature |
|------|------|------|-----------|
| Product Owner | Jevan Cousins | | |

---

*End of Document*
