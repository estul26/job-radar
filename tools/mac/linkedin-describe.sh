#!/bin/zsh
# Fill in the LinkedIn Issues waiting for a description, in each of your Job Radar repositories.
#
# The installer (install-linkedin-describe-agent.sh) copies this next to its own Python
# environment and has launchd run it every two hours. By hand:
#   JOB_RADAR_REPOS="you/job-radar you/job-radar-two" tools/mac/linkedin-describe.sh
set -uo pipefail

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"

INSTALL_DIR="${JOB_RADAR_HOME:-$HOME/Library/Application Support/job-radar}"
RADAR="$INSTALL_DIR/venv/bin/radar"
if [[ ! -x "$RADAR" ]]; then
  echo "radar isn't installed in $INSTALL_DIR/venv. Run tools/mac/install-linkedin-describe-agent.sh." >&2
  exit 1
fi
if [[ -z "${JOB_RADAR_REPOS:-}" ]]; then
  echo "Set JOB_RADAR_REPOS, e.g. JOB_RADAR_REPOS=\"you/job-radar\"." >&2
  exit 1
fi

# Always act as the GitHub account the installer was run for, whichever account gh has active now.
if [[ -n "${JOB_RADAR_GH_USER:-}" ]]; then
  if ! GH_TOKEN="$(gh auth token --user "$JOB_RADAR_GH_USER" 2>/dev/null)" || [[ -z "$GH_TOKEN" ]]; then
    echo "$(date '+%F %T') gh isn't signed in as $JOB_RADAR_GH_USER. Run: gh auth login" >&2
    exit 1
  fi
  export GH_TOKEN
fi

# Outside the checkout: launchd can't read ~/Downloads, ~/Documents or ~/Desktop.
cd "$INSTALL_DIR"
failed=0
for repo in ${=JOB_RADAR_REPOS}; do
  echo "$(date '+%F %T') $repo"
  GITHUB_REPOSITORY="$repo" "$RADAR" linkedin-describe --max "${JOB_RADAR_DESCRIBE_MAX:-15}"
  code=$?
  if (( code == 4 )); then
    echo "$(date '+%F %T') LinkedIn refused a request, so the remaining repositories wait for the next run." >&2
    exit 0
  fi
  (( code == 0 )) || failed=1
  sleep 5
done
exit $failed
