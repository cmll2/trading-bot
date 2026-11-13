---
title: 'Sizing, exchange minimums and dust handling'
type: feature
ticket: '7'
created: '2026-11-13'
status: built
baseline_revision: 'c6f6093'
route: oneshot
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

**Problem:** Sizing floors to the step but does not enforce exchange minimums or the AD-13 sellable-after-worst-loss threshold, and sell-side dust is not recorded.

**Approach:** `buy_qty` returns `NoOrder("below_minimum")` (never rounds up) when qty < amount_min, cost < cost_min, or the resulting position would not satisfy P ≥ amount_min and P × price × (1 − max_total_drawdown) ≥ cost_min; `sell_qty` (full base) rejects below minimums; the engine re-reads `MarketRules` at each intent, journals `below_minimum` with its reason plus a `rejection`/`minimums` risk event, and writes a `dust` risk event when a sell leaves 0 < base < amount_min. Fees in backtest come from config `fees`; rules from the recorded public snapshot.

</intent-contract>

## Implementation Notes

Oneshot (~80 lines of code + tests). Hand-computed 5-case table in `tests/test_sizing.py` (comments show the arithmetic). Files: `bot/sizing.py`, `bot/engine.py` (rules re-read per intent, sell-dust event, `sell_qty` price), `tests/test_sizing.py`.

## Plan Change Log

## Review Triage Log

### 2026-11-13 — Review pass
- verdicts: 10 findings — high 0, medium 2, low 7, false 1, maybe-false 0
- findings:
  - `[medium]` `[patch]` a below-minimum re-price remainder of a partial buy skipped completion — now enters the AD-28 completion phase; test.
  - `[medium]` `[patch]` no risk event for below_minimum at re-price — `rejection`/`minimums` event written.
  - `[low]` `[patch]` remainder >= amount_min but < cost_min left unsellable silently — "held" and the dust check use both minimums.
  - `[low]` `[patch]` rules re-read after `_decide` — re-read before deciding.
  - `[low]` `[patch]` `load_market` inside the signal transaction — moved before it.
  - `[low]` `[patch]` no test for sell-side dust — FakeBroker partial-sell test.
  - `[low]` `[patch]` no test that rules are re-read per intent — `load_market` call test (fees-from-config asserted in story 6's slippage/fee test).
  - `[low]` `[patch]` sellable-threshold not tested end to end — backtest at ~5,000 EUR with 0.55 EUR.
  - `[false]` `[reject]` `_ = date` dummy — already removed before commit (ruff fixed the import).
  - `[low]` `[patch]` table row 3 unreachable — replaced by the reachable re-price case (partial 0.00005, budget 18).

## Auto Run Result

- Summary: reject-never-round minimums, sellable-after-worst-loss threshold, rules per intent, dust events.
- Review: 9 patches, 1 rejected. Follow-up review recommended: true by formula (2 medium) — named risk: minimum-change mid-intent paths are unit-tested only.
- Verification: full check at commit.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
