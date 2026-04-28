#! /usr/bin/env bash
set -e
set -x

python app/tests_pre_start.py
alembic upgrade head # create schema before run pytest
bash scripts/test.sh "$@"