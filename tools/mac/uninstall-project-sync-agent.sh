#!/bin/zsh
set -euo pipefail

LABEL="com.job-radar.project-sync"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
INSTALL_DIR="$HOME/Library/Application Support/job-radar"

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
launchctl bootout "gui/$UID" "$PLIST" 2>/dev/null || true
rm -f "$PLIST" \
  "$INSTALL_DIR/project_sync.py" \
  "$INSTALL_DIR/project-sync-state.json" \
  "$INSTALL_DIR/sync-project-dashboard.sh" \
  "$INSTALL_DIR/sync_project_dashboard.py"
# The radar trigger may still live in the same folder.
rmdir "$INSTALL_DIR" 2>/dev/null || true

echo "Job Radar Project background sync removed."
