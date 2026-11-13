---
title: 'Look-ahead guard by prefix invariance'
type: feature
ticket: '5'
created: '2026-11-13'
status: built
baseline_revision: 'dacdba0'
route: full
route_source: auto
risk: high
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: true
context: []
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** Nothing detects a strategy using future data; brief §9 M2 requires a guard and a test that plants a t+1 leak.

**Approach:** `bot/backtest/lookahead.py` reruns the whole pipeline (fresh `load_dataset` looked up at call time, fresh registry strategy, fresh engine) at `backtest.lookahead_cutpoints` seeded cutpoints k with every candle from k's close replaced by a seeded random walk — and again by its mirror image (negated returns) so any direction-dependent leak differs in at least one — stopping right after k is evaluated; targets for candles ≤ k must equal the baseline's or `LookAheadError` is raised. `bot backtest` runs it before writing anything; the CLI exits 5 with no report.

## Boundaries & Constraints

**Always:** data enters only through `bot.backtest.dataset.load_dataset`; the guard runs on every `bot backtest`; no report on failure.

**Never:** weaken the guard to make v0 pass; touch protected files.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error Handling |
|---|---|---|---|
| planted leak | strategy reads candle t+1 from a module-level reference to the loaded frame | LookAheadError, no results files | CLI exit 5 |
| v0 | v0_trend | guard passes; payload records cutpoints, candles compared, seed | none |
| whole pipeline | N cutpoints | 1 baseline load + 2N fresh loads with replace_after set; a fresh strategy per run | none |

</intent-contract>

## Code Map

- `bot/backtest/lookahead.py` -- new guard.
- `bot/backtest/dataset.py` -- `replace_after`, `seed`, `mirror` (random walk with ±1σ drift).
- `bot/backtest/command.py`, `bot/cli.py` -- guard before any write; `EXIT_LOOKAHEAD = 5`.
- `tests/test_lookahead.py` -- planted leak, fresh-load/fresh-strategy counting, v0 passes, second seed.

## Tasks & Acceptance

**Execution:**
- [x] files above.

**Acceptance Criteria:**
- Given a planted t+1 leak via a module-level frame reference, when the backtest runs, then LookAheadError is raised and no results file or report is written.

## Implementation Notes

Implemented in the coordinator's main session. Mirrored reruns added after observing that one random future catches a sign-of-tomorrow leak only ~50% of the time per cutpoint. Known limit (documented in the module): a strategy that reads Parquet itself or freezes the baseline frame in a never-refreshed global escapes; the import rules cover the first.

## Plan Change Log

## Review Triage Log

### 2026-11-13 — Review pass
- verdicts: 7 findings — high 0, medium 2, low 4, false 0, maybe-false 1
- findings:
  - `[medium]` `[patch]` CLI exit 5 never tested (leaky id refused by the registry first) — test patches `cli.strategy_class_for`; asserts exit 5, no files, message.
  - `[medium]` `[patch]` too-short range reported as look-ahead failure — now `InsufficientData` (exit 4).
  - `[low]` `[patch]` `candles_compared` counted twice — counts distinct candles.
  - `[low]` `[patch]` docstrings overstated the mirror guarantee — now "direction-dependent" plus the size/range/volume limit.
  - `[low]` `[patch]` `ReplayMarketData.from_frames` could fall back to disk — frames-only instances refuse unknown keys.
  - `[low]` `[patch]` CLI caught every ValueError — narrowed to `InsufficientData`; bad params/holdout become `BacktestRefused`.
  - `[maybe-false]` `[reject]` 1d and 15m random futures are independent — reruns stop before any fill on replaced data; documented in `_random_walk_after`; would only be low.

## Auto Run Result

- Summary: prefix-invariance guard with random-walk + mirrored futures at seeded cutpoints, whole pipeline rerun, runs before any write; planted t+1 leak caught (`tests/test_lookahead.py::test_planted_t_plus_1_leak_raises_and_no_report_is_written`).
- Review: 6 patches, 0 deferred, 1 rejected. Follow-up review recommended: true by formula (2 medium) — named risk: guard power against size-only leaks (documented limit); the M2 audit should plant its own leak (story note).
- Verification: `uv run pytest tests/test_lookahead.py` 5 passed; full check at commit.

## Verification

**Commands:**
- `uv run pytest tests/test_lookahead.py` -- expected: pass
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
