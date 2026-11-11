---
id: 11
type: story
title: "Known-outcome synthetic backtest suite"
parent: epic-m2-backtest
covers: ["R26", "R25"]
after: [10]
refined: false
hitl: false
risk: medium
protected: false
---

# Known-outcome synthetic backtest suite

## Description

Closing end-to-end suite: synthetic price series with hand-derived outcomes run through `bot backtest` and assert trades, fees, metrics and rejections.

## Requirements

Verify: `pytest tests/backtest/test_known_outcomes.py` passes and covers rising, falling, flat, gap and sub-minimum series.

1. **Known outcomes** (FR-58)
   **Given** five synthetic series with hand-computed expected trades and returns
   **When** each is backtested
   **Then** trades, fees, ending equity and the verdict line match exactly
2. **Minimum rejection visible** (FR-13)
   **Given** a series that drives the target below minimum
   **When** it runs
   **Then** the rejection is logged and counted, not rounded

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements R26, R25
- prd — docs/planning/prd.md, FR-13, FR-57, FR-58
- architecture — docs/planning/architecture.md, AD-1
- architecture — docs/planning/architecture.md, AD-6
- architecture — docs/planning/architecture.md, AD-13

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
