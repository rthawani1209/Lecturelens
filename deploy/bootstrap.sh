#!/usr/bin/env bash
# Sets up LectureLens on a fresh Ubuntu 24.04 server (4 vCPU / 8 GB or more), as root:
#   curl -fsSL https://raw.githubusercontent.com/rthawani1209/lecturelens/main/deploy/bootstrap.sh | bash
# Installs Docker, clones the repo to /opt/lecturelens, writes deploy/.env with fresh
# secrets, downloads the models and the MIT lectures, starts the stack behind HTTPS,
# queues the lectures for processing, and turns on updates from main (every 15
# minutes, only once that commit's GitHub checks have passed).
# Safe to run again: it keeps the existing .env and skips what's already there.
set -euo pipefail
exec > >(tee -a /var/log/lecturelens-bootstrap.log) 2>&1

repo=https://github.com/rthawani1209/lecturelens.git
dir=/opt/lecturelens
releases=https://github.com/rthawani1209/lecturelens/releases/download

if ! command -v docker >/dev/null; then
  curl -fsSL https://get.docker.com | sh
fi
apt-get update -q && apt-get install -y -q git >/dev/null

# whisper and the Next.js build both want more than 8 GB at their peaks
if ! swapon --show | grep -q .; then
  fallocate -l 4G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo "/swapfile none swap sw 0 0" >>/etc/fstab
fi

[ -d "$dir/.git" ] || git clone "$repo" "$dir"
cd "$dir"

env_file=deploy/.env
if [ ! -f "$env_file" ]; then
  ip=$(curl -fsS https://api.ipify.org || curl -fsS https://ifconfig.me)
  cat >"$env_file" <<ENV
# Written by bootstrap.sh. SITE_ADDRESS can be your own domain once its DNS points here.
SITE_ADDRESS=${SITE_ADDRESS:-$ip.sslip.io}
POSTGRES_PASSWORD=$(openssl rand -hex 24)
SECRET_KEY=$(openssl rand -hex 32)
DEMO_LOGIN=true
# a classroom behind one network address shares this
DEMO_LOGINS_PER_HOUR=30
DAILY_LECTURES_PER_USER=2
DAILY_LECTURES_TOTAL=20
DAILY_LECTURES_PER_IP=3
MAX_UPLOAD_BYTES=1073741824
ANTHROPIC_API_KEY=
SMTP_URL=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
ENV
  chmod 600 "$env_file"
fi

# updates and backups first, so they're on even if a download or seeding below fails
cp deploy/lecturelens-*.service deploy/lecturelens-*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now lecturelens-update.timer lecturelens-backup.timer

bash scripts/get_models.sh

# MIT OpenCourseWare lectures, mirrored in this repo's releases
fetch_course() {
  local folder=$1 tag=$2 out="data/ocw/$1"
  mkdir -p "$out"
  curl -fsSL --retry 3 -o "$out/manifest.json" "$releases/$tag/manifest.json"
  python3 - "$out/manifest.json" <<'PY' | while read -r f; do
import json, sys
for lec in json.load(open(sys.argv[1]))["lectures"]:
    print(lec["video"])
    if lec.get("captions"):
        print(lec["captions"])
PY
    # to a .part file first, so an interrupted run re-downloads instead of keeping half a video
    [ -s "$out/$f" ] || { curl -fsSL --retry 3 -o "$out/$f.part" "$releases/$tag/$f" &&
      mv "$out/$f.part" "$out/$f"; } || echo "skipped $f"
  done
}
fetch_course 6.006 ocw-6.006-s20
fetch_course 6.100L ocw-6.100l
fetch_course 18.06 ocw-18.06

compose="docker compose -f deploy/docker-compose.yml --env-file $env_file"
$compose up -d --build

for course in 6.006 6.100L 18.06; do
  $compose exec -T worker python /scripts/seed_demo.py "/ocw/$course" --queue ||
    echo "couldn't seed $course; run bootstrap.sh again to retry"
done

echo "LectureLens is starting at https://$(grep ^SITE_ADDRESS "$env_file" | cut -d= -f2)"
echo "Lectures are processing in the background: $compose logs -f worker"
