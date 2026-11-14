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
