---
id: 6
type: story
title: "Weekly review job with GL-02 metrics and DECAYING flag"
parent: epic-m4-dashboard
covers: ["R1", "R2", "R3"]
after: [1]
refined: false
hitl: false
risk: high
protected: false
---

# Weekly review job with GL-02 metrics and DECAYING flag

## Description

`bot review` re-runs the backtest over the dry-run period from a hashed cache snapshot and writes backtest_predictions, signal_counterfactuals and weekly_reviews with its own lock.

## Requirements

Verify: Fixture test: per-fill max difference vs 0.5%, equity difference vs 2 pp, flags insufficient_trades (<20), decaying, no_edge_baseline computed as specified; runs while the engine runs.

1. **Same basis comparison** (FR-41, GL-02, AD-20)
   **Given** a dry-run period
   **When** `bot review` runs
   **Then** it re-runs the backtest on the same period with review.backtest_run_ref config and a data hash, and writes max per-fill price difference and equity difference in pp
2. **DECAYING rule** (FR-42, AD-20, PROGRESS)
   **Given** closed round trips and averages
   **When** flags are computed
   **Then** <20 trades → insufficient_trades; avg realized < 0.5 × positive backtest avg → decaying; backtest avg ≤ 0 → no_edge_baseline
3. **Counterfactuals** (FR-40, AD-20)
   **Given** untraded signals
   **When** review runs
   **Then** each gets the return from the t+1 open to the next target change at maker cost
4. **Own lock and tables** (AD-17)
   **Given** the engine running
   **When** review runs
   **Then** it writes only its three tables under review.lock

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R1, R2, R3
- prd — docs/planning/prd.md, FR-40, FR-41, FR-42, GL-02
- architecture — docs/planning/architecture.md, AD-17
- architecture — docs/planning/architecture.md, AD-20

## Notes

- High risk: GL-02 go-live verdict. Extra check: auditor recomputes one week by hand.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
