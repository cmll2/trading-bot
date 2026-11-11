---
id: 5
type: story
title: "Week 4 dry-run review"
parent: epic-m5-dry-run
covers: ["R6", "R7", "R2", "R3"]
after: [4]
refined: false
hitl: true
risk: low
protected: false
---

# Week 4 dry-run review

## Description

Same review for week 4, closing the 28-day window.

## Requirements

Verify: docs/reviews/week-4.md exists with the same facts and the window marked complete (28/28 days).

1. **Review run and read** (FR-41, GL-02, AD-20)
   **Given** week 4 of the dry-run window
   **When** the operator runs `bot review` and opens Dry-run vs backtest, Health and Risk
   **Then** docs/reviews/week-4.md records per-fill and equity verdicts (window d/28), DECAYING status, error and mismatch counts
2. **Incidents handled by the fixed rule** (GL-01)
   **Given** any unhandled error or reconciliation mismatch in the week
   **When** the review finds it
   **Then** it is logged with a bug ticket and the 28-day count restarts per story 1
3. **Nothing changed from the dashboard** (SAF-05, WR-05)
   **Given** the review
   **When** findings are written
   **Then** no setting or limit is changed and no result is presented as profit evidence

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m5-dry-run/epic-m5-dry-run.md, Requirements R6, R7, R2, R3
- prd — docs/planning/prd.md, FR-41, FR-42, GL-01, GL-02, SAF-05, WR-05
- architecture — docs/planning/architecture.md, AD-20

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
