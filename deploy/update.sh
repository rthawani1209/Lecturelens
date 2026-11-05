#!/usr/bin/env bash
# Run by lecturelens-update.timer: rebuild and restart when main has new commits.
set -euo pipefail
cd /opt/lecturelens
git fetch -q origin main
if [ "$(git rev-parse HEAD)" != "$(git rev-parse origin/main)" ]; then
  git reset -q --hard origin/main
  docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build --remove-orphans
  docker image prune -f >/dev/null
fi
