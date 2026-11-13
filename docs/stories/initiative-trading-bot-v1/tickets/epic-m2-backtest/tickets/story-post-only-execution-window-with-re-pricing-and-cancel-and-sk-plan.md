---
title: 'Post-only execution window with re-pricing and cancel-and-skip'
type: feature
ticket: '6'
created: '2026-11-13'
status: in-review
baseline_revision: 'fb93518'
route: full
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

**Problem:** The skeleton places one post-only order per intent and waits for the window end; AD-5/AD-28 require re-pricing every 30 min (max 12 submissions), immediate re-price on a post-only cross, cancel-and-skip, a completion phase for an unsellable partial buy, synthetic candles non-fillable (audit M1 F-2) and a taker report variant (CON-06).

**Approach:** Engine `_advance_intent` re-prices after `reprice_interval` only once the previous order's cancel is confirmed and its fills ingested (AD-27); `_resubmit` re-sizes and re-risk-checks every submission; window end → `not_filled` / `partially_filled` / `completing`; completion re-prices the smallest valid buy toward the sellable threshold until `completion_end_at`, else `dust` (+ risk event + error). While the ticker is stale (exchange halt) the resting order is kept rather than re-priced. Taker variant: `pricing="aggressive"` (ask for buy, bid for sell) + PaperBroker `liquidity="taker"` immediate fill with taker fee; `bot backtest` runs both variants.

## Boundaries & Constraints

**Always:** one shared fill model (`bot/broker/fill_model.py`) used by PaperBroker; strict trade-through; candles that began before the order never fill; synthetic candles never fill; fees and slippage on every simulated fill; every submission risk-checked.

**Never:** market orders in v1 order logic; touch protected files.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected | Error Handling |
|---|---|---|---|
| flat window | bid never traded through | 12 submissions at :00:30/:30:30, all cancelled; outcome not_filled | none |
| strict trade-through | low == L, later low < L | no fill at ==, fill at L x (1+slip) | none |
| placed mid-candle | candle opened before accepted_at trades through | no fill | none |
| synthetic window | halt candles below the bid | never fill; order kept; not_filled | none |
| partial unsellable buy | fill 0.00005 < amount_min | completing; completion buy 0.00006; done partially_filled — or dust at completion end | dust risk event + errors row |
| cross / reject | PostOnlyWouldCross / OrderRejected | immediate re-price / intent cancelled + exchange_reject event | none |
| taker variant | same signals | fills at once at ask x (1+slip), taker fee | none |

</intent-contract>

## Code Map

- `bot/engine.py` -- `_advance_intent`, `_resubmit`, `_end_window`, `_end_completion`, `_price` (taker side fixed), first-submission cross/reject handling, stale-ticker no-churn.
- `bot/sizing.py` -- `sellable_threshold`, `sellable`, `completion_qty`, `ceil_step`.
- `bot/broker/paper.py`, `bot/broker/fill_model.py` -- (from story 4) reviewed here in full.
- `bot/backtest/runner.py` -- `backtest_engine_config`, `orders` in RunResult; `bot/backtest/command.py` -- taker run.
- `tests/backtest/synth.py` (candle overrides, synthetic trades = 0), `tests/backtest/test_execution.py`.

## Tasks & Acceptance

**Execution:**
- [x] files above.

**Acceptance Criteria:**
- Given an unfilled order, when 30 min pass inside the 6 h window, then cancel is confirmed and fills ingested before a new cl_ord_id is placed at the current best price, at most 12 submissions per intent.

## Implementation Notes

Implemented in the coordinator's main session. Bug found by the new taker test: the aggressive pricing branch priced taker buys at the bid (too favourable); fixed before commit. Stale-ticker no-churn is a refinement of AD-28 ("a later risk rejection cancels") for exchange halts, logged as a decision.

## Plan Change Log

## Review Triage Log

## Verification

**Commands:**
- `uv run pytest tests/backtest/test_execution.py` -- expected: pass
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
