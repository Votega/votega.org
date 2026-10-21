#!/usr/bin/env bash
# Commit and push _data/freshness/ (written by record_data_checked.py) after an update
# workflow's own data commit. Separate from that commit because the data step often skips
# committing a quiet run; this tiny file is what tells the site the source was still
# checked. Does nothing when the recorded day has not changed.
set -euo pipefail
git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add -f _data/freshness
if git diff --cached --quiet; then
  echo "freshness: no change"
  exit 0
fi
git commit -m "${1:-Record data check date}"
for attempt in 1 2 3; do
  if git pull --rebase origin main && git push; then
    exit 0
  fi
  echo "Push attempt $attempt failed, retrying..."
  sleep 5
done
echo "::error::freshness push failed after 3 attempts"
exit 1
