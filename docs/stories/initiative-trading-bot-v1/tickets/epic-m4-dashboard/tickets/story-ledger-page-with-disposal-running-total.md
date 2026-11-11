---
id: 10
type: story
title: "Ledger page with disposal running total"
parent: epic-m4-dashboard
covers: ["R14", "R5"]
after: [9]
refined: false
hitl: false
risk: low
protected: false
---

# Ledger page with disposal running total

## Description

View 7: fills ledger with running crypto→EUR disposal total for the selected Europe/Paris year, account-wide, and a CSV download using the export function.

## Requirements

Verify: Fixture store: header total equals the export's total; dry-run title reads `Ledger — SIMULATED (paper fills, not for tax)`.

1. **Running total** (FR-56, FR-47)
   **Given** fills in a year
   **When** the page renders
   **Then** disposal rows are marked with a running total equal to the CLI export
2. **Labels** (NFR-09)
   **Given** dry-run mode
   **When** the page renders
   **Then** the title and total carry the simulated wording of the UX spec

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R14, R5
- prd — docs/planning/prd.md, FR-47, FR-56, NFR-09
- architecture — docs/planning/architecture.md, AD-19
- design — docs/planning/ux-dashboard/EXPERIENCE.md Ledger

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
