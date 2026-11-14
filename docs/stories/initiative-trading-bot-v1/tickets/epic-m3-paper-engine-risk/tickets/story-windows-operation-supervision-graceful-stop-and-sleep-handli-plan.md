---
title: 'Windows operation: supervision, graceful stop and sleep handling'
type: feature
ticket: '11'
created: '2026-11-14'
status: built
baseline_revision: 'c9c2a19'
route: full
route_source: coordinator
risk: medium
review: quick
review_source: batched review of stories 9-11
---

## Intent

AD-29 on this PC: graceful stop (CTRL+C, CTRL_BREAK, or `bot stop`) finishes the tick,
commits, records `runs.stop_reason` and releases the lock; a fatal exit first cancels the
bot's known resting orders; no listening socket; documented Task Scheduler supervision (at
logon, restart on failure) and post-sleep behaviour. Coordinator constraint: provide the
registration script but do NOT register a task and do NOT change power/sleep settings; start
the 48 h run as a detached background process.

## Built

- `scripts/supervise.ps1`: restart loop (10 s doubling to 5 min backoff, reset after a 10 min
  run); exit code 0 (graceful stop) ends it.
- `scripts/start-dry-run.ps1`: starts the supervisor detached via WMI `Win32_Process.Create`
  (survives the starting shell), prints supervisor and engine PIDs.
- `scripts/stop-dry-run.ps1`: `bot stop` + wait for the lock to go.
- `scripts/register-task.ps1`: Task Scheduler task at logon, restart on failure (operator
  action; not run).
- `docs/operations/windows-supervision.md`: start, health (`bot status`), logs, graceful stop,
  forced restart, operator commands, Task Scheduler, sleep/clock, exit codes.
- Already in the runtime (stories 1-3): signal handlers, stop file, sleep-gap reconcile,
  fatal path with best-effort cancel.

## Verification

`tests/engine/test_supervision.py` (6): a stop request mid-tick finishes that tick, commits,
records the stop reason and releases the lock; the stop file is honoured; SIGINT/SIGBREAK
handlers; a fatal error cancels the resting paper order, halts `fatal_error`, records the
stop reason and releases the lock; no module under bot/ binds or listens (AST); doc and
scripts exist. A real stop and restart is demonstrated before the 48 h run (PROGRESS.md).
