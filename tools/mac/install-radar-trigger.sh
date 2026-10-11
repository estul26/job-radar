#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.job-radar.trigger"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs"
# launchd jobs can't read ~/Downloads, ~/Documents or ~/Desktop (macOS privacy
# protection), so run a copy of the trigger from outside the repo.
INSTALL_DIR="$HOME/Library/Application Support/job-radar"
TRIGGER="$INSTALL_DIR/trigger-radar.sh"

# Local times to ask for a scan: a few minutes after the morning and evening schedules in
# .github/workflows/daily-jobs.yml. Change them together.
MORNING_HOUR=7 MORNING_MINUTE=20
EVENING_HOUR=16 EVENING_MINUTE=20

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR" "$INSTALL_DIR"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI not found. Install it with: brew install gh"
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login"
  exit 1
fi

# The GitHub repository of this checkout, for the copy that runs outside it.
REPO="${JOB_RADAR_REPO:-$(cd "$SCRIPT_DIR" && gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)}"
if [[ -z "$REPO" ]]; then
  echo "Could not tell which GitHub repository this is. Run: JOB_RADAR_REPO=you/job-radar $0"
  exit 1
fi

install -m 755 "$SCRIPT_DIR/trigger-radar.sh" "$TRIGGER"

# If the Mac is asleep at a trigger time, launchd runs the missed trigger once it wakes.
# RunAtLoad also covers a Mac that was off at trigger time: logging in fires a
# backup check, which only scans if the current morning/evening scan is missing.
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>$TRIGGER</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>JOB_RADAR_REPO</key>
    <string>$REPO</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>StartCalendarInterval</key>
  <array>
    <dict>
      <key>Hour</key>
      <integer>$MORNING_HOUR</integer>
      <key>Minute</key>
      <integer>$MORNING_MINUTE</integer>
    </dict>
    <dict>
      <key>Hour</key>
      <integer>$EVENING_HOUR</integer>
      <key>Minute</key>
      <integer>$EVENING_MINUTE</integer>
    </dict>
  </array>

  <key>StandardOutPath</key>
  <string>$LOG_DIR/job-radar-trigger.log</string>

  <key>StandardErrorPath</key>
  <string>$LOG_DIR/job-radar-trigger-error.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"

morning="$(printf '%02d:%02d' "$MORNING_HOUR" "$MORNING_MINUTE")"
evening="$(printf '%02d:%02d' "$EVENING_HOUR" "$EVENING_MINUTE")"
echo "Job Radar trigger is installed for $REPO."
echo "It asks GitHub to run the radar at $morning and $evening (or when the Mac wakes/logs in)."
echo "Runs skip themselves when GitHub's own schedule already did that scan."
echo "Rerun this installer after changing tools/mac/trigger-radar.sh."
echo
echo "Logs:"
echo "  $LOG_DIR/job-radar-trigger.log"
echo "  $LOG_DIR/job-radar-trigger-error.log"
