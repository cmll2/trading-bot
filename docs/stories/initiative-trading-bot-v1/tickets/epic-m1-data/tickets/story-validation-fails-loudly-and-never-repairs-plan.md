---
title: 'Validation fails loudly and never repairs'
type: feature
ticket: '2'
created: '2026-11-11'
status: built
baseline_revision: 'ae6cc259913cdeb7e83f139695af3eea26c73631'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: true
context:
  - '{project-root}/docs/stories/initiative-trading-bot-v1/tickets/epic-m1-data/tickets/story-recent-daily-candles-downloaded-cached-and-validated-end-to-plan.md'
warnings: []
deferred:
  - summary: >-
      Acceptance criterion 2 (writer fills a no-trade gap, then bot data validate exits 0) is exercised only through a test stand-in writer.
    evidence: |-
      update_timeframe only receives api rows, so it can never create a no-trade gap; the archive importer (story 3) is the first production writer that fills.
    location: >-
      tests/data/test_cli_data.py
    severity: medium
---

<intent-contract>

## Intent

**Problem:** Story 1's validator checks only schema and timestamps. FR-03/AD-18 also need OHLC consistency, a split between legitimate no-trade intervals (archive omits empty intervals) and download gaps, the explicit `data.no_trade_policy`, and the synthetic-ratio cap.

**Approach:** Extend `bot/data/validate.py` with OHLC/source checks, gap classification, a pure `apply_no_trade_policy` used only by writers (import/update) before validation, and the ratio cap; `validate_frame` itself never modifies data. Add the policy settings to `data:`.

## Boundaries & Constraints

**Always:** validation is read-only: `validate_frame` never changes its input and `bot data validate` never rewrites the file; the fill happens only in `apply_no_trade_policy`, called by writers, and every filled row is marked `source="synthetic"`; the first defect in check order is reported with its `open_at`; every defect raises `DataValidationError` and `bot data validate` exits `EXIT_DATA_ERROR` (4).

**Never:** forward-fill or interpolate API-range or between-source gaps; drop, reorder or deduplicate rows inside validation; new dependencies; touch `config.yaml` `risk:`, `bot/risk/`, `tests/risk/`; weaken existing tests.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Duplicate / non-monotonic / misaligned / naive or non-UTC ts | frame with that defect | defect named with its `open_at` | `DataValidationError`, exit 4, file bytes unchanged |
| high < low, high < max(open,close), low > min(open,close), price ≤ 0 or non-finite, volume < 0 | one bad row | defect `inconsistent OHLC` (or `negative volume`) at that row | same |
| Unknown source value | `source="foo"` | defect `unknown source` | same |
| Archive-range gap, `fill_flat` | archive row t, archive row t+2i | `apply_no_trade_policy` inserts t+i: O=H=L=C=close(t), volume 0, trades 0, source synthetic; then `validate_frame` passes | none |
| Archive-range gap, `fail` | same | `apply_no_trade_policy` raises `no-trade gap` at t+i | `DataValidationError` |
| API-range gap | api row t, api row t+2i | `download gap` at t+i under both policies | `DataValidationError` |
| Between sources | archive row t, api row t+2i (or api then archive) | `download gap` | `DataValidationError` |
| Unfilled no-trade gap in a stored file | archive rows with a hole | `validate_frame` fails `no-trade gap not filled` (validation never fills) | `DataValidationError` |
| Bad synthetic row | synthetic row with volume > 0 or O/H/L/C ≠ previous close | defect `inconsistent synthetic candle` | `DataValidationError` |
| Policy `fail` with synthetic rows in file | any synthetic row | defect `synthetic candle under no_trade_policy=fail` | `DataValidationError` |
| Ratio cap | synthetic rows after `history_start` / rows after `history_start` > `max_synthetic_ratio` | defect names the ratio and the cap | `DataValidationError` |
| Synthetic before `history_start` | many synthetic rows only before it | passes; counted in the report | none |

</intent-contract>

## Code Map

- `bot/data/validate.py` -- extend story 1's validator (it has `CHECKS` list, `check_sources` already, `check_no_missing_interval` which today calls every hole a `download gap`, `read_cache_checked`, `validate_frame(df, tf, now=None)`; keep public names, change the signature to `validate_frame(df, tf, data_settings, now=None)` and update every caller in `bot/data/update.py`, `bot/cli.py` and tests): add `check_ohlc`, `check_synthetic_rows`, replace the missing-interval check with classification, gap classification helper `classify_missing(df, tf) -> list[(open_at, kind)]` with kind `no_trade` when both neighbours are `archive`/`synthetic`, else `download`; `apply_no_trade_policy(df, tf, policy) -> DataFrame` (returns a new normalized frame, sorted); `validate_frame(df, tf, data_settings, now=None)` adds policy and ratio checks; `ValidationReport` gains `synthetic_rows`, `synthetic_ratio_after_start`, `synthetic_by_year: dict[int, int]`.
- `bot/config.py` -- `DataSettings` gains `history_start: date`, `no_trade_policy: Literal["fill_flat","fail"]`, `max_synthetic_ratio: Decimal = Field(ge=0, lt=1)`; validator: `history_start` < `backtest.holdout_start` (cross-check in `Settings`).
- `config.yaml` -- in `data:` (above the PROTECTED banner only): `history_start: 2017-01-01` (provisional, re-measured in story 6), `no_trade_policy: fill_flat`, `max_synthetic_ratio: "0.001"`.
- `bot/data/update.py` -- call `apply_no_trade_policy` on the merged frame before `validate_frame`.
- `bot/cli.py` -- `bot data validate` passes `settings.data`; prints synthetic count, ratio after `history_start`, synthetic rows per year when non-zero.
- `tests/data/test_validate.py` (new) -- one test per matrix row, each asserting the defect name and `open_at`; CLI-level tests in `tests/data/test_cli_data.py` (add, never weaken existing) for exit 4 + unchanged file bytes (compare sha256 before/after).

## Tasks & Acceptance

**Execution:**
- [x] `bot/data/validate.py` -- checks, classification, policy, ratio -- FR-03, AD-18
- [x] `bot/config.py`, `config.yaml` -- policy settings -- explicit no-trade policy
- [x] `bot/data/update.py`, `bot/cli.py` -- wire policy and report -- writers fill, validator only checks
- [x] `tests/data/test_validate.py`, `tests/data/test_cli_data.py`, `tests/test_config.py` (add tests only) -- matrix coverage and config validation (bad policy refused, history_start after holdout refused)

**Acceptance Criteria:**
- Given each defect fixture, when `bot data validate` runs, then it exits 4 naming the defect and timestamp and the cache file's sha256 is unchanged.
- Given an archive-range gap, when a writer applies `fill_flat` and validates, then the written file contains a `synthetic` row with O=H=L=C=previous close and volume 0, and `bot data validate` exits 0.

## Implementation Notes

- Check order (`CHECKS`): columns, open_at UTC, dtypes, nulls, sources, unique, increasing, aligned, `check_ohlc`, `check_synthetic_rows`, `check_no_missing_interval`; then (in `validate_frame`) empty, last candle closed (if `now`), policy `fail` vs synthetic rows, ratio cap. `check_no_missing_interval` keeps its name (existing test pins it last) and now classifies: `download gap` or `no-trade gap not filled` at the first missing `open_at`.
- NaN prices are still reported by the earlier `check_no_nulls` as `null <col>`; `check_ohlc` catches ±inf and ≤ 0. Extra defect beyond the matrix: `negative trades`.
- Synthetic rows must also have `trades == 0` and a previous row; a synthetic first row is `inconsistent synthetic candle`.
- Ratio cap: rows with `open_at >= history_start 00:00 UTC`; compared exactly with `Decimal`; ratio equal to the cap passes. It is an aggregate defect, so it carries no `open_at` (CLI prints no ` at ...`).
- `apply_no_trade_policy` runs the structural checks (columns ... aligned) on the input as given, before any cast or sort, so wrong dtypes, unsorted rows, duplicates or misalignment raise `DataValidationError` and it never fills around them; writers must pass a sorted frame with cache dtypes. It raises `ValueError` on an unknown policy string. Download gaps are left for `validate_frame`. Under `fail` it reports the first no-trade hole even if a download gap precedes it.
- Review fixes: every run of consecutive synthetic rows must have an `archive` row immediately before and after it, else `synthetic candle outside archive range` at the run start (blocks forward-filled API gaps and fills spreading from them); +inf/negative volume is `non-finite or negative volume`; the update test asserts apply -> validate -> write order on the same frame object.
- `update_timeframe` validates the cache with `settings.data` (so an unfilled no-trade hole or a policy/cap breach in the stored file is refused before fetching), then applies the policy to the merged frame before validating. With API-only data the policy is a no-op; archive import (story 3) is the writer that will actually fill.
- CLI line gains `synthetic=N synthetic_ratio_from_{history_start}=R`; a second line `synthetic_by_year={...}` is printed only when non-zero.
- Test helpers: `DATA` (DataSettings matching config.yaml) and `rows(days, sources)` added to `tests/data/fakes.py`. Existing tests changed only to pass `DATA` to the new `validate_frame` signature. Extra tests in `tests/data/test_update.py` (policy wiring, cache with unfilled hole refused).
- Verification 2026-11-11: `uv run ruff check . && uv run ruff format --check . && uv run pytest` -> 311 passed. Real cache `bot data validate --timeframe 1d` -> exit 0, 719 api rows, synthetic=0, sha256 unchanged.

## Plan Change Log

## Review Triage Log

### 2026-11-11 — Review pass
- verdicts: 5 findings — high 0, medium 2, low 3, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` synthetic row bounded by api rows passed validation (forward-filled API gap accepted) — each synthetic run now needs an archive row immediately before and after; tests for api-bounded/start/end runs.
  - `[medium]` `[patch]` `apply_no_trade_policy` normalized before structure checks, hiding dtype defects and raising raw pandas errors — checks now run on the raw input; unsorted input refused; tests added.
  - `[low]` `[patch]` +inf volume named "negative volume" — renamed `non-finite or negative volume`.
  - `[low]` `[patch]` update policy test did not prove order/identity — spies assert apply → validate → write on the same object.
  - `[medium]` `[defer]` AC 2 met only through a stand-in writer in tests (no production writer can produce a no-trade gap until the archive importer) — to be proven end to end by story 3's import.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass

## Auto Run Result

- Summary: validator extended with OHLC/volume/trades/synthetic checks, no-trade vs download gap classification, `apply_no_trade_policy` (writers only), `fail` policy and synthetic-ratio cap from `data.history_start`; `data:` gains `history_start` (provisional 2017-01-01), `no_trade_policy: fill_flat`, `max_synthetic_ratio: "0.001"`.
- Files: `bot/data/validate.py`, `bot/data/update.py`, `bot/cli.py`, `bot/config.py`, `config.yaml` (data: only), `tests/data/*`, `tests/test_config.py` (tests added; existing calls updated for the new `validate_frame` argument only).
- Review: 4 patches (2 medium, 2 low), 1 deferred (medium), 0 rejected. Follow-up review recommended: true (two medium patched) — named risk: synthetic-run boundary rule interacts with story 4's precedence merge (api replacing a synthetic row inside a run would now fail validation).
- Verification: full check → 321 passed; real `bot data validate --timeframe 1d` exit 0, file unchanged.
