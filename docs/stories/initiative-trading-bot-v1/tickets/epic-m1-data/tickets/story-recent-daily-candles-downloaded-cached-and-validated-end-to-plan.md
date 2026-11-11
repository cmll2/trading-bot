---
title: 'Recent daily candles downloaded, cached and validated end to end'
type: feature
ticket: '1'
created: '2026-11-11'
status: built
baseline_revision: 'cfb1afc7fdd320fb24c1376ac91645e21918648f'
route: full
route_source: auto
risk: medium
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

**Problem:** M1 needs a tracer from Kraken's public OHLC endpoint to a local Parquet cache with a validator; nothing in `bot/data/` exists yet beyond stubs.

**Approach:** Add `bot data update` (ccxt public `fetch_ohlcv`, paginated, rate-limit retry, closed candles only, incremental from the last cached `open_at`) writing `var/data/BTC-EUR/{tf}.parquet` (AD-18 schema), and `bot data validate` (schema, UTC, unique, monotonic, aligned, no missing interval) printing the range. Generic over timeframes 1d/4h/15m; 1d is the tracer.

## Boundaries & Constraints

**Always:** public, unauthenticated ccxt only (`ccxt.kraken({"enableRateLimit": True})`, no apiKey/secret ever); wall-clock only through `bot/clock.py`; UTC `open_at` = candle open time, `timestamp[ms, UTC]`; tests never touch the network (fake exchange object, `FakeClock`); atomic cache writes (temp file + `os.replace`); fail loudly with an exception naming the defect and timestamp, never repair.

**Never:** new dependencies; touching `config.yaml` `risk:`, `bot/risk/`, `tests/risk/`; editing/weakening existing tests; opening any secrets file; ccxt `paginate` option (we paginate ourselves); committing (the orchestrator commits).

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| First run | no cache; fake exchange returns 2 pages then empty/non-advancing page | all closed candles written once, sorted, schema exact | none |
| Rate limited | one `ccxt.RateLimitExceeded` (or `DDoSProtection`, `RequestTimeout`, `ExchangeNotAvailable`) | waits via `clock.sleep_until` with exponential backoff, retries, result identical | after `data.fetch_max_retries` failures raise `FetchError` naming tf and since; nothing written |
| Incremental | cache ends at T | request `since = T + interval` (ms); only rows `> T` appended | none |
| Open candle | response includes candle with `open_at + interval > clock.now()` | dropped | none |
| Page overlap | same `open_at` in two pages, identical values | kept once | conflicting values → `FetchError` |
| Malformed row | non-numeric / wrong length / ts not aligned | `FetchError` | nothing written |
| Validate ok | good file | exit 0, prints tf, rows, first/last `open_at`, sources | none |
| Validate defect | duplicate, non-monotonic, misaligned, missing interval, non-UTC/naive, wrong columns | exit non-zero naming defect + timestamp, file untouched | `DataValidationError` |
| No cache | `bot data validate` with missing file | exit non-zero "no cache for {tf}" | none |

</intent-contract>

## Code Map

- `bot/clock.py` -- keep `Clock` Protocol; add `SystemClock` (`now()` = `datetime.now(UTC)`, `sleep_until(t)` = `time.sleep(max(0, delta))`) and `FakeClock(start)` (`now`, `advance(timedelta)`, `sleep_until(t)` sets now to `max(now, t)` and records calls). Only file allowed to use wall clock (ruff TID251 per-file ignore exists). Exchange skew check (AD-2) is M3, note it in docstring.
- `bot/config.py` -- `TIMEFRAME_SECONDS` already has 15m/1h/4h/1d: reuse. Add frozen `DataSettings(_Frozen)`: `timeframes: tuple[Literal["15m","4h","1d"], ...]` (non-empty, unique), `fetch_max_retries: int = Field(ge=0, strict=True)`, `fetch_retry_base_seconds: float = Field(gt=0)`; add required `data: DataSettings` to `Settings`. No defaults hidden in code beyond these fields.
- `config.yaml` -- add a `data:` section ABOVE the protected block (never edit below the `# PROTECTED` banner): `timeframes: [1d, 4h, 15m]`, `fetch_max_retries: 5`, `fetch_retry_base_seconds: 2`.
- `bot/data/cache.py` (new) -- `COLUMNS = ("open_at","open","high","low","close","volume","trades","source")`; `SOURCES = ("archive","api","synthetic")`; `pair_dirname("BTC/EUR") -> "BTC-EUR"`; `cache_path(var_dir, pair, tf) -> var_dir/"data"/pair_dirname/f"{tf}.parquet"`; `empty_frame()`; `normalize(df)` -> exact dtypes: `open_at` `datetime64[ms, UTC]`, OHLCV `float64`, `trades` nullable `Int64` (API rows have `<NA>`: ccxt drops Kraken's count), `source` `string`; `read_cache(path) -> DataFrame | None`; `write_cache(path, df)` atomic (mkdir parents, write `.tmp` sibling via pyarrow/pandas, `os.replace`). Interval helper `interval_ms(tf)` from `TIMEFRAME_SECONDS`.
- `bot/data/fetch.py` (new) -- `class FetchError(RuntimeError)`; `make_public_exchange() -> ccxt.kraken` with `{"enableRateLimit": True}` only; `RETRYABLE = (ccxt.RateLimitExceeded, ccxt.DDoSProtection, ccxt.RequestTimeout, ccxt.ExchangeNotAvailable)`; `fetch_closed_candles(exchange, symbol, tf, since_ms, clock, max_retries, retry_base_seconds) -> DataFrame` (source="api"): loop `exchange.fetch_ohlcv(symbol, tf, since=cursor, limit=720)`, parse rows `[ts, o, h, l, c, v]`, stop when a page is empty or yields no candle beyond the cursor, advance cursor to last ts + interval; drop rows with `open_at + interval > clock.now()`; dedupe identical overlaps, raise on conflicts; backoff `retry_base_seconds * 2**attempt` via `clock.sleep_until(clock.now() + delay)`. Kraken returns only the last 720 candles; say so in the docstring.
- `bot/data/update.py` (new) -- `update_timeframe(settings, exchange, clock, tf) -> DataFrame`: read cache, `since = last + interval` or `None`, fetch, concat, `validate.validate_frame`, write, return frame. Raises before writing on any error.
- `bot/data/validate.py` (new) -- `class DataValidationError(ValueError)` with `.defect` and `.open_at`; `validate_frame(df, tf, now=None) -> ValidationReport` (frozen dataclass: tf, rows, first, last, counts per source). Checks in order: exact columns, `open_at` tz-aware UTC ms dtype, no nulls in open_at/OHLCV/source, unique, strictly increasing, aligned (`open_at` ms % interval == 0), every interval present (missing → defect `download gap` with the first missing `open_at`), if `now` given last candle closed. Story 2 extends this module (OHLC consistency, no-trade policy); keep the check order a simple list of functions so it extends cleanly.
- `bot/data/__init__.py` -- update docstring module list.
- `bot/cli.py` -- add `data` subcommand group (argparse, `allow_abbrev=False`): `bot data update [--timeframe TF]...` and `bot data validate [--timeframe TF]...` (default: `settings.data.timeframes`), both with `--config/--env-file`. Exit `EXIT_OK` on success, new `EXIT_DATA_ERROR = 4` on `FetchError`/`DataValidationError`/missing cache, printing `DATA ERROR [{tf}]: {defect} at {open_at}` to stderr. Existing `backtest/dry-run/live` behaviour and tests unchanged. Exchange and clock are injectable (module-level factory functions `_exchange_factory`, `_clock_factory`) so tests monkeypatch them.
- `tests/data/` (new package, `__init__.py`) -- `tests/data/fakes.py` (`FakeExchange` with scripted pages / exceptions and a call log), `test_fetch.py`, `test_cache.py`, `test_validate_basic.py`, `test_cli_data.py` (uses a tmp copy of config.yaml with `paths.var_dir` pointed at tmp_path, like `tests/test_config.py::repo`).
- Read-only constraints: `tests/test_skeleton.py` bans in `bot/`: the literal `"config.yaml"` outside config.py, any write call whose target name contains `config`/`risk`/`.yaml`, `setattr()`, `__setattr__`, `__dict__`, `model_construct`. `tests/conftest.py` autouse network block must stay untouched.

## Tasks & Acceptance

**Execution:**
- [x] `bot/clock.py` -- add SystemClock, FakeClock -- fetch backoff and closed-candle cut need a clock (AD-2)
- [x] `bot/config.py`, `config.yaml` -- `DataSettings` + `data:` section -- configurable timeframes and retry budget
- [x] `bot/data/cache.py` -- schema, path, atomic read/write -- AD-18 cache
- [x] `bot/data/fetch.py` -- paginated, retried, closed-only public fetch -- FR-01, FR-04
- [x] `bot/data/validate.py` -- basic validator -- FR-03 (extended in story 2)
- [x] `bot/data/update.py` -- incremental update orchestration -- FR-02
- [x] `bot/cli.py` -- `bot data update|validate` -- operator entry points
- [x] `tests/data/*` -- every I/O matrix row plus config tests for `data:` (bad timeframe refused, missing section refused) -- proof

**Acceptance Criteria:**
- Given a fake exchange with two 720-row pages and one `RateLimitExceeded`, when `bot data update --timeframe 1d` runs, then the Parquet file holds each closed candle once with exactly the AD-18 columns and dtypes, and the fake clock recorded one backoff wait.
- Given an existing cache, when update runs again, then the first `fetch_ohlcv` call uses `since = last open_at + interval` and no earlier row is re-requested.
- Given any validator defect, when `bot data validate` runs, then it exits 4, stderr names the defect and its timestamp, and the file's bytes are unchanged.
- Given the real repository config, when the full check runs, then `uv run ruff check . && uv run ruff format --check . && uv run pytest` passes.

## Implementation Notes

- `FetchError` and `DataValidationError` both carry `.defect` and `.open_at`. Schema-level defects (wrong columns, naive/non-UTC `open_at`, wrong dtype) have no single timestamp: the CLI then prints `DATA ERROR [{tf}]: {defect}` without ` at ...`.
- `fetch_max_retries` counts retries after the first attempt (N retries = N+1 attempts; 0 = fail on first error). Non-retryable ccxt errors are wrapped in `FetchError` immediately, no retry.
- Validator adds two schema checks beyond the listed ones: every column has its exact AD-18 dtype, and `source` is in `SOURCES`. `CHECKS` stays a flat ordered list.
- `update_timeframe` validates the existing cache before fetching (never builds on a defective cache) and does not rewrite the file when no new closed candle arrived.
- `bot data update|validate` processes every requested timeframe, reports each failure, and exits 4 if any failed. `validate` passes `clock.now()` so an open last candle is a defect; an unreadable Parquet file is reported as a `DataValidationError`.
- Review fixes (2026-11-11):
  - Still-open candles are skipped per page, before the cross-page conflict check, because the running candle changes between requests.
  - An empty cache is a defect (`empty cache`). A first run that fetches no closed candle raises `FetchError("no closed candles returned for {tf}")` and writes nothing. `test_update_defaults_to_config_timeframes` now supplies candles for each timeframe.
  - `read_cache_checked` (validate.py) reports an unreadable Parquet file as `DataValidationError`; both `update` and `validate` use it. The CLI reports `OSError` (for example a Windows file lock) as a data error, exit 4.
  - `fetch_retry_base_seconds` is now limited to finite values, at most 300.
  - The CLI leaves the location out when `open_at` is NaT.
- Extra test files beyond the code map: `tests/data/test_update.py`, `test_config_data.py`, `test_clock.py`.

## Plan Change Log

## Review Triage Log

### 2026-11-11 — Review pass
- verdicts: 5 findings — high 0, medium 2, low 3, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` fetch.py compares still-open candles across pages, so a changing running candle fails the update — open candles are now skipped before the conflict check; test with a changed open candle after a rate-limit retry.
  - `[medium]` `[patch]` update crashes on unreadable cache / OSError on write instead of exit 4 — `read_cache_checked` maps to `DataValidationError`; CLI catches OSError; tests added.
  - `[low]` `[patch]` first run with no candles writes an empty file and empty frames validate — now `FetchError` and defect `empty cache`; own new tests adjusted (recorded in Implementation Notes).
  - `[low]` `[patch]` `fetch_retry_base_seconds` accepted inf — `allow_inf_nan=False`, `le=300`; tests added.
  - `[low]` `[patch]` null `open_at` printed "at NaT" — location omitted for NaT; assertion added.

## Design Notes

API rows carry `trades = <NA>` because ccxt's unified OHLCV drops Kraken's count; the archive (story 3) fills it. Interval alignment uses epoch multiples, which matches Kraken (4h candles open at 00/04/08... UTC). Kraken may return zero-volume flat candles for empty intervals; they are real API rows, keep them.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass, no network attempts
- `uv run pytest tests/data -q` -- expected: all data tests pass

## Auto Run Result

- Summary: `bot data update` (public ccxt Kraken, paginated, backoff via Clock, closed candles only, incremental) and `bot data validate` (schema/UTC/unique/monotonic/aligned/no missing interval/closed/non-empty) over `var/data/BTC-EUR/{tf}.parquet`; `SystemClock`/`FakeClock`; `data:` config section.
- Files: `bot/clock.py`, `bot/config.py`, `config.yaml` (data: only), `bot/data/{cache,fetch,update,validate}.py`, `bot/data/__init__.py`, `bot/cli.py`, `tests/data/*`.
- Review: 5 patches applied (2 medium, 3 low), 0 deferred, 0 rejected. Follow-up review recommended: true per rule (two medium patched) — residual risk named: the open-candle and unreadable-cache fixes were verified only by unit tests and one real run.
- Verification: `uv run ruff check . && uv run ruff format --check . && uv run pytest` → 240 passed. Real run (public endpoint, 2026-11-11): `bot data update --timeframe 1d` → 719 rows, 2024-11-22 → 2026-11-10, all api; re-run left the file byte-identical; `bot data validate --timeframe 1d` exit 0.
- Residual risks: 4h/15m API windows (120 days / 7.5 days) make gaps fail loudly if updates lapse; API rows carry no trade count.
