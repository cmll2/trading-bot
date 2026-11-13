---
title: 'Post-only execution window with re-pricing and cancel-and-skip'
type: feature
ticket: '6'
created: '2026-11-13'
status: built
baseline_revision: 'fb93518'
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

### 2026-11-13 — Review pass
- verdicts: 10 findings — high 1, medium 4, low 4, false 1, maybe-false 0
- findings:
  - `[high]` `[patch]` completion shared the window's 12-submission count, so it could never run after a full window — completion phase counts its own submissions (`_phase_submissions`, still <= 12 and under the daily cap); risk rejections/unsizable completion orders wait instead of cancelling; test after 12 re-prices ends `dust`. Interpretation logged in PROGRESS.
  - `[medium]` `[patch]` last allowed order cancelled for a 13th submission that cannot be sent — re-price skipped when the phase cap is reached; test.
  - `[medium]` `[patch]` re-price after a cross reused the stale price — ticker re-fetched; an unmoved book waits for the next tick; test.
  - `[medium]` `[patch]` AD-27 settle timeout missing — `execution.fill_settle_timeout_seconds: 60`; overdue `cancel_requested` halts `reconcile_mismatch`; test.
  - `[medium]` `[patch]` completion-reached branch could finish with an unconfirmed cancel — finishes only once no live order remains.
  - `[false]` `[reject]` sell-side dust not recorded at window end — already added in `_finish` by story 7 (9d71e81).
  - `[low]` `[patch]` completion qty sized at mid could fall below cost_min at the bid — sized at the limit price.
  - `[low]` `[patch]` backtest stopped before the last completion phase — hard end includes the completion window.
  - `[low]` `[patch]` report text omitted the taker variant — the story 8 report shows both variants.
  - `[low]` `[patch]` slippage test did not check maker slippage — fills now carry the order limit; test asserts price = limit x (1 ± 5 bp) and fee = qty x price x rate for both variants.

## Auto Run Result

- Summary: AD-5/AD-28 execution in the shared engine; one fill model; taker report variant; synthetic candles never fill.
- Review: 9 patches, 0 deferred, 1 rejected. Follow-up review recommended: true (a high was patched) — named risk: completion-phase interpretation (own submission count) is a reading of AD-28 for the operator/audit to confirm.
- Verification: `tests/backtest/test_execution.py` all pass; full check at commit.

## Verification

**Commands:**
- `uv run pytest tests/backtest/test_execution.py` -- expected: pass
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
