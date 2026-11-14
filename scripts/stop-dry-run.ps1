# Graceful stop of one dry-run engine (AD-29): asks it to stop after its current tick
# (`bot stop` writes the stop file), waits for the engine lock to be released, and the
# supervisor then exits on the engine's exit code 0.
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop-dry-run.ps1 -Strategy v0_trend
param([ValidateSet("v0_trend", "plumbing")][string]$Strategy = "v0_trend")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$lock = Join-Path $root "var\state\dry-run-$Strategy.sqlite.lock"
Set-Location $root
& $py -m bot.cli stop --strategy $Strategy
for ($i = 0; $i -lt 45; $i++) {
    if (-not (Test-Path $lock)) {
        Write-Output "engine $Strategy stopped (lock released)"
        exit 0
    }
    Start-Sleep -Seconds 2
}
Write-Output "engine $Strategy still holds $lock after 90 s; see docs/operations/windows-supervision.md"
exit 1
