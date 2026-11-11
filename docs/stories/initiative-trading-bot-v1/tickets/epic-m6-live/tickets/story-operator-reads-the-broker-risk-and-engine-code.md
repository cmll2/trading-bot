---
id: 3
type: story
title: "Operator reads the broker, risk and engine code"
parent: epic-m6-live
covers: ["R7"]
after: [1, 2]
refined: false
hitl: true
risk: high
protected: false
---

# Operator reads the broker, risk and engine code

## Description

The operator reads bot/broker/, bot/risk/ and bot/engine.py in full, guided by a reading map, and records questions and sign-off.

## Requirements

Verify: PROGRESS.md records date, commit hash read, files and line counts, questions raised and their answers, and the operator's sign-off line (GL-05).

1. **Reading map** (GL-05, NFR-01)
   **Given** the frozen commit
   **When** the map is prepared
   **Then** docs/operations/code-reading-map.md lists each file, line count and the AD it implements, in reading order
2. **Signed reading** (GL-05)
   **Given** the operator's reading
   **When** it ends
   **Then** PROGRESS.md holds the commit read and the sign-off; any change to these files after it voids the sign-off

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m6-live/epic-m6-live.md, Requirements R7
- prd — docs/planning/prd.md, GL-05, NFR-01
- architecture — docs/planning/architecture.md, Capability map (GL-05, NFR-01)

## Notes

- hitl: entirely the operator's work. Extra check: the auditor confirms no commit touched these files after the signed hash.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
