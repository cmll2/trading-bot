#!/usr/bin/env sh
# CI-style check: lint, format check, tests. Same as README.
set -eu
cd "$(dirname "$0")/.."
uv run ruff check . && uv run ruff format --check . && uv run pytest
