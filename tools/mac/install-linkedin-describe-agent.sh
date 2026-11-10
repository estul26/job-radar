#!/bin/zsh
# Have this Mac fill in LinkedIn job descriptions every two hours (docs/linkedin.md).
#
#   tools/mac/install-linkedin-describe-agent.sh                      # this checkout's repository
#   tools/mac/install-linkedin-describe-agent.sh you/radar-a you/radar-b   # several copies at once
#
# Opt-in: it reads LinkedIn's public posting pages without signing in, which LinkedIn's terms
# forbid for automated readers. Remove it with uninstall-linkedin-describe-agent.sh.
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHECKOUT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LABEL="com.job-radar.linkedin-describe"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs"
# launchd jobs can't read ~/Downloads, ~/Documents or ~/Desktop (macOS privacy
# protection), so radar is installed as a copy outside the repo.
INSTALL_DIR="$HOME/Library/Application Support/job-radar"
VENV="$INSTALL_DIR/venv"
RUNNER="$INSTALL_DIR/linkedin-describe.sh"
INTERVAL_SECONDS=7200

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR" "$INSTALL_DIR"

if ! command -v gh >/dev/null 2>&1; then
  echo "GitHub CLI not found. Install it with: brew install gh"
  exit 1
fi

if ! gh auth status >/dev/null 2>&1; then
  echo "GitHub CLI is not authenticated. Run: gh auth login"
  exit 1
fi

if (( $# )); then
  REPOS="$*"
else
  REPOS="${JOB_RADAR_REPO:-$(cd "$SCRIPT_DIR" && gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)}"
fi
if [[ -z "$REPOS" ]]; then
  echo "Could not tell which GitHub repository this is. Run: $0 you/job-radar"
  exit 1
fi

# The agent edits Issues as the account gh is signed in to, which is what starts the scoring.
for repo in ${=REPOS}; do
  if [[ "$(gh api "repos/$repo" --jq .permissions.push 2>/dev/null || true)" != "true" ]]; then
    echo "The GitHub account gh is using can't write to $repo. Check the name, or switch accounts: gh auth switch"
    exit 1
  fi
done

# Python 3.11-3.13 (pyproject.toml); the newest Python may not have wheels for pandas yet.
PYTHON=""
for candidate in python3.12 python3.13 python3.11 python3; do
  if command -v "$candidate" >/dev/null 2>&1; then
    PYTHON="$(command -v "$candidate")"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "Python 3.11 or later not found. Install it with: brew install python@3.12"
  exit 1
fi

echo "Installing radar into $VENV (a minute or two the first time)..."
"$PYTHON" -m venv "$VENV"
"$VENV/bin/python" -m pip install --quiet --upgrade pip
"$VENV/bin/python" -m pip install --quiet --upgrade "$CHECKOUT"
install -m 755 "$SCRIPT_DIR/linkedin-describe.sh" "$RUNNER"

cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>$LABEL</string>

  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>$RUNNER</string>
  </array>

  <key>EnvironmentVariables</key>
  <dict>
    <key>JOB_RADAR_REPOS</key>
    <string>$REPOS</string>
  </dict>

  <key>RunAtLoad</key>
  <true/>

  <key>StartInterval</key>
  <integer>$INTERVAL_SECONDS</integer>

  <key>StandardOutPath</key>
  <string>$LOG_DIR/job-radar-linkedin-describe.log</string>

  <key>StandardErrorPath</key>
  <string>$LOG_DIR/job-radar-linkedin-describe-error.log</string>
</dict>
</plist>
PLIST_EOF

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID" "$PLIST" 2>/dev/null || true
launchctl bootstrap "gui/$UID" "$PLIST"

echo "The LinkedIn description agent is installed for: $REPOS"
echo "Every two hours (and at login) it fills in the Issues labelled needs:description."
echo "Rerun this installer after updating the checkout, or to change the repositories."
echo
echo "Logs:"
echo "  $LOG_DIR/job-radar-linkedin-describe.log"
echo "  $LOG_DIR/job-radar-linkedin-describe-error.log"
