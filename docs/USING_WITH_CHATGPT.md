# Using JobHunter with a ChatGPT subscription (Codex CLI)

JobHunter's heavy lifting is plain Python that never calls an AI model, so it does not care which assistant drives it. The assistant's job is the conversational layer: onboarding you, deciding what to tailor, writing prose. Claude Code is the primary supported assistant; this guide covers the OpenAI equivalent, **Codex CLI**, which signs in with a ChatGPT subscription (Plus or above).

## Setup

1. Install the prerequisites: Python 3.10+, Node, and git (on a Mac, installing the Xcode command line tools covers git).
2. Install Codex CLI and sign in with the ChatGPT account:
   ```bash
   npm install -g @openai/codex
   codex          # follow the sign-in prompt, choose "Sign in with ChatGPT"
   ```
3. Get the project:
   ```bash
   git clone https://github.com/jevancousins/jobhunter.git
   cd jobhunter
   pip install -r requirements.txt
   ```
4. Start the assistant in the project folder and ask to be set up:
   ```
   codex
   > onboard me
   ```

Codex reads this repository's `AGENTS.md` automatically, which points it at the same onboarding interview and daily-run playbooks Claude Code uses. Onboarding takes 30 to 60 minutes and builds your personal files (CV data, goals, screening answers, search configuration, company watchlist); everything about you stays on your machine and out of git.

## Day-to-day

Codex CLI has no slash-commands for this project; just ask in plain language:

- "run the daily job search" (add "just 5 roles" for a small run)
- "show me my pipeline"
- "add <company> to my watchlist"
- "mark <company> as applied" / "as rejected" / "as interviewing"
- "tailor my CV for this job: <url>"
- "write a cover letter for <url>"
- "prep me for my interview at <company>"

## Differences from Claude Code

Feature parity is close but not identical; `AGENTS.md` tells the assistant how to adapt, and these are the visible effects:

- **Smaller batches.** Claude Code isolates per-role work in sub-agents, which is what makes 50-role runs practical. Codex works inline, so keep discovery runs small (5 to 10 roles); several small runs beat one big one.
- **No `/check-emails`.** That skill reads Gmail through a Claude connector. With Codex, update statuses conversationally when you hear back ("mark <company> as rejected").
- **Notion tracker**: the local tracker (default) works fully; the Notion backend works through `scripts/notion_cli.py` but had less testing outside Claude Code. Non-Notion users lose nothing.
- **Approval prompts**: Codex will ask before running commands, as Claude Code does. The same advice applies: stay at `search` autonomy until you trust what the pipeline surfaces, and read what it asks to run.

These playbooks were built and battle-tested under Claude Code; treat the first Codex sessions as a shakedown and report anything that behaves oddly as a GitHub issue.
