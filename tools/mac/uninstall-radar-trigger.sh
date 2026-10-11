#!/bin/zsh
set -euo pipefail

LABEL="com.job-radar.trigger"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
INSTALL_DIR="$HOME/Library/Application Support/job-radar"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID" "$PLIST" 2>/dev/null || true
rm -f "$PLIST" "$INSTALL_DIR/trigger-radar.sh"
# The Project sync agent may still live in the same folder.
rmdir "$INSTALL_DIR" 2>/dev/null || true

echo "Job Radar trigger removed."
