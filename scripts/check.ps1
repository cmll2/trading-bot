# CI-style check: lint, format check, tests. Same as README.
# Windows PowerShell 5.1 has no `&&`, so each step checks $LASTEXITCODE.
Set-Location (Join-Path $PSScriptRoot "..")
uv run ruff check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run ruff format --check .
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
uv run pytest
exit $LASTEXITCODE
