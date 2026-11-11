---
id: 7
type: story
title: "First live weeks monitoring cadence"
parent: epic-m6-live
covers: ["R8"]
after: [5]
refined: false
hitl: true
risk: medium
protected: false
---

# First live weeks monitoring cadence

## Description

Weekly during the first live weeks: `bot review`, dashboard check, ledger export check, approval log review, in docs/reviews/live-week-N.md; switch to autonomous only on the operator's recorded decision.

## Requirements

Verify: At least the first live-week note exists with errors, mismatches, approvals, fills vs expected and disposal total.

1. **Weekly live note** (FR-41, FR-47)
   **Given** a live week
   **When** the review runs
   **Then** the note records errors, mismatches, approvals, fills versus backtest and the year-to-date disposal total
2. **Mode change recorded** (FR-44, PROGRESS)
   **Given** a wish to go autonomous
   **When** it is decided
   **Then** the decision is a dated PROGRESS.md line before the config changes

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m6-live/epic-m6-live.md, Requirements R8
- prd — docs/planning/prd.md, FR-41, FR-44, FR-47, GL-06
- architecture — docs/planning/architecture.md, AD-16
- architecture — docs/planning/architecture.md, AD-19
- architecture — docs/planning/architecture.md, AD-20

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
