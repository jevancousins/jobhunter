#!/bin/bash
# Dead-man's switch for the daily auto-apply run.
#
# The whole point: a run that never STARTS cannot report its own failure. This
# independent job runs after the daily window and alerts if today's auto-apply
# did not finish successfully. It is deliberately tiny and claude-free, so it
# still works even when the thing it is watching is completely broken.
#
# Invoked by launchd every 30 minutes
# (see scripts/launchd/com.jobhunter.auto-apply-watchdog.example.plist)
# or by cron on Linux.
#
# Configuration (all overridable via environment variables):
#   JOBHUNTER_DIR            repo root; defaults to this script's parent directory
#   JOBHUNTER_LOG_DIR        run-log directory; defaults to $JOBHUNTER_DIR/data/auto-apply-runs
#   WATCHDOG_EARLIEST_HOUR   hour (local, 0-23) before which the watchdog stays
#                            quiet; defaults to 12 so a 09:00 daily run has time
#                            to finish before "did not run" alerts can fire
#
# Log-path warning: if you point launchd's StandardOutPath/StandardErrorPath at
# files, keep them OUT of ~/Documents. macOS attaches a com.apple.macl
# attribute there and launchd then fails to spawn the job with EX_CONFIG
# (status 78). Use /tmp or ~/Library/Logs instead.

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
JOBHUNTER_DIR="${JOBHUNTER_DIR:-$(cd "$SCRIPT_DIR/.." && pwd)}"
LOG_DIR="${JOBHUNTER_LOG_DIR:-$JOBHUNTER_DIR/data/auto-apply-runs}"
WATCHDOG_EARLIEST_HOUR="${WATCHDOG_EARLIEST_HOUR:-12}"
TODAY="$(date +%Y-%m-%d)"
NOW="$(date +%s)"
HOUR="$(date +%H)"

# Stay quiet before the daily run has had a fair chance to complete, so a
# 30-minute schedule does not alert all night about a run planned for 09:00.
if [ "$((10#$HOUR))" -lt "$WATCHDOG_EARLIEST_HOUR" ]; then
  exit 0
fi

# Alert at most once per day: the schedule fires every 30 minutes, but one
# email/notification per incident is enough.
STAMP_FILE="$LOG_DIR/watchdog_${TODAY}.alerted"
if [ -f "$STAMP_FILE" ]; then
  exit 0
fi

TODAY_LOG="$(ls -1t "$LOG_DIR"/run_${TODAY}_*.log 2>/dev/null | head -1)"

# Decide health.
#   - finished with "exit code: 0"      -> healthy, stay quiet
#   - finished non-zero                 -> alert
#   - started but no "finished" line:
#       still being worked on (header written <95 min ago) -> assume in progress, quiet
#       otherwise                                          -> alert (stalled)
#   - no run log for today at all       -> alert (the job never ran)
OK=0
REASON=""
if [ -n "$TODAY_LOG" ]; then
  if grep -q "exit code: 0 *===" "$TODAY_LOG" 2>/dev/null; then
    OK=1
  elif grep -q "run finished" "$TODAY_LOG" 2>/dev/null; then
    OK=0
    REASON="Today's run finished but with a non-zero exit code. See $TODAY_LOG"
  else
    # File mtime: `stat -f %m` is BSD/macOS; `stat -c %Y` is the GNU/Linux
    # equivalent. Try both so the script is portable.
    MOD="$(stat -f %m "$TODAY_LOG" 2>/dev/null || stat -c %Y "$TODAY_LOG" 2>/dev/null || echo 0)"
    AGE=$(( NOW - MOD ))
    if [ "$AGE" -lt 5700 ]; then
      OK=1   # in plain -p mode the log only updates at start and end; assume still running
    else
      OK=0
      REASON="Today's run started but never finished (log stale). See $TODAY_LOG"
    fi
  fi
else
  OK=0
  REASON="No auto-apply run log found for ${TODAY}: the scheduled job did NOT run."
fi

if [ "$OK" -eq 1 ]; then
  exit 0
fi

# launchctl only exists on macOS; on Linux this section degrades gracefully.
SCHEDULER_STATUS="$(launchctl list 2>/dev/null | grep jobhunter || echo '  (no jobhunter launchd jobs found, or not on macOS)')"

BODY="JobHunter auto-apply watchdog alert
$(date)

$REASON

launchd job status (a line ending in 78 = EX_CONFIG spawn failure):
$SCHEDULER_STATUS

Most recent run logs:
$(ls -1t "$LOG_DIR"/run_*.log 2>/dev/null | head -5 || echo '  (none)')"

mkdir -p "$LOG_DIR"
touch "$STAMP_FILE"

python3 "$JOBHUNTER_DIR/scripts/run_notify.py" \
  --title "JobHunter: auto-apply DID NOT run" \
  --subtitle "Watchdog alert" \
  --message "$REASON" \
  --sound "Sosumi" \
  --email-subject "[JobHunter] WATCHDOG: auto-apply did not run (${TODAY})" \
  --email-body "$BODY" \
  >> "$LOG_DIR/watchdog_${TODAY}.log" 2>&1 || true

exit 0
