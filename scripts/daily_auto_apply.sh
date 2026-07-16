#!/bin/bash
# Daily auto-apply: launches Claude Code non-interactively to run /auto-apply --discover
# Invoked by launchd (see scripts/launchd/com.jobhunter.auto-apply.example.plist)
# or by cron on Linux.
#
# Configuration (all overridable via environment variables):
#   JOBHUNTER_DIR       repo root; defaults to this script's parent directory
#   JOBHUNTER_LOG_DIR   run-log directory; defaults to $JOBHUNTER_DIR/data/auto-apply-runs
#   CLAUDE_BIN          claude binary; defaults to `command -v claude`
#   MAX_SECONDS         watchdog timeout; defaults to 5400 (90 minutes)
#   JOBHUNTER_HEADLESS  must be set to 1 to actually run (see safety gate below)
#
# Notes:
#  - Uses `/auto-apply --discover`: a bare `/auto-apply` only asks which mode
#    to run and exits without applying, so the daily run must pass --discover.
#  - A watchdog kills the claude process after MAX_SECONDS so a headless hang
#    cannot silently stall the day (macOS ships no `timeout` binary by default).
#  - errexit is intentionally NOT set, so the claude exit code is captured even
#    on non-zero exits and the run is always logged + rotated.
#  - If you point launchd's own StandardOutPath/StandardErrorPath at files,
#    keep them OUT of ~/Documents: macOS attaches a com.apple.macl attribute
#    there and launchd then fails to spawn the job with EX_CONFIG (status 78).
#    Use /tmp or ~/Library/Logs instead. JOBHUNTER_LOG_DIR (written by this
#    script, not launchd) is not affected by this.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
JOBHUNTER_DIR="${JOBHUNTER_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
LOG_DIR="${JOBHUNTER_LOG_DIR:-$JOBHUNTER_DIR/data/auto-apply-runs}"
TIMESTAMP=$(date +%Y-%m-%d_%H%M)
LOG_FILE="$LOG_DIR/run_${TIMESTAMP}.log"
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
MAX_SECONDS="${MAX_SECONDS:-5400}"   # 90-minute watchdog

if [ -z "$CLAUDE_BIN" ] || [ ! -x "$CLAUDE_BIN" ]; then
  echo "Error: claude binary not found. Install Claude Code or set CLAUDE_BIN." >&2
  exit 1
fi

# ---------------------------------------------------------------------------
# SAFETY GATE: this script runs Claude Code with --dangerously-skip-permissions
# because a headless launchd/cron run has no terminal to answer permission
# prompts on. That flag lets the agent execute tools WITHOUT asking first,
# which includes submitting real job applications on your behalf.
# Only set JOBHUNTER_HEADLESS=1 once you have run the pipeline interactively,
# reviewed what it does, and trust it end to end.
# ---------------------------------------------------------------------------
if [ "${JOBHUNTER_HEADLESS:-0}" != "1" ]; then
  cat >&2 <<'EOF'
Refusing to run: JOBHUNTER_HEADLESS is not set to 1.

This script invokes Claude Code with --dangerously-skip-permissions, meaning
it will act (including submitting applications) without asking. Before
enabling it:
  1. Run /auto-apply interactively a few times and review its behaviour.
  2. Check autonomy.level in data/search_config.json is what you intend.
  3. Then set JOBHUNTER_HEADLESS=1 in your launchd plist or cron environment
     (see scripts/launchd/com.jobhunter.auto-apply.example.plist).
EOF
  exit 1
fi

mkdir -p "$LOG_DIR"

echo "=== Auto-apply run started: $(date) ===" >> "$LOG_FILE"

cd "$JOBHUNTER_DIR"

EXIT_CODE=0
"$CLAUDE_BIN" \
  --dangerously-skip-permissions \
  -p "/auto-apply --discover" \
  >> "$LOG_FILE" 2>&1 &
CLAUDE_PID=$!

# Watchdog: kill claude if it runs past MAX_SECONDS
( sleep "$MAX_SECONDS"; kill -0 "$CLAUDE_PID" 2>/dev/null && kill -TERM "$CLAUDE_PID" 2>/dev/null ) &
WATCHDOG_PID=$!

wait "$CLAUDE_PID" || EXIT_CODE=$?

# Stop the watchdog if claude finished on its own
kill "$WATCHDOG_PID" 2>/dev/null || true

if ! kill -0 "$CLAUDE_PID" 2>/dev/null && [ "$EXIT_CODE" -ne 0 ]; then
  # If the watchdog fired, EXIT_CODE will reflect the TERM signal (143)
  if [ "$EXIT_CODE" -eq 143 ]; then
    echo "" >> "$LOG_FILE"
    echo "!!! Auto-apply TIMED OUT after ${MAX_SECONDS}s and was killed by the watchdog !!!" >> "$LOG_FILE"
  fi
fi

echo "" >> "$LOG_FILE"
echo "=== Auto-apply run finished: $(date) (exit code: $EXIT_CODE) ===" >> "$LOG_FILE"

# --- Notify (desktop + optional email) so the outcome is never silent ---
COUNTS="$(grep -oE 'applied=[0-9]+, escalated=[0-9]+, failed=[0-9]+' "$LOG_FILE" 2>/dev/null | tail -1)"
if [ "$EXIT_CODE" -eq 0 ]; then
  STATUS="OK Auto-apply succeeded"
  MSG="${COUNTS:-Run completed (exit 0)}"
elif [ "$EXIT_CODE" -eq 143 ]; then
  STATUS="TIMEOUT Auto-apply timed out"
  MSG="Killed by watchdog after ${MAX_SECONDS}s"
else
  STATUS="FAILED Auto-apply error"
  MSG="Exit code ${EXIT_CODE}. ${COUNTS}"
fi
EMAIL_BODY="$STATUS
$(date)
Exit code: $EXIT_CODE
${COUNTS:+Counts: $COUNTS}
Log: $LOG_FILE

--- last 45 lines of run log ---
$(tail -n 45 "$LOG_FILE" 2>/dev/null)"
python3 "$JOBHUNTER_DIR/scripts/run_notify.py" \
  --title "JobHunter: daily auto-apply" \
  --subtitle "$STATUS" \
  --message "$MSG" \
  --email-subject "[JobHunter] $STATUS ($(date +%Y-%m-%d))" \
  --email-body "$EMAIL_BODY" \
  >> "$LOG_FILE" 2>&1 || true

# Keep only the last 30 run logs
ls -1t "$LOG_DIR"/run_*.log 2>/dev/null | tail -n +31 | xargs rm -f 2>/dev/null

exit $EXIT_CODE
