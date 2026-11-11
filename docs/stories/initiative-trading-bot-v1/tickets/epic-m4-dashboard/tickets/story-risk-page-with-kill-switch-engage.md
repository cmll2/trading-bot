---
id: 2
type: story
title: "Risk page with kill-switch engage"
parent: epic-m4-dashboard
covers: ["R11", "R15"]
after: [1]
refined: false
hitl: false
risk: high
protected: false
---

# Risk page with kill-switch engage

## Description

Risk view: each limit with usage from risk_snapshots, rejection/halt/kill history, kill-switch state, and an Engage button with confirmation that calls risk.kill_switch.engage.

## Requirements

Verify: Test: clicking Engage then confirming creates the kill file with source=dashboard and the engine (FakeBroker) halts on next tick; no disengage control exists; usage values come from risk_snapshots.

1. **Engage only, with confirm** (FR-53, FR-62, GL-04, AD-12)
   **Given** the switch armed
   **When** the operator clicks Engage and confirms
   **Then** the kill file is created via risk.kill_switch.engage(source=dashboard) and the panel shows Requested then ENGAGED
   **And** no button can disengage; the panel names `bot kill off` for the terminal
2. **Usage read, never recomputed** (AD-17)
   **Given** risk_snapshots rows
   **When** the page renders
   **Then** each limit shows configured value and usage from the latest snapshot with warn at 80% and fail at 100%, read-only
3. **History with reasons** (FR-37, FR-53)
   **Given** risk_events and halts
   **When** the page renders
   **Then** rejections, halts and kill events are listed with rule, reason and UTC time, filterable by date

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R11, R15
- prd — docs/planning/prd.md, FR-37, FR-53, FR-62, GL-04
- architecture — docs/planning/architecture.md, AD-12
- architecture — docs/planning/architecture.md, AD-17
- design — docs/planning/ux-dashboard/EXPERIENCE.md Risk, Kill switch button

## Notes

- High risk: the only write path. Extra check: auditor confirms the app has no other file or DB write call (grep + AST).
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
