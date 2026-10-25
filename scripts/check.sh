#!/usr/bin/env bash
# Run the same lint and tests as CI before pushing.
# Postgres and model tests skip unless TEST_DATABASE_URL points at a pgvector
# database and scripts/get_models.sh has been run.
set -euo pipefail
cd "$(dirname "$0")/../backend"

ruff check . && ruff format --check .
ruff check --config pyproject.toml ../ml ../scripts
ruff format --config pyproject.toml --check ../ml ../scripts
python -m pytest -q
