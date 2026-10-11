#!/bin/zsh
# Ask GitHub Actions to run the Daily Job Radar.
#
# By default the run skips itself when this morning/evening scan already
# completed, so launchd can fire it as a backup to GitHub's own schedule.
# Pass --force to always scan, the same as clicking "Run workflow".
set -euo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

# The installer sets JOB_RADAR_REPO; run by hand inside the checkout, gh finds it.
REPO="${JOB_RADAR_REPO:-$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || true)}"
if [[ -z "$REPO" ]]; then
  echo "Set JOB_RADAR_REPO (e.g. you/job-radar) or run this inside your job-radar checkout." >&2
  exit 1
fi
WORKFLOW="daily-jobs.yml"

skip_if_done=true
if [[ "${1:-}" == "--force" ]]; then
  skip_if_done=false
fi

# Right after the Mac wakes, the network can take a moment, so retry for ~5 minutes.
for attempt in {1..10}; do
  if gh workflow run "$WORKFLOW" --repo "$REPO" --ref main -f skip_if_done="$skip_if_done"; then
    echo "$(date '+%F %T') Triggered $WORKFLOW (skip_if_done=$skip_if_done)."
    echo "Watch it: gh run list --repo $REPO --workflow $WORKFLOW -L 3"
    exit 0
  fi
  echo "$(date '+%F %T') Trigger attempt $attempt failed; retrying in 30 seconds." >&2
  sleep 30
done

echo "$(date '+%F %T') Could not trigger $WORKFLOW after 10 attempts." >&2
exit 1
