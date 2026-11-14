---
title: 'Reconciliation at startup and hourly halts on mismatch'
type: feature
ticket: '3'
created: '2026-11-14'
status: built
baseline_revision: 'caea204'
route: full
route_source: coordinator
risk: high
review: quick
review_source: batched review of stories 1-3 (Review Triage Log below)
---

## Intent

AD-9: at startup, every hour and after a > 10 min gap between ticks, compare the store with
the broker (the `paper_*` tables in dry-run): open orders by `cl_ord_id` (foreign order or a
store-resting order absent at the broker), base balance exactly equal to the derived
position, quote balance >= derived cash (A-1), fills both ways by exchange trade id. Any
mismatch: `risk_events` (one per problem, both sides in `detail_json`), `halts`
(`reconcile_mismatch`), both sides logged, own resting orders cancelled best effort,
`ReconcileMismatch` -> the runtime records `stop_reason` and exits 1.

## Built

- `Engine.reconcile(now)` (bot/engine.py); called by `bot/runtime.py` after `recover` at
  startup, then hourly (`CHECK_EVERY`) and after a gap > `SLEEP_GAP` (10 min).

## Verification

`tests/engine/test_reconcile.py` (9): consistent state passes; foreign open order; base off
by one step (1e-8); quote below derived cash; quote above allowed; unmatched fill; store order
missing at the broker; the auditor's check (tamper a `paper_fills` row in the dry-run store
-> restart exits 1 with a `reconcile_mismatch` halt); hourly and after-sleep scheduling.

## Review Triage Log
