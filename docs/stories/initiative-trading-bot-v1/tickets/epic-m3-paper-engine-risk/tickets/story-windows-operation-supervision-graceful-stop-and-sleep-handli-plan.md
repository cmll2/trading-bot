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

## Real demonstration (2026-11-14, public Kraken endpoints, SIMULATED)

`start-dry-run.ps1 -Strategy plumbing` -> supervisor PID 24180, engine PID 23740, `bot
status` HEALTHY; a second start refused (supervisor already running); `Stop-Process -Id
23740 -Force` (forced kill) -> supervisor logged exit -1 and restarted the engine (PID 20384,
run 4) 10 s later, recovery + reconciliation OK (`reconcile mismatches: 0`); then
`stop-dry-run.ps1` -> engine exit 0, stop file removed, supervisor exited.

## Review Triage Log (batched review of stories 9-11)

One context-free quick-review subagent read the diff d132720..8a075e4. Fixes in the commit
after this story; regression tests where testable.

| # | Finding | Verdict | Route / evidence |
|---|---|---|---|
| 1 | Live loop ticks on exact 30 s boundaries: the window-end tick cannot see the last eligible 15m candle (10 s settle), so the order is cancelled unfilled, unlike the backtest; plumbing's re-priced order could never fill; the consistency test's 15 s offset hid it | high | patch: loop ticks on the 30 s grid + `TICK_OFFSET` 15 s (> settle); the consistency test now documents that it uses that grid (`test_loop_ticks_never_land_on_a_candle_boundary`) |
| 2 | Consistency docstring claims `run_backtest` wiring; 1h frame resampled; quotes look ahead within the candle; AC2 not checked | medium | patch: docstring states exactly what is compared (adapters, maker, plumbing timings; not `run_backtest`'s schedule/taker); fixture labels; `priced_from` rows compared and one per order |
| 3 | `_apply_kill_off` crashes on a malformed `at=` (ValueError) and crash-loops | high | patch: unparseable time -> file mtime |
| 4 | Whole-second kill file time vs millisecond request: a tie deletes the newer switch | medium | patch: compare against the request's second; a tie keeps the switch |
| 5 | Label must be `plumbing — no edge` (em dash); journal lacks it | low | patch: em dash; `bot journal` header carries it; orders untagged (store is plumbing-only) noted in the story 10 plan |
| 6 | "1-hour run" verify runs 2 hours | low | kept: a 1-hour window yields 2 orders (first + one re-price); 2 hours give >= 3 ("several"); noted in the story 10 plan |
| 7 | Plan claim "about 12 intents/day" | low | patch: plan text corrected |
| 8 | Wrong hour number in a test comment | low | patch |
| 9 | `supervise.ps1` cmd.exe quoting breaks with a space in the path (PS 5.1) | medium | patch: `Start-Process -FilePath -ArgumentList -Wait -PassThru` with per-start stdout/stderr files |
| 10 | `start-dry-run.ps1` reports success from a stale lock | medium | patch: only a lock written after this start counts |
| 11 | A stop sent while the engine is down or starting is lost (engine deleted the stop file at start) | high | patch: the engine no longer deletes it at start and removes it only when honoured; the supervisor consumes a stop file found before a restart and exits; `start-dry-run.ps1` clears a stale one |
| 12 | Duplicate supervisors loop forever on exit 2 and take over after a stop | medium | patch: lock refusal exits with code 6 and the supervisor exits on 6; `start-dry-run.ps1` refuses a second supervisor (demonstrated) |
| 13 | `stop-dry-run.ps1` ignores `bot stop`'s exit code | low | patch: checked; also waits for the supervisor to exit |
| 14 | Task Scheduler restart-on-failure may not restart an exited supervisor | maybe-false | doc: stated as not verified, with what to check |
| 15 | Stop-and-restart demonstration missing | medium | done (section above; also in PROGRESS.md) |
| 16 | "Mid-tick" test sets the flag after the tick | low | patch: flag set as the tick starts; the tick still completes |
