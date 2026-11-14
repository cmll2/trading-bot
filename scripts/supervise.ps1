# Supervisor loop for one dry-run engine (AD-29, docs/operations/windows-supervision.md).
#
# Runs `python -m bot.cli dry-run --strategy <S> --approval <A>` and restarts it when it
# exits with a non-zero code (crash, forced kill, network down at startup), with a backoff
# of 10 s doubling up to 5 min (reset after a run of more than 10 min).
#
# The supervisor EXITS (no restart) when:
#   - the engine exits with code 0 (graceful stop: `bot stop`, CTRL+C);
#   - the engine exits with code 6 (another live engine holds the store lock: never loop
#     against a running engine);
#   - a stop file is found before a (re)start (`bot stop` sent while the engine was down);
#     the file is removed.
#
# DRY-RUN ONLY: there is no live option here. Restarting is always safe (AD-7, AD-8, AD-9):
# the engine re-takes its lock, recovers in-flight orders and reconciles before trading.
# A persistent halt (e.g. reconcile_mismatch) survives restarts until `bot reset-halt`.
param(
    [ValidateSet("v0_trend", "plumbing")][string]$Strategy = "v0_trend",
    [ValidateSet("manual", "autonomous")][string]$Approval = "autonomous"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
$logs = Join-Path $root "var\logs"
$stopFile = Join-Path $root "var\state\dry-run-$Strategy.sqlite.stop"
New-Item -ItemType Directory -Force $logs | Out-Null
$supLog = Join-Path $logs "dry-run-$Strategy.supervisor.log"

function Write-SupLog([string]$msg) {
    $at = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    Add-Content -Path $supLog -Value "$at pid=$PID $msg" -Encoding utf8
}

Set-Location $root
$delay = 10
while ($true) {
    if (Test-Path $stopFile) {
        Remove-Item $stopFile -Force
        Write-SupLog "stop requested while the engine was down: supervisor exits"
        break
    }
    $started = Get-Date
    $stamp = $started.ToUniversalTime().ToString("yyyyMMddTHHmmssZ")
    $out = Join-Path $logs "dry-run-$Strategy-console-$stamp.out.log"
    $err = Join-Path $logs "dry-run-$Strategy-console-$stamp.err.log"
    Write-SupLog "starting engine: strategy=$Strategy approval=$Approval (DRY-RUN, SIMULATED)"
    $p = Start-Process -FilePath $py -WorkingDirectory $root -NoNewWindow -Wait -PassThru `
        -ArgumentList @("-m", "bot.cli", "dry-run", "--strategy", $Strategy, "--approval", $Approval) `
        -RedirectStandardOutput $out -RedirectStandardError $err
    $code = $p.ExitCode
    Write-SupLog "engine pid=$($p.Id) exited with code $code"
    if ($code -eq 0) {
        Write-SupLog "graceful stop: supervisor exits"
        break
    }
    if ($code -eq 6) {
        Write-SupLog "another engine holds the store lock: supervisor exits (no loop)"
        break
    }
    if (((Get-Date) - $started).TotalMinutes -gt 10) { $delay = 10 }
    Write-SupLog "restarting in $delay s"
    Start-Sleep -Seconds $delay
    $delay = [Math]::Min($delay * 2, 300)
}
