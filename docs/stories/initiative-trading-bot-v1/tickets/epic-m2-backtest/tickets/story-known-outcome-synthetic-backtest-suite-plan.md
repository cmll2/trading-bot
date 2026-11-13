---
title: 'Known-outcome synthetic backtest suite'
type: feature
ticket: '11'
created: '2026-11-13'
status: built
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

### 2026-11-13 — Review pass
- verdicts: 8 findings — high 0, medium 2, low 5, false 1, maybe-false 0
- findings:
  - `[medium]` `[patch]` verdict line not compared exactly — every series now asserts the full line rebuilt from hand-computed finals.
  - `[medium]` `[patch]` taker variant never hand-checked for trading series — rising and gap tests derive taker fills, fees, equity.
  - `[low]` `[patch]` flat series fees/verdict unchecked — asserted.
  - `[low]` `[patch]` taker buy-and-hold not asserted in rising — asserted for both variants.
  - `[low]` `[patch]` sub-minimum count not derived — exactly 24 rejections, and the report shows them.
  - `[low]` `[patch]` wrong SMA in the gap comment — 41333.3.
  - `[low]` `[patch]` docstring omitted sell/taker rules — model documented in full.
  - `[false]` `[reject]` single-value parametrize / anomaly no-fill only — parametrize removed (start passed through `_run`); the fill branch is covered by `test_metrics_report.py` and the story only requires the listing.

## Auto Run Result

- Summary: six end-to-end known-outcome tests through `execute`; all values hand-derived; 2018-01-13 anomaly listed.
- Review: 7 patches, 1 rejected. Follow-up review recommended: false (test-only change; both mediums are test-strength improvements).
- Verification: `tests/backtest/test_known_outcomes.py` 6 passed; full check at commit.

## Verification

**Commands:**
- `uv run pytest tests/backtest/test_known_outcomes.py` -- expected: 6 passed
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
