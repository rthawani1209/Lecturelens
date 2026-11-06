#!/usr/bin/env bash
# Run nightly by lecturelens-backup.timer. Keeps the last 7 database dumps and the
# last 2 copies of the uploaded files in /var/backups/lecturelens. Copy that
# folder off the server too if the data matters to you.
#
# Restore: gunzip -c db-<date>.sql.gz | docker compose -f deploy/docker-compose.yml \
#   --env-file deploy/.env exec -T postgres psql -U lecturelens lecturelens
# and for files: docker run --rm -v lecturelens_appdata:/data -v /var/backups/lecturelens:/b \
#   alpine tar -xzf /b/files-<date>.tar.gz -C /data
set -euo pipefail
cd /opt/lecturelens
out=/var/backups/lecturelens
mkdir -p "$out"
day=$(date +%F)
compose="docker compose -f deploy/docker-compose.yml --env-file deploy/.env"

$compose exec -T postgres pg_dump -U lecturelens lecturelens | gzip >"$out/db-$day.sql.gz.part"
mv "$out/db-$day.sql.gz.part" "$out/db-$day.sql.gz"
docker run --rm -v lecturelens_appdata:/data:ro -v "$out":/b alpine \
  tar -czf "/b/files-$day.tar.gz.part" -C /data storage
mv "$out/files-$day.tar.gz.part" "$out/files-$day.tar.gz"

ls -1t "$out"/db-*.sql.gz | tail -n +8 | xargs -r rm
ls -1t "$out"/files-*.tar.gz | tail -n +3 | xargs -r rm
echo "backed up to $out"
