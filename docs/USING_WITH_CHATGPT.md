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

Feature parity is close. Codex CLI has native subagent support (parallel agents with their own context windows), so the batch-processing pattern the playbooks rely on works as designed; `AGENTS.md` tells the assistant to use it. Two setup notes:

- **Email monitoring** (`/check-emails` / "check my emails"): works once Gmail is connected to Codex, either through the ChatGPT apps connector for Gmail or a Gmail MCP server (Composio, Smithery, and Google Workspace MCP are common choices). Until it is connected, update statuses conversationally when you hear back ("mark <company> as rejected").
- **Custom agent definitions**: the role definitions in `.claude/agents/` are plain markdown procedures and work as instructions to Codex subagents directly. If you want them as first-class Codex agents, they can be mirrored as TOML files under `.codex/agents/`; this is optional, not required.

These playbooks were built and battle-tested under Claude Code; treat the first Codex sessions as a shakedown and report anything that behaves oddly as a GitHub issue.
