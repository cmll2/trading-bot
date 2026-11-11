---
id: 2
type: story
title: "Pure pre-trade checks and halt evaluation (protected)"
parent: epic-m2-backtest
covers: ["R19", "R20", "R21", "R22", "R23", "R24", "R27"]
after: ["epic-m1-data"]
refined: false
hitl: false
risk: high
protected: true
---

# Pure pre-trade checks and halt evaluation (protected)

## Description

bot/risk/checks.py and halts.py implement check_order and evaluate_halts exactly per AD-11, with tests/risk/ triggering every rule. PROTECTED: see Constraints.

## Requirements

Verify: tests/risk/ passes with one test per rule that triggers it and one that passes it, including the 24 submissions/day cap and flatten exemptions.

1. **Max position** (FR-31, AD-11)
   **Given** an order that increases exposure
   **When** (position + resting buys + qty) × price exceeds min(100% × equity, €25)
   **Then** check_order rejects with rule max_position; a sell is never rejected by it
2. **Orders per day** (FR-32, AD-11, PROGRESS)
   **Given** `max_order_intents_per_day` intents (20) already created on the UTC day
   **When** a first attempt of one more non-flatten intent is checked
   **Then** it is rejected as max_orders_per_day; a submission beyond `max_exchange_submissions_per_day` (120) on the day or `max_submissions_per_intent` (12) for the intent is rejected as max_submissions
   **And** flatten intents are exempt from the intent count only
3. **Halts** (FR-33, AD-11)
   **Given** equity ≤ 90% of day-open equity, or ≤ 75% of the active baseline
   **When** evaluate_halts runs
   **Then** it returns daily_loss or total_drawdown triggers; it never auto-expires
4. **Stale data and price sanity** (FR-34, FR-35, AD-11)
   **Given** the last closed candle older than 2 intervals or synthetic, or the ticker older than 120 s, or mid more than 2% from reference_price
   **When** check_order runs
   **Then** it rejects with stale_candle, stale_ticker or price_sanity and the reason text
   **And** stale_candle is exempt for flatten, stale_ticker and price_sanity are not
5. **Kill switch, halt, market status, minimums** (FR-36, AD-11, AD-13)
   **Given** kill switch engaged, an active halt, market status not online, or qty below minimums
   **When** a non-flatten order is checked
   **Then** it is rejected with that rule
6. **Pure and dedicated** (SAF-04, SAF-05, AD-10)
   **Given** risk/
   **When** it is imported and committed
   **Then** it does no I/O besides kill_switch_engaged reading, and the commit touches only bot/risk/ and tests/risk/

## Constraints

- PROTECTED (SAF-04): touches bot/risk/checks.py, bot/risk/halts.py, tests/risk/. Start only when the operator has asked for it explicitly in the chat; land it in a dedicated commit that touches nothing else.

## Boundaries

- Must not change: any file outside the protected paths in this story's commit.
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements R19, R20, R21, R22, R23, R24, R27
- prd — docs/planning/prd.md, FR-30, FR-31, FR-32, FR-33, FR-34, FR-35, FR-36, FR-61, SAF-04, SAF-05
- architecture — docs/planning/architecture.md, AD-10
- architecture — docs/planning/architecture.md, AD-11
- architecture — docs/planning/architecture.md, AD-12
- decisions — PROGRESS.md, orders/day interpretation

## Notes

- High risk: wrong semantics trade past limits. Extra check: the operator reads checks.py against the AD-11 table (part of GL-05).
- Every rejection returns a reason string the engine stores (FR-37).
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
