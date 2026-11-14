---
title: 'Complete journal outcomes, snapshots, health records and backups'
type: feature
ticket: '8'
created: '2026-11-14'
status: built
baseline_revision: '0789998'
route: full
route_source: coordinator
risk: medium
review: quick
review_source: batched review of stories 5-8
---

## Intent

Every signal ends with exactly one AD-28 outcome, written in the same transaction as the
final intent state; each tick writes equity (marked at mid) and a risk snapshot (context +
usage of every limit), the first tick of a UTC day writes day-open equity before any risk
check; health data: `api_calls` (latency, ok, rate_limited, detail), `errors` (redacted
message and traceback), heartbeats; 30-day retention; a daily `sqlite3` backup to
`var/backups/` keeping 30 copies. Journal view with an estimated would-have-returned for
untraded signals (`bot journal`).

## Built

- bot/engine.py: `_risk_snapshot` (per tick, off in the backtest via
  `EngineConfig.risk_snapshots=False` for speed: the report does not read them),
  `housekeeping` (prune `api_calls`/`heartbeats`/`risk_snapshots` > 30 days, backup, keep 30);
  engine log lines redacted too.
- bot/store.py: `Store.backup(target)` (sqlite backup API, temp file then rename).
- bot/runtime.py: housekeeping on the first tick and then once per UTC day.
- bot/logging_setup.py: broader credential patterns (`='...'`, `": "`, Bearer, nonce).
- bot/journal.py + `bot journal`: read-only; would-have-returned = entry at the signal close,
  exit at the next signal with a different target (or the latest mark, "open"), maker fee on
  both legs; labelled SIMULATED / estimate. The authoritative counterfactual table
  (`signal_counterfactuals`, AD-20) stays owned by `bot review` (M4, AD-17): deviation note
  for the coordinator's "would-have-returned" requirement.

## Verification

`tests/engine/test_journal_health.py` (16): each of the 9 final outcomes produced; the
outcome and final intent state commit together; equity + risk snapshot per tick and one
day-open row per UTC day; day-open written before the first risk check; error rows redacted;
dry-run records api_calls and writes `var/backups/dry-run-v0_trend-YYYYMMDD.sqlite`;
housekeeping keeps 30 backups and prunes old health rows; journal estimate.
`tests/test_logging.py` (7): credential shapes redacted; a planted secret raised through the
ccxt wrapper is absent from the JSON log file and from the `errors` row.

## Review Triage Log (batched review of stories 5-8)

One context-free quick-review subagent read the bot/ diff 5a99592..d132720 against the
plans, stories and architecture. Every finding verified; fixes in the commit after story 9,
regression tests in `tests/engine/test_review_fixes_5_8.py`.

| # | Finding | Verdict | Route / evidence |
|---|---|---|---|
| 1 | Operator action effect and `consumed_at` committed separately: a crash replays the command (double reset/rebase) | high | patch: `_prepare_<kind>` (broker calls) + `_apply_<kind>` whose writes commit with `consumed_at` in one transaction (`test_an_action_is_never_applied_twice_after_a_crash`) |
| 2 | A pending `kill off` deletes a switch engaged after it | high | patch: the file's recorded `at=` (or mtime for a hand-made file) later than the action -> kept (`test_kill_off_never_deletes_a_switch_engaged_after_it`) |
| 3 | `unlink` of a kill file held open on Windows raises and crash-loops the engine | high | patch: `OSError` rolls back, error recorded, retried next tick (`test_kill_file_held_open_...`) |
| 4 | A reset closes halts raised after the command | medium | patch: only halts with `triggered_at <= action.at` (`test_reset_never_closes_a_halt_raised_after_the_command`) |
| 5 | Ticker failure returns before the kill switch / halt sweep | high | patch: on a failed ticker the tick still consumes actions and sweeps on kill/halt (`test_kill_switch_cancels_the_resting_order_even_while_the_ticker_fails`) |
| 6 | `recover()` could send an order (resumed pending signal) before halts and reconciliation | high | patch: recover only expires window-passed pending signals; open ones are re-evaluated on the tick after halts; `test_pending_signal_without_intent_is_resumed_while_its_window_is_open` now asserts nothing is sent during recover (stricter) |
| 7 | A halt raised while syncing lets the intent re-price and end `rejected_by_risk` | medium | patch: `_advance_intent` sweeps (outcome `halted`) when a halt or the switch appears mid-tick (`test_halt_raised_while_syncing_ends_the_intent_halted`) |
| 8 | A pending flatten (cancel unconfirmed) lets the active intent keep re-pricing (live risk) | medium | patch: no `_advance_intent` while a flatten action is pending (`test_pending_flatten_freezes_the_active_intent`) |
| 9 | Completion intent in manual mode buys without approval | medium | patch: created `awaiting_approval` with its window end as deadline, announced (`test_manual_completion_intent_waits_for_its_own_approval`) |
| 10 | CLI opened the store with `Store.open` (could migrate outside the lock) | medium | patch: `Store.open_existing` (rw, no create/migrate, version check) (`test_cli_never_migrates_a_store`) |
| 11 | Backtest now writes `priced_from` rows and runs extra per-tick queries | low | patch: `EngineConfig.health_records=False` in the backtest disables `priced_from` and `risk_snapshots`; extra queries kept (results unchanged; full suite incl. known-outcome tests passes) |
| 12 | `input()` without a terminal raises `EOFError` | low | patch: treated as no confirmation -> refused (`test_rebase_confirmation_without_a_terminal_is_refused`) |
