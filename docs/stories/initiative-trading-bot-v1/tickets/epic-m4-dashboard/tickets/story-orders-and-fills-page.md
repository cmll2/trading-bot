---
id: 5
type: story
title: "Orders and fills page"
parent: epic-m4-dashboard
covers: ["R10"]
after: [1]
refined: false
hitl: false
risk: low
protected: false
---

# Orders and fills page

## Description

Orders table with status, fills with price, fee and slippage versus the signal price, filterable by date.

## Requirements

Verify: Fixture store: filtering a date range shows only its rows; slippage_bps matches fill vs reference price.

1. **Orders and fills** (FR-52)
   **Given** orders and fills rows
   **When** the page renders with a date filter
   **Then** only rows in range appear with status, price, fee and slippage vs signal price

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R10
- prd — docs/planning/prd.md, FR-52
- design — docs/planning/ux-dashboard/EXPERIENCE.md Orders & fills

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
