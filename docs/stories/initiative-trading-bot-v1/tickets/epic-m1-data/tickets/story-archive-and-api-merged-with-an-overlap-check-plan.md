---
title: 'Archive and API merged with an overlap check'
type: feature
ticket: '4'
created: '2026-11-11'
status: built
baseline_revision: '1198593549b6d91ff094e7abde939e8cfed0d38a'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/docs/stories/initiative-trading-bot-v1/tickets/epic-m1-data/tickets/story-kraken-ohlcvt-archive-import-with-checksum-plan.md'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** History comes from two sources (archive ZIPs and the 720-candle API window) that must be combined into one cache; a silent disagreement between them would corrupt every backtest.

**Approach:** One pure `merge_candles(existing, incoming, tick, price_tol_ticks, volume_tol_fraction)` used by both `bot data update` and `bot data import-archive`: rows with the same `open_at` must agree (each of O,H,L,C within `price_tol_ticks × tick`, volume within `volume_tol_fraction` relative to the larger volume) or the whole operation fails and nothing is written; on agreement the row is kept from the higher-precedence source (archive > synthetic > api; agreeing synthetic and api rows carry the same values, and keeping `synthetic` preserves story 2's rule that every synthetic run is bounded by archive rows), so per-row `source` survives. Gaps between sources stay download gaps (story 2 classification).

## Boundaries & Constraints

**Always:** tick read from exchange market metadata (`exchange.load_markets()`; `market["precision"]["price"]`, ccxt TICK_SIZE mode for Kraken; must be a positive finite number, else refuse) — never hardcoded (CON-03); tolerances from config `data.overlap_price_tolerance_ticks` (1) and `data.overlap_volume_tolerance_fraction` ("0.01"), assumption A-3; float comparison uses a tiny epsilon (1e-9 × price) so exactly 1 tick passes and 2 ticks fail; the mismatch error names timeframe, `open_at`, field, both values and the tolerance; merge result is sorted, unique, normalized; overlap stats (rows compared, max price diff in ticks, max volume diff fraction) are returned and printed by the CLI; import into an existing cache now merges instead of refusing (replace story 3's refusal); `update` keeps "only candles after the last cached open_at are requested".

**Never:** average or patch values; let a later source overwrite an earlier one without the check; compare `trades` (API has none); new dependencies; touch protected files; weaken tests.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Within tolerance | archive vs api same `open_at`, close differs by exactly 1 tick, volume by 0.9% | merged; row keeps `source=archive` | none |
| Price 2 ticks off | close differs by 2 ticks | fails naming field `close`, both values | `MergeError` (subclass of `DataValidationError` or own), exit 4, cache bytes unchanged |
| Volume off | volume differs by 1.5% | fails naming `volume` | same |
| Precedence | existing api row, incoming archive row agreeing | archive row kept | none |
| Synthetic vs api | existing synthetic row, incoming api zero-volume flat row agreeing | synthetic row kept (validation of synthetic runs stays satisfied) | disagreeing → fail |
| No overlap | disjoint ranges | union | none |
| Gap between sources | archive ends t, api starts t+2i | merge succeeds, then `apply_no_trade_policy` raises `download gap` | exit 4, nothing written |
| Bad tick | metadata tick missing/0/NaN | refused | exit 4 |

</intent-contract>

## Code Map

- Existing code to reuse (stories 1-3): `bot/data/cache.py` (`normalize`, `read_cache`, `write_cache`, `cache_path`), `bot/data/validate.py` (`read_cache_checked`, `apply_no_trade_policy` which refuses unsorted/duplicate/wrong-dtype input, `validate_frame(df, tf, data_settings, now)`), `bot/data/archive.py` (`_refuse_existing_cache` to be replaced by the merge; single-handle checksum then parse), `bot/data/update.py`, `bot/cli.py` (`_exchange_factory`, `EXIT_DATA_ERROR`). Write source files with LF line endings and escape any non-printable bytes in literals.
- `bot/data/merge.py` (new) -- `MergeError`, `OverlapStats` (frozen dataclass), `SOURCE_PRECEDENCE = {"archive": 3, "synthetic": 2, "api": 1}`, `merge_candles(...) -> tuple[DataFrame, OverlapStats]`.
- `bot/data/fetch.py` -- add `price_tick(exchange, symbol) -> float` (calls `load_markets()`).
- `bot/data/update.py` -- replace plain concat with `merge_candles` (existing = cache, incoming = fetched); tick from `price_tick`.
- `bot/data/archive.py` -- when the cache exists, merge archive rows into it with `merge_candles` (needs the tick: `import_archive` gains a `tick` argument; CLI obtains it from the public exchange via `price_tick`, through the same injectable `_exchange_factory` used by `update`).
- `bot/config.py`, `config.yaml` -- `DataSettings.overlap_price_tolerance_ticks: int = Field(ge=0, strict=True)`, `overlap_volume_tolerance_fraction: Decimal = Field(ge=0, lt=1)`; yaml values 1 and "0.01" in `data:` (above the PROTECTED banner).
- `bot/cli.py` -- print overlap stats for update and import.
- `tests/data/test_merge.py` (new), additions to `tests/data/test_archive.py` and `tests/data/test_cli_data.py` -- matrix rows; the existing story 3 test for "cache exists → refused" is superseded by merge behaviour: change it only to the new specified behaviour (merge with check), recording why in Implementation Notes; do not delete other assertions.

## Tasks & Acceptance

**Execution:**
- [x] `bot/data/merge.py` -- overlap-checked merge -- AD-18, A-3
- [x] `bot/data/fetch.py`, `bot/data/update.py`, `bot/data/archive.py`, `bot/cli.py` -- use it in both writers
- [x] `bot/config.py`, `config.yaml` -- tolerances
- [x] tests -- matrix coverage

**Acceptance Criteria:**
- Given an api cache and an archive fixture overlapping it with a 2-tick close difference, when `bot data import-archive` runs, then it exits 4 naming `close` and the cache file is byte-identical afterwards.
- Given an api cache written by `bot data update` and an archive fixture agreeing within 1 tick and 1% volume on the overlap, when `bot data import-archive` runs, then overlapping rows become `source=archive`, the api-only rows stay `api`, and `bot data validate` exits 0.
- Given an archive cache, when `bot data update` runs, then it still requests only candles after the last cached `open_at` (story 1 rule kept) and combines through `merge_candles`, so no duplicate `open_at` can ever be appended. The frame passed to `apply_no_trade_policy` is sorted, unique and normalized (story 2 refuses anything else).

## Implementation Notes

- `merge_candles(existing, incoming, tick, price_tol_ticks, volume_tol_fraction, *, tf=None)`: the keyword-only `tf` was added so the error itself names the timeframe (Always clause); both writers pass it. Pass rule per price field: `|a-b| <= tol_ticks*tick + 1e-9*max(|a|,|b|)`; volume: `|a-b| <= frac*max + 1e-9*max`. First mismatch in `open_at` order, fields in order O,H,L,C,V. Ties (same source) keep the existing row. Inputs with duplicate `open_at`, unknown `source` or missing columns raise `MergeError`; invalid tick/tolerances too. `MergeError` subclasses `DataValidationError` (carries `tf`, `field`, `open_at`), so the CLI exits 4 through the existing handlers.
- `price_tick(exchange, symbol)` refuses unless `exchange.precisionMode == ccxt.TICK_SIZE` (else `precision.price` would be a digit count), then `load_markets()`; tick must be a non-bool finite number > 0, else `FetchError`. No retry/backoff on `load_markets` (one call per timeframe; ccxt caches markets).
- `update`: tick read before the cache/fetch (bad tick refuses before any request); `update_timeframe_with_stats` returns `(frame, OverlapStats)`, `update_timeframe` keeps its old signature. The `since` rule is unchanged, so update's overlap is normally empty (stats `rows_compared=0`).
- `import_archive(..., timeframes, *, tick, now=None, on_written=None)`: `tick` is keyword-only and required, checked (as `ArchiveError`) before the checksum. Per tf: existing non-empty cache is validated first (never merge into a defective cache), then read member -> `merge_candles` -> `apply_no_trade_policy` -> `validate_frame` -> `write_cache`. Merge comes before the no-trade fill, so an archive hole covered by an API row is not filled synthetically. `on_written(tf, frame, stats)`. The CLI reads the tick through `_exchange_factory` before the import even when no cache exists yet (one public metadata call; bad tick -> `DATA ERROR:` exit 4).
- Matrix "gap between sources": `apply_no_trade_policy` never fills a download gap; it is `validate_frame` that raises `download gap` (exit 4, nothing written) -- same outcome as specified.
- Story 3 test `test_existing_cache_refused_until_story_4` replaced by `test_existing_cache_reimport_merges_identically`: the refusal was explicitly temporary ("merge arrives in story 4"); the new specified behaviour is merge-with-check. Its other assertion (`len(existing["1d"]) == 10`) is kept; the byte-identity assertion became frame equality (the file is rewritten by the merge, content unchanged).
- `tests/data/fakes.py`: `FakeExchange` gained `markets`, `precisionMode` (TICK_SIZE) and `load_markets()`; `TICK = 0.1`; `DATA` gained the two tolerances. `tests/data/test_archive.py` gained an autouse fixture wiring a `FakeExchange` into `cli._exchange_factory` (the CLI import now reads the tick) and `tick=TICK` on direct `import_archive` calls.
- Real check 2026-11-11 (scratch var dir, not the repo `var/`): `bot data update` 1d+4h (719 API rows each), then `import-archive` of `Kraken_OHLCVT_2026Q3.zip` merged with the API cache: 1d 92 rows compared, 4h 469 compared, max price diff 0 ticks, max volume diff ~4e-14 (archive and API agree exactly); result 1d archive 92 / api 627, 4h archive 552 / api 250; `bot data validate` exit 0; a second `update` exit 0 with nothing new. ~4.3 s.

## Plan Change Log

- 2026-11-11 (review): price epsilon changed from `1e-9 x price` to `1e-6 x tick` -- at very high prices the price-relative epsilon exceeds a tick and would let 2 ticks pass, contradicting "exactly 1 tick passes and 2 ticks fail" (test at base 1e8). Volume keeps `1e-9 x larger volume`.
- 2026-11-11 (review): `import_archive` takes keyword-only `tick_provider: Callable[[], float]` instead of `tick`; called after the checksum, only when a non-empty cache must be merged, at most once per import. The CLI passes `lambda: price_tick(_exchange_factory(), pair)`, so a first import and checksum/format errors never touch the network. This supersedes the Implementation Notes lines about `tick` being required and checked before the checksum.
- 2026-11-11 (review): `MergeError` messages no longer repeat the timeframe (the CLI already prints `[tf]`); `.tf` stays on the exception, including for "frame unusable".

## Review Triage Log

### 2026-11-11 — Review pass
- verdicts: 4 findings — high 0, medium 1, low 3, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` import fetched the tick over the network before checksum/format checks (offline imports reported a network error instead of the real cause; first import needed network) — lazy `tick_provider` called only after checksum and only when merging; offline tests added.
  - `[low]` `[patch]` timeframe printed twice in merge errors — label dropped from messages, `.tf` kept.
  - `[low]` `[patch]` "frame unusable" MergeError lacked `tf` — passed.
  - `[low]` `[patch]` float epsilon grew with price (2 ticks could pass at ~1e8) — epsilon now 1e-6 × tick; high-price test added.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass

**Result 2026-11-11:** ruff check and format clean; 445 passed (83 new: 41 in `tests/data/test_merge.py`, plus additions to test_archive, test_cli_data, test_update, test_fetch, test_config_data).

## Auto Run Result

- Review (orchestrator): 4 patches (1 medium, 3 low), 0 deferred, 0 rejected; follow-up review recommended: false.
- Verification: full check → 454 passed. Real run by the implementer (scratch var dir): api 1d/4h then Q3 2026 archive import: 92 (1d) and 469 (4h) overlapping candles compared, max price diff 0 ticks, max volume diff ~4e-14; validate exit 0.
