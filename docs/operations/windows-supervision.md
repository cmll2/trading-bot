# Running the dry-run on this Windows PC

Everything here is **DRY-RUN: simulated orders on a paper account, priced from Kraken's
public market data**. No API key is used and no real order can be placed. Two engines can run
side by side, each on its own store and lock:

| Engine | Store | Log (JSON lines) |
|---|---|---|
| v0 (daily trend) | `var/state/dry-run-v0_trend.sqlite` | `var/logs/dry-run-v0_trend.log` |
| plumbing (hourly, no edge, dry-run only) | `var/state/dry-run-plumbing.sqlite` | `var/logs/dry-run-plumbing.log` |

Each engine also writes `var/logs/dry-run-<strategy>.console.log` (stdout/stderr) and, when
started through the supervisor, `var/logs/dry-run-<strategy>.supervisor.log`. Daily store
backups go to `var/backups/` (30 kept). `var/` is gitignored.

All commands below run from the repository root in PowerShell.

## Start (detached, no scheduled task)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-dry-run.ps1 -Strategy v0_trend
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start-dry-run.ps1 -Strategy plumbing
```

The script creates the supervisor (`scripts\supervise.ps1`) through WMI, so it is not a child
of your shell and keeps running when the shell closes. It prints the supervisor PID and,
once the engine has taken its lock, the engine (python) PID. `-Approval autonomous` is the
default of these scripts, because nobody is there to approve an unattended run;
`config.yaml` keeps `execution.approval: manual` for the first live weeks. The override is
logged at start (`execution.approval overridden for this dry-run session`).

## Check health

```powershell
uv run bot status --strategy v0_trend      # exit code 0 = healthy, 1 = not healthy
uv run bot status --strategy plumbing
```

`bot status` opens the store read-only and prints the mode (DRY-RUN (SIMULATED)), the run and
its PID (running / DEAD / stopped), the **last heartbeat** and its age (HEALTHY when within 3
ticks, i.e. 90 s), the kill switch, active halts, equity, the active intent, counts of
signals/orders/fills, errors in the last 24 h, reconciliation mismatches, API latency and
rate-limit events, and pending operator actions.

Other views: `uv run bot journal --strategy v0_trend` (every signal with its outcome and a
would-have-returned estimate for untraded signals).

## View logs

```powershell
Get-Content var\logs\dry-run-v0_trend.log -Tail 20 -Wait          # JSON lines, redacted
Get-Content var\logs\dry-run-plumbing.log -Tail 20 -Wait
Get-Content var\logs\dry-run-v0_trend.supervisor.log -Tail 20      # starts, exits, restarts
Get-Content var\logs\dry-run-v0_trend.console.log -Tail 50         # anything printed to stderr
```

## Stop (graceful)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop-dry-run.ps1 -Strategy v0_trend
# or: uv run bot stop --strategy v0_trend
```

`bot stop` writes `var/state/dry-run-<strategy>.sqlite.stop`. The engine checks it every
second between ticks, finishes the tick in progress, commits, records
`runs.stop_reason = graceful stop: stop file ...`, releases its lock and exits with code 0;
the supervisor then exits too. In a console window, CTRL+C or CTRL+BREAK do the same.

## Forced restart (the M3 check: a forced restart must be survived)

Kill the **engine** process the hard way, as Task Manager's "End task" would:

```powershell
$enginePid = Get-Content var\state\dry-run-v0_trend.sqlite.lock    # or the PID in bot status
Stop-Process -Id $enginePid -Force
```

The supervisor logs `engine exited with code 1` (or `-1`) and starts the engine again after
10 s. On start the engine takes over the stale lock (the PID is gone), then runs the AD-8
recovery (orders left `created` become `not_found`, `submitting` become `unknown` and are
looked up in open AND closed orders for 60 s before anything is re-sent, fills are ingested
once by trade id) and the AD-9 reconciliation (store vs paper account: open orders, base,
quote, fills). A mismatch halts and exits non-zero; otherwise trading resumes. Verify with
`bot status` (new run id, fresh heartbeat, `reconcile mismatches: 0`) and the supervisor log.

To stop everything without the graceful path, kill the supervisor first (it would restart
the engine), then the engine:

```powershell
Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
  Where-Object CommandLine -like "*supervise.ps1*" | Select-Object ProcessId, CommandLine
Stop-Process -Id <supervisor PID> -Force; Stop-Process -Id <engine PID> -Force
```

## Kill switch, halts, flatten (operator)

- `uv run bot kill on --note "why"`: creates `var/KILL` now; the engine stops new orders and
  cancels resting ones on its next tick (keeps the position). Any file at `var/KILL`, even
  empty, counts.
- `uv run bot kill off --note "why"`: the engine deletes the file on its next tick (it is the
  only deleter).
- `uv run bot reset-halt daily_loss --note "why"` (or `total_drawdown`, `reconcile_mismatch`,
  `fatal_error`, `clock_skew`, `all`). `--rebase-baseline` (total_drawdown only) asks you to
  type `REBASE`. Halts never expire on their own.
- `uv run bot flatten --note "why"`: sells the whole position, the only sell allowed while
  halted or killed.

## Supervision with Task Scheduler (operator action, not done by the build)

`scripts\register-task.ps1 -Strategy v0_trend` (and again for `plumbing`) registers a task
that starts `scripts\supervise.ps1` **at logon** with **restart on failure** (every minute,
up to 999 times), no time limit, allowed on battery, one instance at a time. The supervisor
restarts the engine after a crash with a 10 s to 5 min backoff; the task restarts the
supervisor itself. Remove it with
`Unregister-ScheduledTask -TaskName "trading-bot dry-run v0_trend" -Confirm:$false`.

## Sleep, hibernation, clock

The build does not change power or sleep settings. For a four-week dry-run the operator
should keep the PC awake (Settings > System > Power & sleep: "Never" while plugged in), or
accept gaps. While the PC sleeps nothing ticks. After waking:

- the next tick sees the gap (> 10 min since the previous tick) and **reconciles before
  doing anything else** (AD-29);
- live candles are refetched; a resting order from before the sleep is re-synced, and the
  stale-data rules (`stale_ticker` 120 s, `stale_candle` 2 intervals) refuse any submission
  priced from old data;
- the hourly clock check compares the PC clock with Kraken's public server time; a skew
  above 5 s refuses the start or, while running, halts with rule `clock_skew` (reset with
  `bot reset-halt clock_skew` after fixing the clock: Settings > Time > Sync now).

Heartbeat gaps caused by sleep are visible in `heartbeats` and in `bot status`.

## Exit codes

| Code | Meaning | Supervisor |
|---|---|---|
| 0 | graceful stop | exits |
| 1 | fatal error or reconciliation mismatch (halt written, resting orders cancelled first) | restarts (the halt stays until `bot reset-halt`) |
| 2 | start refused (lock held by a live engine, clock skew, public data unreachable) | restarts with backoff |
