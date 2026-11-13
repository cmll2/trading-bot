---
title: 'Walking-skeleton backtest from one command'
type: feature
ticket: '4'
created: '2026-11-13'
status: built
baseline_revision: '64fce9c'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: [oversized]
deferred: []
---

<intent-contract>

## Intent

**Problem:** No backtest exists; `bot backtest` is a stub and the engine, paper broker, fill model, sizing and v0 strategy are stubs.

**Approach:** Tracer bullet through the real architecture: `bot backtest --strategy v0_trend` builds the shared `Engine(PaperBroker, SimClock, ReplayMarketData, Store(":memory:"))` (approval forced to autonomous), over cached 1d (signals) and 15m (fills) candles from `data.history_start` to `backtest.holdout_start` (exclusive; holdout never loaded), and writes `results/{date}_{strategy}_{commit}.json` + `.md` labelled SIMULATED with strategy vs buy-and-hold vs cash. Re-pricing/completion (story 6), minimum/dust rules (story 7), full metrics (story 8) and look-ahead guard (story 5) build on it.

## Boundaries & Constraints

**Always:** coordinator decisions — v0 params fixed in `config.yaml strategy.params` (`sma_days: 200`, long iff last closed close > SMA(200)), `fees:` section = Kraken published entry tier 0.0040/0.0080 labelled `published_schedule`; synthetic 15m candles never fill (audit M1 F-2); minimums/precision from the committed public market snapshot (`bot/backtest/kraken_market_snapshot.json`, fetched 2026-11-13); every submission passes `check_order`, decision passed to `place_order`; engine has no mode branch; one fill model shared with paper; no network in tests; deterministic results content.

**Never:** load holdout data; touch protected files; add dependencies; change risk values.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error Handling |
|---|---|---|---|
| rising synthetic series | v0 SMA(3), wicks 0.5% | one buy executed on the day after the first close > SMA; equity > 20 | none |
| falling series | closes below SMA | no fills; all signals no_action | none |
| one command | `bot backtest --end <date>` | exit 0; one results JSON with label SIMULATED | none |
| holdout | `--end` after holdout_start | refused, no results written | exit 2 |
| risk gate | every submission | `check_order` called; approved decision with matching cl_ord_id given to `place_order` | RiskGateViolation if not |

</intent-contract>

## Code Map

- `config.yaml`, `bot/config.py` -- `strategy.params`, `fees:`, execution sim settings, backtest settings (results_dir resolved, look-ahead, bootstrap, walk-forward).
- `tests/test_config.py` -- maker/taker ban narrowed to "outside `fees:`" + new fees test (coordinator decision).
- `bot/strategy/v0_trend.py`, `bot/strategy/registry.py` (`build`), `bot/strategy/plumbing.py` (`implemented = False`).
- `bot/broker/fill_model.py` (pure maker/taker fill), `bot/broker/paper.py` (PaperBroker, paper_* tables).
- `bot/sizing.py` (basic buy/sell qty), `bot/engine.py` (Engine), `bot/data/market.py` (`from_frames`, `limit`).
- `bot/backtest/{dataset,runner,provenance,results,command,market_rules}.py`, `kraken_market_snapshot.json`.
- `bot/cli.py` -- `bot backtest [--start] [--end] [--results-dir]`; `tests/test_cli.py` stub test narrowed (backtest v0 now implemented).
- `tests/backtest/{synth.py,test_walking_skeleton.py}`.

## Tasks & Acceptance

**Execution:**
- [x] all files above.

**Acceptance Criteria:**
- Given the backtest command, when it runs, then it builds Engine with PaperBroker, SimClock, ReplayMarketData and an in-memory store, approval autonomous.
- Given a run, when the results file is written, then it shows strategy, buy-and-hold and cash total return for the same range, labelled SIMULATED.

## Implementation Notes

Implemented in the coordinator's main session. Backtest tick schedule = daily close + tick_seconds, and every 15m boundary + tick_seconds while an intent is active (decision logged). Ticker in backtest = last closed non-synthetic 15m close ± half-spread (strictly causal; deviation from "execution candle open" in AD-6, logged). Real-data smoke run: ~13 s per variant over 2017-01-01..2025-11-10.

## Plan Change Log

## Review Triage Log

### 2026-11-13 — Review pass
- verdicts: 10 findings — high 0, medium 3, low 6, false 1, maybe-false 0
- findings:
  - `[medium]` `[patch]` holdout rows read/validated in memory and `load_dataset` had no holdout check — `load_dataset` now raises `HoldoutViolation` for `end > holdout_start` unless `allow_holdout=True` (registered holdout run only); docstrings corrected (the whole file is validated, nothing at/after `end` is handed out); test.
  - `[medium]` `[patch]` last usable daily signal dropped (off-by-one) — `last_signal_tick = end - window + lag`; hard end bounded by that window; test.
  - `[medium]` `[patch]` bad ranges / short warm-up crashed with a traceback — start<end refusal (exit 2), `InsufficientData` and other ValueErrors → exit 4; tests.
  - `[low]` `[patch]` known anomalies not in results — `data_anomalies` in the payload (report section in story 8).
  - `[low]` `[patch]` market snapshot date/source missing — `market_rules` in the payload; test.
  - `[low]` `[patch]` fee label/rates not recorded — `fees` (+ `published_schedule`) and `slippage_bps` in the payload; test.
  - `[low]` `[patch]` in-memory store untested — test asserts SQLite reports no file.
  - `[low]` `[patch]` raw cache evicted the other timeframe — one cache slot per file.
  - `[low]` `[patch]` too little data reported as a rule refusal — now `InsufficientData` (exit 4).
  - `[false]` `[reject]` fill_model.py/paper.py absent from the diff — staging artefact (untracked files not intent-added); both are reviewed in full with story 6's diff.

## Auto Run Result

- Summary: one command `bot backtest` runs the shared engine with backtest adapters over cached 1d/15m candles (holdout excluded and refused at the loader) and writes a SIMULATED results JSON + report.
- Review: 9 patches, 0 deferred, 1 rejected. Follow-up review recommended: true by formula (3 medium) — named risk: the tick-schedule boundaries (last signal, hard end) are covered by one test each; story 11's known-outcome suite exercises them further.
- Verification: full check at commit.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
