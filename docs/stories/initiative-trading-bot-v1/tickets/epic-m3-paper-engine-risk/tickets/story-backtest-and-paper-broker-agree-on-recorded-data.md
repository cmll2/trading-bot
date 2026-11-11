---
id: 9
type: story
title: "Backtest and paper broker agree on recorded data"
parent: epic-m3-paper-engine-risk
covers: ["R17", "R4"]
after: [1]
refined: false
hitl: false
risk: high
protected: false
---

# Backtest and paper broker agree on recorded data

## Description

Dry-run records the bid/ask it priced from; a consistency test replays the same recorded 15m candles and bid/ask through the backtest path and the paper path and asserts identical trades.

## Requirements

Verify: `pytest tests/test_consistency.py` passes on a recorded fixture of at least 10 intents including a re-price and a not_filled.

1. **Same trades** (FR-60, AD-6)
   **Given** recorded candles and bid/ask from a dry-run session
   **When** they are replayed through backtest and paper paths
   **Then** fills, prices, fees and outcomes are identical
2. **Recorded inputs** (AD-6)
   **Given** dry-run pricing
   **When** an order is priced
   **Then** the bid/ask used is stored in api_calls detail

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R17, R4
- prd — docs/planning/prd.md, FR-24, FR-60
- architecture — docs/planning/architecture.md, AD-6

## Notes

- High risk: GL-02 is meaningless without it. Extra check: auditor perturbs one recorded price and sees the test fail.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
