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
$state = Join-Path $root "var\state"
$lock = Join-Path $state "dry-run-$Strategy.sqlite.lock"
$stopFile = Join-Path $state "dry-run-$Strategy.sqlite.stop"
New-Item -ItemType Directory -Force (Join-Path $root "var\logs") | Out-Null

$running = Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
    Where-Object { $_.CommandLine -like "*supervise.ps1*-Strategy $Strategy *" }
if ($running) {
    Write-Output "REFUSED: a supervisor for $Strategy is already running (PID $($running.ProcessId -join ', '))"
    exit 2
}
if (Test-Path $stopFile) { Remove-Item $stopFile -Force }  # a stale stop request

$startUtc = (Get-Date).ToUniversalTime()
$cmdLine = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -WindowStyle Hidden " +
    "-File `"$sup`" -Strategy $Strategy -Approval $Approval"
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create `
    -Arguments @{ CommandLine = $cmdLine; CurrentDirectory = $root }
if ($r.ReturnValue -ne 0) { throw "Win32_Process.Create failed with code $($r.ReturnValue)" }
Write-Output ("supervisor started: PID $($r.ProcessId) at " + $startUtc.ToString("yyyy-MM-ddTHH:mm:ssZ") +
    " (strategy=$Strategy approval=$Approval)")

# The engine (python) writes its PID into the store lock once it has started; only a lock
# written after this start counts (a stale lock from a killed engine is ignored).
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 2
    if ((Test-Path $lock) -and ((Get-Item $lock).LastWriteTimeUtc -ge $startUtc.AddSeconds(-1))) {
        $enginePid = (Get-Content $lock -Raw).Trim()
        if ($enginePid) {
            Write-Output "engine started: PID $enginePid (lock $lock)"
            exit 0
        }
    }
}
Write-Output "engine lock not seen after 60 s: check var\logs\dry-run-$Strategy.supervisor.log and the console logs"
exit 1
