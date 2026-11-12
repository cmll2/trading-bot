---
title: '15m candles rebuilt from public trades between archive end and API window'
type: feature
ticket: '9'
created: '2026-11-12'
status: built
baseline_revision: '322c7fd9a2783cfcde87e128598093e3181b2067'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/stories/initiative-trading-bot-v1/tickets/epic-m1-data/tickets/story-15m-candles-rebuilt-from-public-trades.md'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** No official 15m source covers 2026-10-01 to about 2026-11-04 (the archive ends 2026-09-30; the OHLC endpoint keeps about 7.5 days of 15m), so the 15m cache cannot validate across that span.

**Approach:** `bot data backfill-trades --timeframe TF --start S --end E` pages Kraken's public trades through ccxt `fetch_trades` over [S, E), deduplicates by trade id, checkpoints to disk so it resumes, aggregates trades into candles with the archive's OHLCVT convention, tags them `source="trades"`, and merges into the cache through the existing `merge_candles` -> `apply_no_trade_policy` -> `validate_frame` -> `write_cache` chain.

## Boundaries & Constraints

**Always:**
- Public unauthenticated client only (`bot.data.fetch.make_public_exchange`); exponential backoff through the Clock on `bot.data.fetch.RETRYABLE` with `data.fetch_max_retries` / `fetch_retry_base_seconds`.
- `S` and `E` timezone-aware UTC, aligned to TF, `S < E <= clock.now()` (so every bucket is closed), else refuse.
- Trade id required and parsed as int (Kraken's sequential `trade_id`, exposed by ccxt as `id`); duplicates across pages dropped; the same id with different fields raises `FetchError`.
- A non-empty page that brings no new id fails loudly (`FetchError("no progress ...")`); never skip trades by bumping the cursor. The next cursor is the max trade timestamp seen (ccxt sends `since` in whole seconds, so pages overlap; dedupe handles it).
- Pagination stops when a trade with time >= E is seen (those are dropped) or a page is empty (no trades since the cursor up to now). Trades outside [S, E) are dropped.
- Aggregation: bucket = floor(ts_ms / interval_ms); sort by (ts, id); open = first, close = last, high = max, low = min, volume = sum of amounts, trades = count. Empty buckets are omitted (the existing policy fills them flat).
- `source="trades"` is a new value in `bot.data.cache.SOURCES`, meaning "complete exchange trade record". In `bot/data/validate.py` it counts like `archive` for gap classification (a hole between two archive/trades/synthetic rows is a no-trade gap) and as a valid boundary for synthetic runs (a synthetic run must sit between archive/trades rows). In `bot/data/merge.py` precedence becomes archive 4 > trades 3 > synthetic 2 > api 1.
- The merged cache must have no download gap (validation already enforces it: a hole touching an `api` row is a download gap).
- Checkpoint file `{var_dir}/data/{PAIR-DIR}/trades/trades_{S:%Y%m%dT%H%M}_{E:%Y%m%dT%H%M}.parquet` with columns `ts_ms` int64, `id` int64, `price` float64, `amount` float64 (finite, price > 0, amount > 0). Written atomically (temp file + `os.replace`, as in `bot/data/cache.py`) every 25 pages and at the end. On resume it is validated (unique ids, ts within [S, E), columns/dtypes) and fetching continues from its max ts. It is kept after success (gitignored cache).
- CLI prints trades fetched (new vs from checkpoint), candles built, overlap stats and the validation report line. Errors: exit 4 with `DATA ERROR [tf]: ...`; nothing written to the candle cache.

**Never:** authenticated endpoints, API keys, the ccxt `paginate` option; network in tests (fake exchange object; the autouse block in tests/conftest.py stays); new dependencies; touching config.yaml `risk:`, bot/risk/, tests/risk/; weakening existing tests (existing tests that enumerate sources may be extended with `trades`, never loosened); committing.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Happy path | fake pages over [S,E) with trades repeated between pages, one RateLimitExceeded | candles exact per bucket (O/H/L/C/V/count), source=trades, one backoff wait | none |
| Empty bucket | no trade in one bucket between trade buckets | flat synthetic row added by the policy; validate passes | none |
| No progress | non-empty page whose ids were all seen | FetchError "no progress" | exit 4, nothing written |
| Conflicting id | same id, different price | FetchError | exit 4 |
| Missing id | trade without id | FetchError | exit 4 |
| Resume | checkpoint holds trades up to T; rerun | first fetch uses since=T; result equals an uninterrupted run | none |
| Bad checkpoint | duplicate ids or ts outside range | refused | exit 4 |
| Overlap ok | api rows overlapping, agreeing | merged; overlapping rows keep source=trades | none |
| Overlap mismatch | api row close 2 ticks off | MergeError naming close | exit 4, cache bytes unchanged |
| Download gap | trades end before the first api row, with a hole | validation fails "download gap" | exit 4 |
| Bad window | S not aligned, S >= E, E in the future, naive | refused | exit 4 (or argparse 2) |

</intent-contract>

## Code Map

- `bot/data/trades.py` (new) -- `fetch_trades_range(exchange, symbol, start_ms, end_ms, clock, max_retries, retry_base_seconds, checkpoint_path) -> pd.DataFrame` (ts_ms, id, price, amount); `candles_from_trades(trades, tf) -> pd.DataFrame` (normalized cache frame, source="trades", trades Int64); `backfill_trades(settings, exchange, clock, tf, start, end)` returning the merged frame, `OverlapStats` and counts.
- `bot/data/fetch.py` -- reuse `RETRYABLE`, `FetchError`, `price_tick`, the backoff pattern of `_fetch_page` (factor a shared helper only if trivial).
- `bot/data/cache.py` -- add `"trades"` to `SOURCES`.
- `bot/data/validate.py` -- `NO_TRADE_NEIGHBOURS` and the synthetic-run boundary rule accept `trades` like `archive`.
- `bot/data/merge.py` -- `SOURCE_PRECEDENCE` with trades.
- `bot/candles.py` -- unchanged (`synthetic` flag only).
- `bot/cli.py` -- `bot data backfill-trades --timeframe TF --start ISO --end ISO` (exactly one timeframe; values parsed as UTC; a date means 00:00 UTC), using `_exchange_factory` / `_clock_factory`.
- `bot/data/__init__.py` -- docstring line for `trades`.
- `tests/data/test_trades.py` (new) -- every matrix row through a fake exchange with scripted `fetch_trades` pages (extend `tests/data/fakes.py` FakeExchange; trades as ccxt dicts `{"id": "123", "timestamp": ms, "price": p, "amount": a}`).
- Write files with LF endings; escape non-printable bytes in literals.

## Tasks & Acceptance

**Execution:**
- [x] `bot/data/trades.py` -- fetch, checkpoint, aggregate, backfill
- [x] `bot/data/cache.py`, `bot/data/validate.py`, `bot/data/merge.py` -- `trades` source semantics
- [x] `bot/cli.py`, `bot/data/__init__.py` -- command and docs
- [x] `tests/data/test_trades.py`, `tests/data/fakes.py` -- matrix coverage; extend existing source-enumeration tests only by adding `trades`

**Acceptance Criteria:**
- Given a 15m api cache and fake trades covering [S, first api open + 1 day), when `bot data backfill-trades --timeframe 15m --start S --end E` runs, then the cache holds trades rows for [S, E), overlapping rows checked and kept as trades, api rows after E, and `bot data validate --timeframe 15m` exits 0.
- Given a run interrupted after some pages (the fake raises a non-retryable error), when rerun with a fake that serves the rest, then fetching resumes from the checkpoint and the final cache equals an uninterrupted run.

## Implementation Notes

- `fetch_trades_range_with_counts` (also returns the checkpoint count, for the CLI line) backs `fetch_trades_range`; `check_window` holds the window rules; `BackfillResult` carries frame, stats, counts and checkpoint path.
- Checkpoint written every `CHECKPOINT_EVERY_PAGES` (25) pages and at the end only, not on failure: an interrupted run loses at most the pages since the last multiple of 25.
- ccxt 4.5.92 Kraken `fetch_trades` reads `id` from the raw trade's 7th field (Kraken `trade_id`); `since` is sent as `int(since / 1000)` seconds, as the plan assumes.
- Defect text "synthetic candle outside archive range" kept (existing tests assert it), now meaning outside archive/trades rows.
- Review fix (end of data): ccxt keeps trades with time >= `since` (ms), so the cursor trade always comes back and a page is never empty against real Kraken. Requests now pass `limit=PAGE_LIMIT` (1000); a page with no new id and fewer than `limit` trades means end of data (stop cleanly); a full page with no new id still raises "no progress". The fake mimics the ms filter and honours `limit`.
- Review fix (gap classification): deviates from the plan's "counts like archive for gap classification". `NO_TRADE_NEIGHBOURS` stays `archive`/`synthetic`: any hole touching a `trades` row (archive end to backfill start, between two backfill windows, backfill end to API start) is a download gap. `trades` remains a valid synthetic-run boundary. The backfill fills its own interior empty buckets (strictly between its first and last trade bucket) in `fill_interior_buckets`, per `data.no_trade_policy` (`fail` raises "no-trade gap"); leading/trailing empty buckets are never filled. The CLI line adds `synthetic_filled=N`.
- CLI: naive datetimes are read as UTC, explicit offsets converted to UTC; window errors exit 4, unparsable values exit 2 (argparse).
- Existing source-enumeration tests extended with `trades` (report `sources` dicts, `SOURCE_PRECEDENCE`, whose archive rank moves 3 -> 4 per the plan).
- `FakeExchange` gained `fetch_trades` with `trades_script`, plus `trades_book`/`trades_page_size` that serve pages like Kraken (time >= since truncated to seconds).

## Plan Change Log

## Review Triage Log

### 2026-11-12 — Review pass
- verdicts: 2 findings — high 0, medium 2, low 0, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` real Kraken never returns an empty page (ccxt keeps trades >= since), so end of data raised "no progress" — short page with no new id = end of data; full page with no new id still fails; fake mimics ccxt's filter; tests added.
  - `[medium]` `[patch]` `trades` counted like `archive` for gap classification let cross-source holes be filled flat — classification reverted (holes touching trades rows are download gaps); backfill fills only its own interior empty buckets (policy-aware); tests added.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass

## Auto Run Result

- Summary: `bot data backfill-trades` (public `fetch_trades`, id dedupe, backoff, checkpoint/resume, archive OHLCVT convention, `source="trades"`, interior no-trade buckets filled flat, overlap-checked merge).
- Review: 2 patches (2 medium), 0 deferred, 0 rejected. Follow-up review recommended: true (two medium patched) — named risk: end-of-data and gap rules verified only with the fake exchange until the real run.
- Verification: full check → 596 passed. Real run recorded in PROGRESS.md.
