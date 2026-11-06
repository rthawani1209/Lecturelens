#!/usr/bin/env bash
# Run by lecturelens-update.timer: rebuild and restart when main has a new commit
# whose GitHub checks (CI, Deploy check, Security) have all passed. A red or
# still-running commit is skipped; the next tick looks again.
set -euo pipefail
cd /opt/lecturelens
git fetch -q origin main
new=$(git rev-parse origin/main)
[ "$(git rev-parse HEAD)" = "$new" ] && exit 0

checks=$(curl -fsS "https://api.github.com/repos/rthawani1209/lecturelens/commits/$new/check-runs?per_page=100")
verdict=$(python3 -c '
import json, sys
runs = json.load(sys.stdin)["check_runs"]
if not runs or any(r["status"] != "completed" for r in runs):
    print("wait")
elif all(r["conclusion"] in ("success", "skipped", "neutral") for r in runs):
    print("green")
else:
    print("red")
' <<<"$checks")
if [ "$verdict" != green ]; then
  echo "not deploying ${new:0:7}: checks are $verdict"
  exit 0
fi

old=$(git rev-parse HEAD)
git reset -q --hard "$new"
if ! docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build --remove-orphans; then
  # e.g. a font download timed out mid-build: go back so the next tick tries again
  git reset -q --hard "$old"
  echo "build of ${new:0:7} failed; will retry"
  exit 1
fi
# old images and build cache add up to gigabytes after a few deploys
docker image prune -f >/dev/null
docker builder prune -f --keep-storage 2GB >/dev/null
echo "deployed ${new:0:7}"
