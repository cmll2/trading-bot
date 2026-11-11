---
title: 'Clock port and closed-candle history view'
type: feature
ticket: '5'
created: '2026-11-11'
status: built
baseline_revision: '502e4f1faf0e7203e89f9b611e22af57e66ed5cf'
route: full
route_source: auto
risk: high
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/planning/architecture.md'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** Strategies must see only closed candles (FR-04, AD-3) through an immutable view, in every mode, and results must record a reproducible data hash (NFR-02, AD-21). A leak here is look-ahead everywhere.

**Approach:** Add `SimClock` beside story 1's `SystemClock`/`FakeClock`; a pure, immutable `CandleHistory` in a neutral module that holds only candles with `open_at + interval <= as_of`; the `MarketData` port signature fixed as `closed_candles(pair, timeframe) -> CandleHistory` using the adapter's clock, with `ReplayMarketData` serving the Parquet cache; a deterministic `data_hash` over a cached frame.

## Boundaries & Constraints

**Always:** the closed rule is exactly `open_at + interval <= as_of` (visible at its close instant, invisible one microsecond before); `as_of` must be timezone-aware UTC (naive → `ValueError`); `CandleHistory` is a frozen dataclass whose arrays are copies with `flags.writeable = False`, so item assignment raises and the source frame is never changed; `to_frame()` returns a fresh copy; `CandleHistory` lives in `bot/candles.py` and imports nothing from `bot/data`, `bot/broker`, `bot/engine`, `bot/store` or any network library (strategy/ may import it; architecture rule that strategy/ never imports data/); `ReplayMarketData` refuses an unknown pair/timeframe or a missing cache loudly and validates the frame with `validate_frame` on load; `data_hash` is sha256 hex over a canonical serialization (columns in schema order, `open_at` as int64 ms, floats via `repr`-exact bytes e.g. `numpy` `.tobytes()` of float64, `trades` with NA encoded explicitly, `source` utf-8) so loading the same file twice gives the same hash and any value change changes it.

**Never:** `object.__setattr__`, `setattr()`, `__dict__`, `model_construct` in `bot/` (tests/test_skeleton.py bans them); wall-clock calls outside `bot/clock.py`; the AD-2 exchange-skew check (M3); new dependencies; protected files; weakening tests.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| 1 s before close | FakeClock 2026-01-01T23:59:59Z, 1d candle opened 2026-01-01T00:00Z | candle absent; last visible is 2025-12-31 | none |
| At close | FakeClock 2026-01-02T00:00:00Z | candle present | none |
| 4h / 15m | same rule at their intervals | exact boundaries | none |
| Mutation | `hist.close[0] = 1`, assigning an attribute | raises (`ValueError` / `FrozenInstanceError`); source frame unchanged | expected exception |
| Naive as_of | naive datetime | `ValueError` | expected exception |
| Replay | cache written by `write_cache`, `ReplayMarketData(var_dir, pair, clock)` | `closed_candles("BTC/EUR","1d")` equals the closed prefix of the cache | missing cache → `FileNotFoundError`-like `DataValidationError` |
| Hash stable | load same file twice | same hex | none |
| Hash sensitive | change one close by 0.1, or one source | different hex | none |
| SimClock | `SimClock(start)`, `advance_to(t)` / `sleep_until(t)` | now moves forward only; moving backwards raises | `ValueError` |

</intent-contract>

## Code Map

- Existing code (stories 1-4): `bot/clock.py` has `Clock`, `SystemClock`, `FakeClock` (+ `_require_utc`); `bot/data/cache.py` (`read_cache`, `cache_path`, `normalize`, `COLUMNS`); `bot/data/validate.py` (`read_cache_checked`, `validate_frame(df, tf, data_settings, now=None)`, `DataValidationError`); `bot/cli.py` `bot data validate` prints a per-timeframe line. Write files with LF line endings; escape non-printable bytes in literals.
- `bot/clock.py` -- add `SimClock(start)`: `now()`, `advance_to(t)` (monotonic, raises on backwards), `sleep_until(t)` = `advance_to(max(now, t))`. Keep `SystemClock`, `FakeClock` from story 1 unchanged.
- `bot/candles.py` (new) -- `CandleHistory` frozen dataclass: `timeframe`, `as_of`, read-only numpy arrays `open_at` (int64 ms), `open`, `high`, `low`, `close`, `volume`, `synthetic` (bool), `__len__`, `last_open_at` (datetime or None), `to_frame()`; constructor `CandleHistory.from_frame(df, timeframe, as_of)` applies the closed filter. Interval from `bot.config.TIMEFRAME_SECONDS` (config import is allowed; it is not data/).
- `bot/data/market.py` -- `MarketData` Protocol: `closed_candles(self, pair: str, timeframe: str) -> CandleHistory`; `ReplayMarketData(var_dir, pairs, clock, data_settings)` loads via `bot.data.cache.read_cache`/`cache_path` once per (pair, tf), validates, serves `CandleHistory.from_frame(df, tf, clock.now())`; exposes `data_hash(pair, tf)`.
- `bot/data/cache.py` -- add `data_hash(df) -> str`.
- `bot/strategy/base.py` -- type `history` as `CandleHistory` in the Protocol (no behaviour change; strategies remain stubs).
- `bot/cli.py` -- `bot data validate` also prints each file's `data_hash`.
- `tests/test_clock.py`, `tests/test_candles.py`, `tests/data/test_market.py`, `tests/data/test_hash.py` (new) -- matrix rows; plus an AST test that `bot/candles.py` and `bot/strategy/*` import nothing from `bot.data`, `bot.broker`, `bot.engine`, `bot.store`, `ccxt`, `socket`, `urllib`, `requests`.

## Tasks & Acceptance

**Execution:**
- [x] `bot/clock.py` -- SimClock -- AD-2
- [x] `bot/candles.py` -- immutable closed-only view -- FR-04, AD-3
- [x] `bot/data/market.py`, `bot/data/cache.py` -- port, replay adapter, hash -- AD-18, AD-21
- [x] `bot/strategy/base.py`, `bot/cli.py` -- typing and hash print
- [x] tests -- matrix coverage and import-boundary test

**Acceptance Criteria:**
- Given a cache and `FakeClock` at a candle's close instant minus 1 s, when a strategy-facing history is read through `ReplayMarketData`, then that candle is absent, and at the close instant it is present.
- Given `bot data validate` on an unchanged cache run twice, then the printed data hash is identical.

## Implementation Notes

- `ReplayMarketData(var_dir, pairs, clock, data_settings)` follows the Code Map; the matrix row's shorter `(var_dir, pair, clock)` form omitted `data_settings`, which `validate_frame` needs.
- Replay validates without `now=`: a backtest cache legitimately holds candles after the sim clock; `CandleHistory`'s closed filter hides them.
- Unknown pair/timeframe raise `ValueError`; a missing or invalid cache raises `DataValidationError` (itself a `ValueError`).
- `CandleHistory.__post_init__` only checks (read-only arrays, dtypes, lengths, UTC `as_of`, every candle closed); it never assigns, so no `object.__setattr__`. Arrays are views of a read-only private buffer, so `flags.writeable = True` also raises.
- The closed comparison is done in integer microseconds, so the one-microsecond boundary is exact.
- `data_hash` normalises the frame, prefixes a version tag (`bot-candles-v1`), and frames each column with its name, row count and byte length; little-endian bytes throughout.
- SimClock tests live in the new `tests/test_clock.py` as planned; story 1's `tests/data/test_clock.py` is unchanged. The import-boundary test lives in `tests/test_candles.py`.

## Plan Change Log

## Review Triage Log

### 2026-11-11 — Review pass
- verdicts: 4 findings — high 0, medium 2, low 2, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` `from_frame` rounded `open_at` to ms before the closed check (≤1 ms look-ahead for non-aligned ns frames) — exact ns alignment check refuses off-boundary timestamps; tests added.
  - `[medium]` `[patch]` arrays owned writable memory reachable via `.base` — arrays now backed by immutable `bytes`; writeable cannot be re-enabled; tests added.
  - `[low]` `[patch]` constructor accepted read-only views of caller-writable arrays — `__post_init__` requires bytes-backed arrays (same root cause as above).
  - `[low]` `[patch]` bare pair string split into characters in `ReplayMarketData` — `TypeError`; test added.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass

## Auto Run Result

- Summary: `SimClock`; immutable closed-only `CandleHistory` (`bot/candles.py`, no data/broker/network imports); `MarketData.closed_candles(pair, tf)`; `ReplayMarketData`; deterministic `data_hash`, printed by `bot data validate`.
- Review (orchestrator): 4 patches (2 medium, 2 low), 0 deferred, 0 rejected. Follow-up review recommended: true (two medium patched; high-risk story) — named risk: the M2 look-ahead guard (AD-4) must run through this view and re-check prefix invariance end to end.
- Verification: full check → 495 passed; real `bot data validate` exit 0 with stable hashes (1d 975bb436…, 4h d62eb114…, 15m cb82fedc…).
