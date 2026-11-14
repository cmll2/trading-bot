# Start one supervised dry-run engine as a DETACHED background process (no window, not a
# child of this shell, not a scheduled task). Logs go to var\logs\ (gitignored).
#
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-dry-run.ps1 -Strategy v0_trend
#   powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-dry-run.ps1 -Strategy plumbing
#
# The process is created through WMI (Win32_Process.Create), so it keeps running after the
# shell that started it closes. `-ExecutionPolicy Bypass` applies to that one process only;
# no system setting (execution policy, power, sleep) is changed. DRY-RUN ONLY.
param(
    [ValidateSet("v0_trend", "plumbing")][string]$Strategy = "v0_trend",
    [ValidateSet("manual", "autonomous")][string]$Approval = "autonomous"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$sup = Join-Path $PSScriptRoot "supervise.ps1"
$lock = Join-Path $root "var\state\dry-run-$Strategy.sqlite.lock"
New-Item -ItemType Directory -Force (Join-Path $root "var\logs") | Out-Null

$cmdLine = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden " +
    "-File `"$sup`" -Strategy $Strategy -Approval $Approval"
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
    -Arguments @{ CommandLine = $cmdLine; CurrentDirectory = $root }
if ($r.ReturnValue -ne 0) { throw "Win32_Process.Create failed with code $($r.ReturnValue)" }
$startedUtc = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
Write-Output "supervisor started: PID $($r.ProcessId) at $startedUtc (strategy=$Strategy approval=$Approval)"

# The engine (python) writes its PID into the store lock once it has started.
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    if (Test-Path $lock) {
        $enginePid = (Get-Content $lock -Raw).Trim()
        if ($enginePid) {
            Write-Output "engine started: PID $enginePid (lock $lock)"
            exit 0
        }
    }
}
Write-Output "engine lock not seen after 60 s: check var\logs\dry-run-$Strategy.console.log and .supervisor.log"
exit 1
