---
title: 'Crash-safe restart mid-order with no duplicates'
type: feature
ticket: '2'
created: '2026-11-14'
status: built
baseline_revision: '85015c2'
route: full
route_source: coordinator
risk: high
review: quick
review_source: batched (see story 3 plan, Review Triage Log)
---

## Intent

AD-8 startup sequence and duplicate prevention: persist before acting, `created` ->
`not_found`, `submitting` -> `unknown`, `find_order` (open AND closed) every 10 s up to
`execution.unknown_grace_seconds` (60 s) before `not_found`, fills ingested once, pending
signals resumed, rate limits / transient reads without state change, illegal transitions
fatal.

## Built (bot/engine.py)

- `Engine.recover(now)`: steps 2-7 of AD-8 (step 2 consumes `reset_halt` actions, wired
  in story 6); `_resume_pending_signals` re-evaluates a `pending` signal with no intent
  through the same `_decide_and_open` path as a fresh signal, or ends it `not_filled` /
  `restart_window_passed`.
- `_resolve_unknown`: polling loop through the clock; `place_order` raising
  `OrderOutcomeUnknown` resolves immediately (never resent). In normal ticks an `unknown`
  order is not freed before the grace.
- `_sync_order`: ingested fills > exchange filled -> `reconcile_mismatch` halt at once;
  exchange filled > ingested for longer than `fill_settle_timeout` -> halt (AD-27, any state,
  not only `cancel_requested`); fills the `exchange_order_id` learned after a restart.
- `_read`: broker reads (fills, find_order) retried at most 3 times, `RateLimited` sleeps
  `retry_after_s`, each failure recorded in `api_calls` (`broker.<name>`), then the tick
  is skipped (the runtime records the error). The tick's ticker read is not retried, so the
  backtest's SimClock never sleeps.
- `_cancel_live`: a timed-out cancel stays `cancel_requested` and is re-sent next tick; an
  `unknown` order is resolved before any cancel.
- `_maybe_signal` split into `_decide_and_open` + `_submit_first` (shared with resume);
  new signals during a flatten are journaled `no_action` / `flatten_active` (AD-25).
- Audit M2 F-5 (story 1 note): own-feed staleness cancels the resting order (risk event
  `stale_data` / `stale_ticker`); an unavailable ticker for > `stale_ticker_seconds` does
  too; the order is kept only when the latest execution candle is synthetic (exchange
  halt), which is the only case the backtest can produce, so backtest results are unchanged.
- Runtime: `IllegalTransition`, `FatalBrokerError`, any unhandled error -> `fatal_error`
  halt, best-effort cancel of resting orders, `runs.stop_reason`, exit 1.

## Verification

`tests/engine/test_restart.py` (40 tests incl. 25 seeded random-crash runs) and
`tests/engine/test_stale_feed.py` (3): order row committed (second connection) before the
broker call; crash in `created`, before send, after accept; timeout after accept; unknown
not found only after 60 s; partial fills counted once over two restarts; restart in
`cancel_requested`; exchange-side cancel; pending signal resumed / expired; rate limit and
3 transient retries change no state; illegal transition -> `fatal_error`, exit 1.
