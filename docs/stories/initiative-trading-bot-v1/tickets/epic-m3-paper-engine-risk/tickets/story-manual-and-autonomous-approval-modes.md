---
id: 7
type: story
title: "Manual and autonomous approval modes"
parent: epic-m3-paper-engine-risk
covers: ["R15", "R14"]
after: [2]
refined: false
hitl: false
risk: medium
protected: false
---

# Manual and autonomous approval modes

## Description

`execution.approval` manual or autonomous; in manual an intent waits in awaiting_approval until `bot approve <id>` or `bot reject <id> --note`, and expires at window end.

## Requirements

Verify: FakeClock tests: approve moves to working, reject and deadline both give skipped_by_operator; re-prices inside ±2% need no re-approval but still pass risk.

1. **Manual approval** (FR-44, AD-16)
   **Given** approval=manual and a new intent
   **When** it is created
   **Then** it waits in awaiting_approval and the order with its allowed price band is printed and logged
2. **Reject or expire** (FR-40, AD-16, AD-28)
   **Given** an awaiting intent
   **When** it is rejected or its deadline passes
   **Then** it ends with signal outcome skipped_by_operator
3. **Approval covers the intent** (AD-16)
   **Given** an approved intent
   **When** it re-prices within the band
   **Then** no new approval is asked and risk checks still run on every submission

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R15, R14
- prd — docs/planning/prd.md, FR-40, FR-44
- architecture — docs/planning/architecture.md, AD-16
- architecture — docs/planning/architecture.md, AD-28

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
