#! /usr/bin/env bash

set -euo pipefail
set -x

PYTHON_BIN="/app/.venv/bin/python"
ALEMBIC_BIN="/app/.venv/bin/alembic"

# Let the DB start
"${PYTHON_BIN}" -m app.pre_start

# Run migrations
"${ALEMBIC_BIN}" upgrade head

# Create initial data in DB
"${PYTHON_BIN}" -m app.initial_data