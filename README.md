# JobHunter AI

Personal job search automation platform that streamlines job discovery, application, and interview preparation using AI.

## Features

- **Automated Discovery**: Daily scraping of job postings from Indeed, LinkedIn, and Welcome to the Jungle
- **AI-Powered Scoring**: Intelligent suitability scoring using Claude API with weighted criteria
- **One-Click Applications**: Automated CV tailoring and cover letter generation
- **Interview Preparation**: AI-generated company research and question preparation
- **Notion Integration**: Zero-frontend UI using Notion as the database and dashboard

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

Required keys:
- `NOTION_API_KEY`: Your Notion integration token
- `NOTION_JOBS_DB_ID`: Jobs database ID
- `ANTHROPIC_API_KEY`: Claude API key

### 3. Set Up Notion Databases

Create the following databases in Notion with the properties specified in the PRD:
- Jobs Database
- Company Watchlist
- Search Criteria
- Interview Prep

Share each database with your Notion integration.

### 4. Run Daily Discovery

```bash
python scripts/daily_discover.py
```

## Project Structure

```
jobhunter/
├── config/              # Configuration and prompts
├── src/
│   ├── scrapers/       # Job board scrapers
│   ├── scoring/        # AI scoring module
│   ├── notion/         # Notion integration
│   ├── generation/     # CV/cover letter generation
│   └── storage/        # Google Drive integration
├── scripts/            # Main entry point scripts
├── data/               # Master CV and config data
└── .github/workflows/  # GitHub Actions for scheduling
```

## Scoring System

Jobs are scored 0-100 based on:
- **Location Match (25%)**: Paris=100, London=80, Remote=75
- **Role Alignment (25%)**: Match to target role types
- **Industry Fit (15%)**: Finance/FinTech/Tech alignment
- **Seniority Match (10%)**: Appropriate for experience level
- **Skills Match (15%)**: Technical skills alignment
- **Impact Potential (10%)**: Meaningful work signals

Jobs scoring ≥60 are added to Notion; ≥80 are flagged as strong matches.

## Automation

### GitHub Actions

- **Daily Discovery** (`daily_discover.yml`): Runs at 07:00 UTC daily
- **Status Processing** (`process_status.yml`): Runs every 15 minutes

### Status-Based Triggers

- Change status to **"Apply"** → Generates tailored CV and cover letter
- Change status to **"Interview"** → Generates interview prep materials

## Cost Estimate

~$5-15/month total:
- Notion: Free
- GitHub Actions: Free tier
- Claude API: ~$5-15 based on usage
- Google Drive: Free tier
