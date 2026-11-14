---
title: 'Plumbing strategy on its own store, never live'
type: feature
ticket: '10'
created: '2026-11-14'
status: built
baseline_revision: 'd132720'
route: full
route_source: coordinator
risk: medium
review: quick
review_source: batched review of stories 9-11
---

## Intent

`strategy/plumbing.py` generates enough simulated orders to exercise order handling,
restarts and the dashboard, with no claimed edge, only in dry-run (and backtest per AD-30's
allowed_modes), on its own store `var/state/dry-run-plumbing.sqlite`; the registry and the
live gate refuse it in live.

## Decisions

- Timeframe 1h (was a 15m placeholder): with 15m execution candles a 15m strategy could not
  re-price inside a window <= its timeframe (AD-5). Hourly candles, 60 min window, 30 min
  re-price, 60 min completion window (`plumbing:` section in config.yaml, validated). A
  15 min re-price (first draft) cancelled every order just before its first eligible 15m
  candle closed, so nothing could ever fill (found by the story 9 consistency run): the
  re-price interval must span two execution candles.
- Holds `target_pct` (50 %) of equity, then nothing, switching every `flip_hours` (2) hours
  of candle open time: about 12 intents/day when orders fill (an unfilled intent re-signals on
  the next hourly candle, so a day can have more; the protected 20/day backstop then rejects
  the excess, which also exercises that rule); 50 % keeps
  the fee drag (~2.7 %/day SIMULATED) below the daily-loss halt on its own.
- `bot backtest --strategy plumbing` stays not implemented (dry-run exercise only).
- Label `plumbing — no edge` on the strategy, the start log line, `bot status` and `bot
  journal`; orders carry no per-row tag (the whole store is plumbing-only, AD-30);
  every mode label says SIMULATED.

## Verification

`tests/engine/test_plumbing.py` (5): builds for dry-run, absent from LIVE_STRATEGIES, live
build refused, live CLI refused even with both gates; alternation and no-edge label; a
2-hour fake-clock dry-run produces >= 3 orders on `dry-run-plumbing.sqlite` only, status
labelled; window fits the timeframe. The existing `tests/test_cli.py` plumbing-live tests
still pass.
