---
title: 'Known-outcome synthetic backtest suite'
type: feature
ticket: '11'
created: '2026-11-13'
status: in-review
baseline_revision: 'ea9e8a19ec12968dabaadc4b0b38fb1bdd768d01'
route: oneshot
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** M2 needs a closing end-to-end suite proving the one command produces hand-derivable trades, fees, ending equity and verdicts on synthetic series (FR-58), that sub-minimum orders are rejected and counted (FR-13), and (audit M1 F-3) that the 2018-01-13 anomaly appears in the report.

**Approach:** `tests/backtest/test_known_outcomes.py` runs `execute` (behind `bot backtest`: maker + taker, guard, metrics, report) on rising, falling, flat, gap-down round-trip and sub-minimum series, deriving expected fill prices, quantities, fees, final equity, buy-and-hold equity and verdict lines by explicit arithmetic from the execution model in the module docstring; plus a range covering 2018-01-13 whose report lists the anomaly.

</intent-contract>

## Implementation Notes

Oneshot (test-only). The first draft's gap series had an equal close (v0: "not above" → flat), which moved the sell one day earlier; the series was corrected to keep v0 long until the gap — the engine was right, the hand derivation was wrong.

## Plan Change Log

## Review Triage Log

## Verification

**Commands:**
- `uv run pytest tests/backtest/test_known_outcomes.py` -- expected: 6 passed
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
