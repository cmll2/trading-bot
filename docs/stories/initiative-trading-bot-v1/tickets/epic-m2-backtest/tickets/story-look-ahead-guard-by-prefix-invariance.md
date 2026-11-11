---
id: 5
type: story
title: "Look-ahead guard by prefix invariance"
parent: epic-m2-backtest
covers: ["R16"]
after: [4]
refined: false
hitl: false
risk: high
protected: false
---

# Look-ahead guard by prefix invariance

## Description

backtest/lookahead.py reruns the whole pipeline at N seeded cutpoints with the future replaced by a random walk and raises LookAheadError on any differing past target.

## Requirements

Verify: tests/test_lookahead.py: a strategy reading t+1 through a module-level reference raises LookAheadError and no report is written; v0 passes.

1. **Leak caught by any path** (FR-22, AD-4)
   **Given** a planted strategy that reads candle t+1 via a module-level frame reference
   **When** the backtest runs
   **Then** LookAheadError is raised and no results file or report is written
2. **Whole pipeline rerun** (AD-4)
   **Given** `backtest.lookahead_cutpoints` = 12
   **When** the guard runs
   **Then** each rerun loads the dataset fresh, builds a fresh strategy and engine, and compares targets for candles ≤ k

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements R16
- prd — docs/planning/prd.md, FR-22
- architecture — docs/planning/architecture.md, AD-4

## Notes

- High risk: this is the M2 done-when. Extra check: the auditor plants a second leak of their own.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
