---
id: 3
type: story
title: "Overview page with equity curve against buy-and-hold and cash"
parent: epic-m4-dashboard
covers: ["R8"]
after: [1]
refined: false
hitl: false
risk: low
protected: false
---

# Overview page with equity curve against buy-and-hold and cash

## Description

Overview per FR-50: mode, engine status and heartbeat, equity, cash, open position, return since start, total fees, equity curve vs buy-and-hold and cash, pending approvals read-only.

## Requirements

Verify: Against a fixture store the figures equal derived quantities from store.py helpers and the chart has three series with distinct line styles.

1. **Figures from shared helpers** (FR-50, §2 Derived quantities)
   **Given** a fixture store
   **When** Overview renders
   **Then** equity, cash, position, return and fees equal the store helpers' values
2. **Curve with benchmarks** (FR-50, FR-08)
   **Given** equity_snapshots
   **When** the chart renders
   **Then** strategy, buy-and-hold and cash series are shown, distinguishable without colour
3. **Pending approvals read-only** (AD-16, UX Pending approvals)
   **Given** an awaiting_approval intent
   **When** Overview renders
   **Then** it is listed with the CLI command to approve, with no button

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R8
- prd — docs/planning/prd.md, FR-08, FR-50
- design — docs/planning/ux-dashboard/EXPERIENCE.md Overview

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
