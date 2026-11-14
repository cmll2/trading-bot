---
title: 'Backtest and paper broker agree on recorded data'
type: feature
ticket: '9'
created: '2026-11-14'
status: built
baseline_revision: 'dfbcb56'
route: full
route_source: coordinator
risk: high
review: quick
review_source: batched review of stories 9-11
---

## Intent

FR-60 / AD-6: the same recorded 15m candles and bid/ask, replayed through the backtest's
adapters and through the dry-run's adapters, give identical trades (fills, prices, fees,
order states, outcomes). Dry-run records the bid/ask each order was priced from.

## Built

- Recording: `api_calls` endpoint `priced_from` (bid, ask, limit, cl_ord_id per order;
  added with the stories 1-3 review fixes) and the `fetch_ticker` detail on every tick.
- `tests/fixtures/consistency/`: `candles_15m.csv` = REAL Kraken BTC/EUR 15m candles copied
  from the validated cache (2026-11-05 .. 2026-11-08, 288 rows); `quotes.csv` = bid/ask every
  5 minutes DERIVED from those candles (mid from the forming candle's open to its close, half
  spread 1-3 bp) by `make_fixture.py`. **Deviation:** the story asks for bid/ask "from a dry-run
  session"; none existed when the test was written. The quotes use the same fields as the
  recorded `priced_from` / `fetch_ticker` detail, so a slice of the 48 h run can replace them.
- `tests/test_consistency.py`: backtest path = `ReplayMarketData` + `PaperBroker` (public
  market snapshot) + `SimClock` + in-memory store, as `run_backtest` wires them, with the
  recorded quotes as ticker; paper path = `bot.runtime.build_dry_run` (CcxtMarketData,
  LiveFeed, PaperBroker with live rules/ticker) over a fake public exchange serving the
  same rows; both run the plumbing strategy in lockstep (every 60 s while an intent is
  active, else each hourly close + 15 s). The backtest's own tick schedule (daily close +
  30 s, 15m boundaries) is not used: equality needs identical tick times.

## Verification

3 tests: the fixture yields 38 intents, 47 orders (9 re-prices), 33 fills, 4 not_filled,
1 rejected_by_risk; fills/orders/intents/signals identical between the two paths; perturbing
one recorded quote (EUR 40 at the first order) breaks the equality.
