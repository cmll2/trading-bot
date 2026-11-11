---
id: 6
type: story
title: "Post-only execution window with re-pricing and cancel-and-skip"
parent: epic-m2-backtest
covers: ["R6", "R18", "R29"]
after: [4]
refined: false
hitl: false
risk: high
protected: false
---

# Post-only execution window with re-pricing and cancel-and-skip

## Description

The engine executes each intent per AD-5 and AD-28: post-only limit at best bid/ask, re-price every 30 min within a 6 h window, max 12 submissions per intent, completion phase, cancel and skip; PaperBroker fills through fill_model on closed 15m candles.

## Requirements

Verify: FakeClock tests on synthetic 15m candles: fill on strict trade-through, re-price after 30 min, skip with outcome not_filled at window end, completion phase for an unsellable partial buy.

1. **Fill model** (FR-12, FR-24, CON-04, AD-6)
   **Given** a buy at limit L accepted at time a
   **When** a closed 15m candle opening at or after a rounded up has low < L
   **Then** it fills in full at L with maker fee and slippage against the trader; a candle that began before a never fills it
2. **Window and re-pricing** (AD-5, PROGRESS)
   **Given** an unfilled order
   **When** 30 min pass inside the 6 h window
   **Then** cancel is confirmed and fills ingested before a new cl_ord_id is placed at the current best price, at most 12 submissions per intent
3. **Window end** (AD-28)
   **Given** no fill by window end
   **When** the window closes
   **Then** the intent ends done with signal outcome not_filled; a sellable partial ends partially_filled
4. **Taker variant** (CON-06, AD-5)
   **Given** the same signals
   **When** the taker variant runs
   **Then** it fills at the t+1 open with the taker fee for the report

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements R6, R18, R29
- prd — docs/planning/prd.md, CON-04, CON-06, FR-12, FR-24, NFR-08
- architecture — docs/planning/architecture.md, AD-5
- architecture — docs/planning/architecture.md, AD-6
- architecture — docs/planning/architecture.md, AD-7
- architecture — docs/planning/architecture.md, AD-27
- architecture — docs/planning/architecture.md, AD-28

## Notes

- High risk: execution drift between modes breaks GL-02. Extra check: the M3 backtest-vs-paper consistency test (4.9).
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
