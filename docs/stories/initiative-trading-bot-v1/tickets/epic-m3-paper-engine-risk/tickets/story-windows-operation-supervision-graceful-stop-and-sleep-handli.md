---
id: 11
type: story
title: "Windows operation: supervision, graceful stop and sleep handling"
parent: epic-m3-paper-engine-risk
covers: ["R21", "R23"]
after: [3]
refined: false
hitl: true
risk: medium
protected: false
---

# Windows operation: supervision, graceful stop and sleep handling

## Description

Documented Task Scheduler setup (at logon, restart on failure), CTRL+C/CTRL_BREAK graceful stop that finishes the tick and releases the lock, fatal-exit cancel, and post-sleep behaviour.

## Requirements

Verify: Test: a stop signal mid-tick commits and releases the lock; docs/operations/windows-supervision.md exists; the builder demonstrates a stop and restart.

1. **Graceful stop** (AD-29)
   **Given** a running engine
   **When** CTRL+C or CTRL_BREAK arrives
   **Then** the tick finishes, the state is committed, the lock is released and runs.stop_reason is set
2. **Fatal exit** (AD-29)
   **Given** a fatal error
   **When** the engine exits
   **Then** it first tries to cancel its known resting orders
3. **Local only** (NFR-06)
   **Given** the engine
   **When** it runs
   **Then** it opens no listening socket

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R21, R23
- prd — docs/planning/prd.md, NFR-04, NFR-06
- architecture — docs/planning/architecture.md, AD-29
- decisions — PROGRESS.md, Windows supervision decision

## Notes

- hitl: the operator creates the Task Scheduler task and sets power settings per the doc.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
