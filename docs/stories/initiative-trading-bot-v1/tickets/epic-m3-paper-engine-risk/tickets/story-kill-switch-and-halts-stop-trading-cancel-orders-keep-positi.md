---
id: 5
type: story
title: "Kill switch and halts stop trading: cancel orders, keep position"
parent: epic-m3-paper-engine-risk
covers: ["R9", "R10", "R11", "R18", "R19"]
after: [2, 4]
refined: false
hitl: false
risk: high
protected: false
---

# Kill switch and halts stop trading: cancel orders, keep position

## Description

Each tick snapshots the kill switch and evaluates halts before any submission; when engaged or halted the engine blocks intents, cancels resting non-flatten orders, moves the active intent to halted and keeps the position; `bot kill on/off --note` via operator_actions.

## Requirements

Verify: FakeBroker tests for file, CLI and each halt rule: resting order cancelled in the same tick, final fills ingested, outcome halted, position unchanged, risk_events written; `bot kill off` deletes the file only through the engine.

1. **Order of checks** (FR-36, AD-12)
   **Given** a tick
   **When** it starts
   **Then** kill switch and halts are evaluated before any submission and the file is re-read just before every place_order
2. **Stop behaviour** (FR-33, FR-36, AD-12)
   **Given** kill switch engaged or a halt active
   **When** the tick runs
   **Then** new intents and submissions are blocked, resting non-flatten orders are cancelled and their fills ingested, the active intent becomes halted, and no sell is placed automatically
3. **Stored with reasons** (FR-37)
   **Given** each kill_on, kill_off, halt and rejection
   **When** it happens
   **Then** a risk_events row with rule and reason is written once per state change
4. **Disengage only via CLI** (AD-12, UX control boundary)
   **Given** `bot kill off --note`
   **When** the engine consumes the operator action
   **Then** the engine deletes the file and logs kill_off; no other process deletes it

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R9, R10, R11, R18, R19
- prd — docs/planning/prd.md, FR-33, FR-36, FR-37, FR-61, FR-62
- architecture — docs/planning/architecture.md, AD-11
- architecture — docs/planning/architecture.md, AD-12
- architecture — docs/planning/architecture.md, AD-17
- research — docs/planning/ux-dashboard/EXPERIENCE.md — Control boundary

## Notes

- High risk: the emergency stop. Extra check: GL-04 evidence matrix in M5 (6.6).
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
