# Registers a Windows Task Scheduler task that runs one supervised dry-run engine at logon
# and restarts it on failure (AD-29, decision 2026-11-11). OPERATOR ACTION: this script is
# provided, never run by the build. Run it yourself, once per strategy:
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Strategy v0_trend
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\register-task.ps1 -Strategy plumbing
#
# Remove with:  Unregister-ScheduledTask -TaskName "trading-bot dry-run <strategy>" -Confirm:$false
#
# DRY-RUN ONLY (plumbing can never run live; this script has no live option). The task runs
# scripts\supervise.ps1, which restarts the engine after a crash or a forced kill; the task's
# own restart-on-failure covers the supervisor itself. Power and sleep settings are NOT
# changed here: see docs/operations/windows-supervision.md (sleep blocks trading through the
# stale-data rules, and the engine reconciles after waking).
param(
    [ValidateSet("v0_trend", "plumbing")][string]$Strategy = "v0_trend",
    [ValidateSet("manual", "autonomous")][string]$Approval = "autonomous"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$sup = Join-Path $PSScriptRoot "supervise.ps1"
$name = "trading-bot dry-run $Strategy"

$action = New-ScheduledTaskAction -Execute "powershell.exe" -WorkingDirectory $root `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$sup`" -Strategy $Strategy -Approval $Approval"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -MultipleInstances IgnoreNew -StartWhenAvailable `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
$principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Principal $principal -Description "trading-bot DRY-RUN ($Strategy, approval=$Approval): SIMULATED orders only" | Out-Null
Write-Output "registered task '$name' (at logon, restart on failure). Start now with: Start-ScheduledTask -TaskName '$name'"
