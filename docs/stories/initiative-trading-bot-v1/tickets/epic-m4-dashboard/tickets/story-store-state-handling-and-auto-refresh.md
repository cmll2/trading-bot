---
id: 11
type: story
title: "Store-state handling and auto-refresh"
parent: epic-m4-dashboard
covers: ["R7"]
after: [1]
refined: false
hitl: false
risk: low
protected: false
---

# Store-state handling and auto-refresh

## Description

Unreadable, locked and stale-engine states per the UX State Patterns, 30 s fragment refresh with pause and refresh-now, paused while the confirm dialog is open.

## Requirements

Verify: Tests: a locked DB keeps prior data with `refresh failed`, three failures switch to unreadable; a stale heartbeat shows HEARTBEAT STALE.

1. **States** (UX State Patterns)
   **Given** store missing, locked, or engine stale
   **When** the page refreshes
   **Then** each shows its specified text and never keeps stale numbers on an unreadable store
2. **Refresh** (FR-49)
   **Given** the app open
   **When** 30 s pass
   **Then** data fragments refresh unless paused or the dialog is open

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R7
- prd — docs/planning/prd.md, FR-49
- design — docs/planning/ux-dashboard/EXPERIENCE.md State Patterns, Interaction Primitives

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
