---
id: 13
type: story
title: "All seven views verified against the dry-run database"
parent: epic-m4-dashboard
covers: ["R7", "R8", "R9", "R10", "R11", "R12", "R13", "R14"]
after: [12]
refined: false
hitl: true
risk: low
protected: false
---

# All seven views verified against the dry-run database

## Description

Closing check: the operator opens every view against the live M3 dry-run store (v0 and plumbing) and confirms each FR-50–FR-56 element.

## Requirements

Verify: A checklist in docs/audits/M4-views-checklist.md has one line per FR-50–FR-56 element marked seen by the operator with date.

1. **Every view works** (brief §9 M4)
   **Given** the dry-run database
   **When** each view is opened
   **Then** every element listed in FR-50 to FR-56 is visible with real data and SIMULATED tags

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R7, R8, R9, R10, R11, R12, R13, R14
- prd — docs/planning/prd.md, FR-49, FR-50, FR-51, FR-52, FR-53, FR-54, FR-55, FR-56
- design — docs/planning/ux-dashboard/EXPERIENCE.md Key Flows F1, F2

## Notes

- hitl: the operator does the walkthrough.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
