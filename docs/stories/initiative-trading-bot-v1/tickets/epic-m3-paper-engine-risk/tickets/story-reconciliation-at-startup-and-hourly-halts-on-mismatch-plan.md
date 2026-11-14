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

One context-free quick-review subagent read the diff of stories 1-3 (f6380da..5a99592)
against the three plans, the stories and the architecture. Every finding verified against
the code; fixes in the commit after story 6 with regression tests in
`tests/engine/test_review_fixes_1_3.py`.

| # | Finding | Verdict | Route / evidence |
|---|---|---|---|
| 1 | `CcxtMarketData` kept Kraken's forming candle and later served it as closed (truncated daily close, every other signal) | high | patch: rows not closed + 10 s settle at FETCH time are dropped; refetch when the next candle has closed and settled (`test_forming_candle_is_never_served_as_closed`) |
| 2 | A slow tick (> 30 s of lookups) makes the adapter return a candle "closed" after the tick's `now`: false `FutureCandleError`, fatal exit | high | patch: `_check_closed` uses the clock at the call; SimClock never moves within a tick so the backtest guard is unchanged (`test_slow_tick_...`) |
| 3 | A `cancel_requested` order is never re-sent; after a crash between commit and cancel the first tick halts | high | patch: `_advance_intent` re-sends the cancel each tick; settle timeout measured from the first cancel this process sent (`test_cancel_lost_in_a_crash_is_re_sent_not_halted`) |
| 4 | Reconciliation compares before ingesting fills: the bot's own fills look like mismatches (likely after sleep) | high | patch: `_sync_all_live` before comparing, one re-check after another sync (`test_reconcile_ingests_unseen_fills_before_comparing`) |
| 5 | After a sleep gap the tick trades before reconciliation | medium | patch: hourly/after-gap checks run BEFORE the tick |
| 6 | Transient network errors at startup or in the hourly reconcile become a `fatal_error` halt; `_fatal` could write into a store whose lock is not held | high | patch: startup network failure -> refuse (exit 2, no halt); hourly failure recorded and retried next tick; no store write without the lock (`test_network_down_at_startup_...`, `test_transient_failure_of_the_hourly_reconcile_...`) |
| 7 | `RateLimited` from `place_order` changes state (`rejected`) and counts against the caps | low | kept, documented: the exchange refused before placing; counting it is the conservative side of a protected backstop. Added the `retry_after_s` sleep and an `api_calls` record (`test_rate_limited_place_...`) |
| 8 | `cancel_all_resting` skipped `unknown` orders | medium | patch: best-effort cancel by `cl_ord_id` |
| 9 | Lock takeover race on an empty lock file; store opened before the lock | medium | patch: empty lock younger than 30 s refuses; CLI takes the lock before building (AD-8 step 1) |
| 10 | Network read inside the AD-28 transaction | low | patch: resume path pre-reads candles and rules before the transaction (fresh signals already read before it) |
| 11 | AD-6 bid/ask record ambiguous (second ticker fetched by the paper post-only check) | medium | patch: engine writes `api_calls` endpoint `priced_from` with the bid/ask/limit per order (`test_the_bid_ask_each_order_was_priced_from_is_recorded`) |
| 12 | Backtest unchanged | n/a | reviewer confirmed; full suite incl. known-outcome and look-ahead tests passes |
