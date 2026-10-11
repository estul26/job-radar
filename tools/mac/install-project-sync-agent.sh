#!/bin/zsh
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LABEL="com.job-radar.project-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs"
# launchd jobs can't read ~/Downloads, ~/Documents or ~/Desktop (macOS privacy
# protection), so run a copy of the sync from outside the repo.
INSTALL_DIR="$HOME/Library/Application Support/job-radar"
SYNC="$INSTALL_DIR/project_sync.py"

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

install -m 644 "$SCRIPT_DIR/../project_sync.py" "$SYNC"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/env</string>
    <string>python3</string>
    <string>$SYNC</string>
    <string>sync</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>PATH</key>
    <string>$PATH</string>
    <key>JOB_REPOSITORY</key>
    <string>$REPO</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>StartInterval</key>
  <integer>120</integer>

  <key>StandardOutPath</key>
  <string>$LOG_DIR/job-radar-project-sync.log</string>

  <key>StandardErrorPath</key>
  <string>$LOG_DIR/job-radar-project-sync-error.log</string>
</dict>
</plist>
PLIST_EOF

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"
launchctl kickstart -k "gui/$UID/$LABEL"

echo "Job Radar Project sync is installed for $REPO."
echo "It checks the board every 2 minutes while this Mac is awake."
echo "Rerun this installer after changing tools/project_sync.py."
echo
echo "Logs:"
echo "  $LOG_DIR/job-radar-project-sync.log"
echo "  $LOG_DIR/job-radar-project-sync-error.log"
