#!/usr/bin/env bash
# Push local commits to main, rebasing onto anything another workflow pushed
# while this job was running (LinkedIn intake, status sync, resume generation).
set -euo pipefail

for attempt in 1 2 3 4 5; do
  if git push origin HEAD:main; then
    exit 0
  fi
  echo "Push rejected (attempt $attempt); rebasing onto the latest main."
  sleep $((attempt * 3))
  git fetch origin main
  git rebase origin/main
done

echo "Could not push to main after 5 attempts." >&2
exit 1
