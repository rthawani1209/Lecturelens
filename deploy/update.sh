#!/usr/bin/env bash
# Run by lecturelens-update.timer: rebuild and restart when main has a new commit
# whose GitHub checks (CI, Deploy check, Security) have all passed. A red or
# still-running commit is skipped; the next tick looks again.
set -euo pipefail
# never at the same time as bootstrap.sh (or another tick): they share this lock
exec 9>/var/lock/lecturelens.lock
flock -n 9 || { echo "busy (bootstrap or another update running)"; exit 0; }
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

compose="docker compose -f deploy/docker-compose.yml --env-file deploy/.env"
old=$(git rev-parse HEAD)
git reset -q --hard "$new"
# a release can add a model; TF Serving won't start without it
if ! bash scripts/get_models.sh >/dev/null || ! $compose up -d --build --remove-orphans --wait --wait-timeout 600; then
  # a failed build, a migration that broke on real data, an api that never got
  # healthy: put the last good version back up (its images are cached) and let
  # the next tick try again
  # --build: the images tagged latest are the broken new ones; the old tree's
  # layers are still cached, so this takes seconds. A migration that half ran
  # is not undone; check `$compose logs migrate`.
  git reset -q --hard "$old"
  $compose up -d --build --remove-orphans || true
  echo "deploying ${new:0:7} failed; back on ${old:0:7}"
  exit 1
fi
# old images and build cache add up to gigabytes after a few deploys
docker image prune -f >/dev/null
docker builder prune -f --keep-storage 2GB >/dev/null
echo "deployed ${new:0:7}"
