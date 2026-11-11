---
id: 13
type: story
title: "48-hour unattended dry-run with a forced restart"
parent: epic-m3-paper-engine-risk
covers: ["R21", "R13", "R8"]
after: [12]
refined: false
hitl: true
risk: medium
protected: false
---

# 48-hour unattended dry-run with a forced restart

## Description

Closing check: v0 and plumbing dry-runs run 48 h on this PC without intervention, including one forced process kill and restart; results recorded.

## Requirements

Verify: PROGRESS.md records start/end UTC, heartbeat gaps, errors count 0, reconciliation mismatches 0, and the forced-restart time with no duplicate orders.

1. **48 hours unattended** (brief §9 M3, NFR-04)
   **Given** the final M3 code
   **When** dry-run runs 48 h
   **Then** heartbeats show no gap longer than 2 ticks except the forced restart, and the errors table holds no unhandled error
2. **Forced restart survived** (FR-39, AD-8)
   **Given** the engine killed mid-run (Task Manager end task)
   **When** it restarts
   **Then** it resumes, reconciles with no mismatch and creates no duplicate order

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R21, R13, R8
- prd — docs/planning/prd.md, FR-29, FR-39, NFR-04
- architecture — docs/planning/architecture.md, AD-8
- architecture — docs/planning/architecture.md, AD-9
- architecture — docs/planning/architecture.md, AD-29

## Notes

- hitl: the operator keeps the PC on and performs the forced kill.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
