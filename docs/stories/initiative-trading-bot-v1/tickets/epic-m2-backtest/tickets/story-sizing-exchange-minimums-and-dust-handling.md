---
id: 7
type: story
title: "Sizing, exchange minimums and dust handling"
parent: epic-m2-backtest
covers: ["R7", "R25"]
after: [4]
refined: false
hitl: false
risk: high
protected: false
---

# Sizing, exchange minimums and dust handling

## Description

sizing.py computes order quantity per AD-13 at every submission, enforces amount/cost minimums and tick/step from MarketRules, and rejects (never rounds) sub-minimum orders with outcome below_minimum.

## Requirements

Verify: Unit tests: €20 equity buy sized by min(target×equity, caps, free/(1+fee)); a target under the sellable threshold yields below_minimum and a logged rejection; sell sizes the full base.

1. **Reject, never round** (FR-13, CON-02, AD-13)
   **Given** a computed qty below amount_min or cost below cost_min
   **When** sizing runs
   **Then** it returns NoOrder(below_minimum), the signal outcome is below_minimum and the reason is stored
2. **Sellable after worst loss** (AD-13)
   **Given** a buy whose resulting position P × price × 0.75 < cost_min
   **When** sizing runs
   **Then** the buy is refused as below_minimum
3. **Rules from metadata** (CON-03, AD-13)
   **Given** MarketRules
   **When** they are loaded
   **Then** minimums, tick and step come from market metadata at startup and at each intent; fees in backtest come from config `fees`

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements R7, R25
- prd — docs/planning/prd.md, CON-02, CON-03, FR-13, FR-57
- architecture — docs/planning/architecture.md, AD-13
- Conventions: Numbers, Fees

## Notes

- High risk: with €20 a sizing error strands dust or over-buys. Extra check: hand-computed table of 5 cases in the test.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
