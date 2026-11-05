#!/usr/bin/env bash
# Browser tests against a real, freshly seeded stack: Postgres, Redis, the API,
# a Celery worker running the real pipeline, and the built web app.
#
# Needs: Postgres with pgvector at E2E_DATABASE_URL, Redis, ffmpeg, espeak-ng,
# tesseract, the models (scripts/get_models.sh), and a Python env with the backend
# installed. CI runs this same script.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

export DATABASE_URL="${E2E_DATABASE_URL:-postgresql://lecturelens:lecturelens@localhost:5432/lecturelens_e2e}"
export REDIS_URL="${E2E_REDIS_URL:-redis://localhost:6379/5}"
api_port="${E2E_API_PORT:-8300}"
web_port="${E2E_WEB_PORT:-3300}"
run="$(mktemp -d)"
export STORAGE_BACKEND=local LOCAL_STORAGE_DIR="$run/storage" UPLOAD_DIR="$run/uploads"
export MODELS_DIR="$root/models" APP_URL="http://localhost:$web_port"
export API_URL="http://localhost:$api_port"
# small enough that the "too big" test doesn't need gigabytes
export MAX_UPLOAD_BYTES=$((50 * 1024 * 1024))
# small chunks so even the short test video goes up in several pieces
export UPLOAD_CHUNK_BYTES=$((32 * 1024))
export E2E_API_LOG="$run/api.log" E2E_SEED="$run/seed.json" E2E_BASE_URL="http://localhost:$web_port"

for port in "$api_port" "$web_port"; do
  if curl -s -o /dev/null "http://localhost:$port"; then
    echo "port $port is already in use; stop whatever is running there" >&2
    exit 1
  fi
done

# each service runs in its own process group so cleanup also stops the
# children (npx -> next-server, celery's pool)
pids=()
cleanup() {
  for p in "${pids[@]}"; do kill -- "-$p" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT

python - <<PY
import psycopg
url = "$DATABASE_URL"
admin, name = url.rsplit("/", 1)
with psycopg.connect(admin + "/postgres", autocommit=True) as c:
    c.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
    c.execute(f'CREATE DATABASE "{name}"')
with psycopg.connect(url, autocommit=True) as c:
    c.execute("CREATE EXTENSION IF NOT EXISTS vector")
PY
redis-cli -u "$REDIS_URL" flushdb >/dev/null 2>&1 || true
(cd backend && python -m lecturelens.db.migrate)
(cd backend && python ../scripts/e2e_seed.py "$E2E_SEED")

(cd backend && exec setsid uvicorn lecturelens.api.main:app --port "$api_port" >"$E2E_API_LOG" 2>&1) &
pids+=($!)
(cd backend && exec setsid celery -A lecturelens.worker worker -l warning -P solo >"$run/worker.log" 2>&1) &
pids+=($!)

cd frontend
npx next build >"$run/build.log" 2>&1 || { cat "$run/build.log"; exit 1; }
(PORT="$web_port" exec setsid npx next start >"$run/web.log" 2>&1) &
pids+=($!)

for _ in $(seq 60); do
  curl -sf "http://localhost:$api_port/health" >/dev/null && curl -sf "$E2E_BASE_URL" >/dev/null && break
  sleep 1
done

status=0
npx playwright test "$@" || status=$?
if [ "$status" -ne 0 ]; then
  echo "--- api log"; tail -50 "$E2E_API_LOG"
  echo "--- worker log"; tail -50 "$run/worker.log"
fi
[ "$status" -eq 0 ] && rm -rf "$run"
exit "$status"
