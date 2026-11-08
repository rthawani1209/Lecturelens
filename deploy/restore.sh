#!/usr/bin/env bash
# Put a backup from /var/backups/lecturelens back, replacing what's there now:
#   bash deploy/restore.sh 2026-11-06
# The site is down for the minute this takes. The database is emptied first,
# since loading a dump into tables that already have rows fails on their keys.
set -euo pipefail
cd /opt/lecturelens
day=${1:?usage: restore.sh <date>, e.g. $(ls /var/backups/lecturelens | sed -n 's/^db-\(.*\)\.sql\.gz$/\1/p' | tail -1)}
src=/var/backups/lecturelens
files="-f deploy/docker-compose.yml"
[ "$(uname -m)" = aarch64 ] && files="$files -f deploy/docker-compose.arm.yml"
compose="docker compose $files --env-file deploy/.env"

$compose stop api worker web
$compose exec -T postgres psql -v ON_ERROR_STOP=1 -U lecturelens lecturelens \
  -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
gunzip -c "$src/db-$day.sql.gz" |
  $compose exec -T postgres psql -q -v ON_ERROR_STOP=1 -U lecturelens lecturelens
if [ -f "$src/files-$day.tar.gz" ]; then
  docker run --rm -v lecturelens_appdata:/data -v "$src":/b alpine \
    sh -c "rm -rf /data/storage && tar -xzf /b/files-$day.tar.gz -C /data && chown -R 10001 /data/storage"
fi
$compose up -d
echo "restored $day"
