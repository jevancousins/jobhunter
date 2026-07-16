#!/bin/bash
# Weekly retrospective: launches Claude Code to run the full retrospective
# and generate a human-readable weekly summary.
# Invoked by launchd (com.jobhunter.weekly-retrospective.plist) every Sunday at 19:00,
# or run manually: bash scripts/weekly_retrospective.sh
#
# Configuration (all overridable via environment variables):
#   JOBHUNTER_DIR      repo root; defaults to this script's parent directory
#   CLAUDE_BIN         claude binary; defaults to whatever is on PATH
#   JOBHUNTER_HEADLESS set to 1 to allow the unattended --dangerously-skip-permissions
#                      run. Without it this script explains and exits: a headless run
#                      cannot prompt you for permission, so only enable it once you
#                      trust the retrospective pipeline.

set -euo pipefail

JOBHUNTER_DIR="${JOBHUNTER_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
LOG_DIR="${JOBHUNTER_LOG_DIR:-$JOBHUNTER_DIR/data/auto-apply-runs}"
TIMESTAMP=$(date +%Y-%m-%d_%H%M)
LOG_FILE="$LOG_DIR/retro_${TIMESTAMP}.log"

if [ -z "$CLAUDE_BIN" ]; then
  echo "claude binary not found; install Claude Code or set CLAUDE_BIN" >&2
  exit 1
fi

if [ "${JOBHUNTER_HEADLESS:-0}" != "1" ]; then
  cat >&2 <<'MSG'
Refusing to run headless without JOBHUNTER_HEADLESS=1.
This script invokes Claude Code with --dangerously-skip-permissions, which
lets it act without asking. Run the retrospective interactively first
(python scripts/retrospective.py), and set JOBHUNTER_HEADLESS=1 in the
launchd plist once you trust it.
MSG
  exit 1
fi

mkdir -p "$LOG_DIR"

echo "=== Weekly retrospective started: $(date) ===" >> "$LOG_FILE"

cd "$JOBHUNTER_DIR"

"$CLAUDE_BIN" \
  --dangerously-skip-permissions \
  -p "Run the weekly deep retrospective for the auto-apply pipeline.

1. Run: python scripts/retrospective.py (full mode with Notion queries) to regenerate data/apply-intelligence.json.
2. Read the generated intelligence file.
3. If a previous weekly retro exists in data/auto-apply-runs/, read the most recent one to compare trends.
4. Write a human-readable weekly summary to data/auto-apply-runs/weekly-retro-$(date +%Y-%m-%d).md containing:
   - Overall stats: total submitted, positive outcomes, rejected, overall response rate, trend vs last week
   - Top performing variants by response rate (min 3 submissions)
   - Underperforming variants with 0% response rate and 5+ resolved outcomes
   - ATS channel breakdown
   - Skip hosts and escalation playbook updates
   - Tailoring insights if available
   - Walker candidates: any unknown-ATS host with 15+ escalations where the edge-case agent succeeded >50%
   - 3-5 actionable recommendations
5. Print a brief summary of the most important findings.

Use British English, no em-dashes." \
  >> "$LOG_FILE" 2>&1

EXIT_CODE=$?

echo "" >> "$LOG_FILE"
echo "=== Weekly retrospective finished: $(date) (exit code: $EXIT_CODE) ===" >> "$LOG_FILE"

# Keep only the last 12 retro logs (3 months)
ls -1t "$LOG_DIR"/retro_*.log 2>/dev/null | tail -n +13 | xargs rm -f 2>/dev/null

exit $EXIT_CODE
