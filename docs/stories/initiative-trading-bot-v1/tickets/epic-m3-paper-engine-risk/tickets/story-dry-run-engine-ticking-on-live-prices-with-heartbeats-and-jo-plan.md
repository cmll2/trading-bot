---
title: 'Dry-run engine ticking on live prices with heartbeats and journal'
type: feature
ticket: '1'
created: '2026-11-14'
status: built
baseline_revision: 'f6380da'
route: full
route_source: coordinator
risk: medium
review: quick
review_source: batched (see story 3 plan, Review Triage Log)
---

## Intent

`bot dry-run --strategy v0_trend` runs the SAME M2 `Engine` with `PaperBroker` (live public
bid/ask via `LiveFeed.ticker`, public market rules re-read per intent, fills through the
shared `fill_model` on live closed 15m candles), `SystemClock`, `CcxtMarketData` (public
`fetch_ohlcv`, cached, refetched only when a newer candle can have closed) and the file store
`var/state/dry-run-<strategy>.sqlite`. No API key, no `load_secrets`.

## Built

- `bot/data/live.py`: `CcxtMarketData`, `LiveFeed` (ticker, market rules, server time),
  ccxt errors -> `RateLimited` / `TransientReadError`, every call recorded to `api_calls`
  (latency, ok, rate_limited, `detail_json`; the ticker detail holds the bid/ask, AD-6).
- `bot/migrations/0003_api_call_detail.sql` (schema v3): `api_calls.detail_json`, indexes.
- `bot/runtime.py`: `build_dry_run`, engine lock `<store>.lock` (O_EXCL + PID; stale PID
  taken over; Windows liveness via OpenProcess, never `os.kill(pid, 0)`), clock-skew check
  against Kraken public server time (refuse > 5 s at start; hourly re-check halts with rule
  `clock_skew`), tick loop on the `tick_seconds` grid with a heartbeat per tick, graceful
  stop (CTRL+C, CTRL_BREAK, stop file), fatal exit path.
- `bot/logging_setup.py`: JSON lines `var/logs/dry-run-<strategy>.log`, daily rotation,
  30 kept, redaction filter on every handler, `run_id`/`mode`/`strategy` on every line.
- `bot/ops.py` + CLI: `bot status` (exit 0 only when a heartbeat is within 3 ticks),
  `bot stop` (stop file).
- `PaperBroker(ticker_source=, rules_source=)`; `Engine.start(pid)`, `heartbeat`, `error`
  (redacted), `raise_halt`, `fatal`, `cancel_all_resting`.

## Decisions / deviations

- Heartbeats are written by the runtime loop, not by `Engine.tick`, so the backtest's
  in-memory store is unchanged.
- A first tick that evaluates a daily candle whose window already passed journals it as
  `not_filled` / `window_passed` (existing M2 engine behaviour).
- `tests/test_cli.py::test_backtest_and_dry_run_are_stubs`: the two `dry-run` cases were
  removed because dry-run is now implemented (tested in `tests/engine/test_dry_run.py`;
  running the real command in that test would hit the network block). Not a weakening.

## Verification

`tests/engine/test_dry_run.py` (10 tests): one daily close -> journaled signal + paper
order at the live bid; heartbeats per tick; restart keeps paper balances and `initial_*`;
second engine refused; stale lock taken over; skew > 5 s refused; CLI dry-run + status.
The real 10-minute run against Kraken public endpoints is done with the final code before
the 48 h run (see PROGRESS.md).
