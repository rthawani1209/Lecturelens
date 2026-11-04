#!/usr/bin/env bash
# Run the same lint and tests as CI before pushing.
# Postgres and model tests skip unless TEST_DATABASE_URL points at a pgvector
# database and scripts/get_models.sh has been run.
set -euo pipefail
cd "$(dirname "$0")/../backend"

# separate lines: with set -e, a failure on the left of && would not stop the script
ruff check .
ruff format --check .
ruff check --config pyproject.toml ../ml ../scripts
ruff format --config pyproject.toml --check ../ml ../scripts
python -m pytest -q

# SavedModel tests need TensorFlow, which lives in the ml env (ml/requirements.txt)
ml_python="${ML_PYTHON:-../ml/.venv/bin/python}"
if [ ! -x "$ml_python" ]; then
  echo "no ml env at $ml_python; create it with ml/requirements.txt or set ML_PYTHON" >&2
  exit 1
fi
"$ml_python" -m pytest -q ../ml/tests

# frontend: the same steps as the CI frontend job
cd ../frontend
if [ ! -d node_modules ]; then npm ci; fi
npx prettier --check .
npx eslint --max-warnings 0 .
npx tsc --noEmit
npx vitest run
npm run build
