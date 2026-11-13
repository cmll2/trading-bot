---
title: 'Sizing, exchange minimums and dust handling'
type: feature
ticket: '7'
created: '2026-11-13'
status: in-review
baseline_revision: 'c6f6093'
route: oneshot
route_source: auto
risk: high
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

**Problem:** Sizing floors to the step but does not enforce exchange minimums or the AD-13 sellable-after-worst-loss threshold, and sell-side dust is not recorded.

**Approach:** `buy_qty` returns `NoOrder("below_minimum")` (never rounds up) when qty < amount_min, cost < cost_min, or the resulting position would not satisfy P ≥ amount_min and P × price × (1 − max_total_drawdown) ≥ cost_min; `sell_qty` (full base) rejects below minimums; the engine re-reads `MarketRules` at each intent, journals `below_minimum` with its reason plus a `rejection`/`minimums` risk event, and writes a `dust` risk event when a sell leaves 0 < base < amount_min. Fees in backtest come from config `fees`; rules from the recorded public snapshot.

</intent-contract>

## Implementation Notes

Oneshot (~80 lines of code + tests). Hand-computed 5-case table in `tests/test_sizing.py` (comments show the arithmetic). Files: `bot/sizing.py`, `bot/engine.py` (rules re-read per intent, sell-dust event, `sell_qty` price), `tests/test_sizing.py`.

## Plan Change Log

## Review Triage Log

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
