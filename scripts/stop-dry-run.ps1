# Graceful stop of one dry-run engine (AD-29): asks it to stop after its current tick
# (`bot stop` writes the stop file), then waits until the engine lock is released AND the
# supervisor process has exited (it exits on the engine's code 0, or consumes the stop file
# itself if the engine was down).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop-dry-run.ps1 -Strategy v0_trend
param([ValidateSet("v0_trend", "plumbing")][string]$Strategy = "v0_trend")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$lock = Join-Path $root "var\state\dry-run-$Strategy.sqlite.lock"
Set-Location $root
& $py -m bot.cli stop --strategy $Strategy
if ($LASTEXITCODE -ne 0) {
    Write-Output "bot stop failed with code $LASTEXITCODE"
    exit 1
}
function Get-Supervisor {
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like "*supervise.ps1*-Strategy $Strategy *" }
}
for ($i = 0; $i -lt 60; $i++) {
    if (-not (Test-Path $lock) -and -not (Get-Supervisor)) {
        Write-Output "engine $Strategy stopped (lock released, supervisor gone)"
        exit 0
    }
    Start-Sleep -Seconds 2
}
Write-Output "engine $Strategy not stopped after 120 s (lock present: $(Test-Path $lock)); see docs/operations/windows-supervision.md"
exit 1
