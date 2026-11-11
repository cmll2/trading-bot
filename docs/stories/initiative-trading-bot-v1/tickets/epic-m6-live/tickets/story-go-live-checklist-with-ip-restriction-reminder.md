---
id: 4
type: story
title: "Go-live checklist with IP-restriction reminder"
parent: epic-m6-live
covers: ["R9", "R10", "R7", "R8"]
after: [3]
refined: false
hitl: true
risk: high
protected: false
---

# Go-live checklist with IP-restriction reminder

## Description

One checklist in docs/operations/go-live-checklist.md walks GL-01 to GL-06, the key setup (query and trade only, no withdrawal), the SAF-03 IP restriction, €20 allocation, manual approval, and the open architecture questions.

## Requirements

Verify: The checklist is complete with each line ticked or answered by the operator and the go/no-go decision recorded in PROGRESS.md.

1. **Go-live criteria** (GL-01, GL-02, GL-03, GL-04, GL-05)
   **Given** the M5 report, evidence matrix and the reading sign-off
   **When** the checklist is walked
   **Then** each GL line cites its evidence and a FAIL blocks go-live
2. **IP restriction reminder** (SAF-03)
   **Given** the checklist
   **When** the key step is reached
   **Then** it reminds the operator to restrict the key to the PC's IP if it is stable, and records yes/no and the reason
3. **Key created by the operator** (SAF-06, SAF-02)
   **Given** the new key
   **When** the operator creates it on Kraken
   **Then** it has query and trade permissions only, the secrets file is outside the repo, and no one pastes the key in chat
4. **Decision is the operator's** (GL-06)
   **Given** a no-edge result
   **When** the decision is made
   **Then** it is recorded either way; profit is not a criterion

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m6-live/epic-m6-live.md, Requirements R9, R10, R7, R8
- prd — docs/planning/prd.md, GL-01, GL-02, GL-03, GL-04, GL-05, GL-06, SAF-02, SAF-03, SAF-06
- architecture — docs/planning/architecture.md, AD-14
- architecture — docs/planning/architecture.md, AD-26
- decisions — PROGRESS.md, approval mode

## Notes

- hitl: operator answers each line. Also record answers to architecture Q-5, Q-9, Q-10.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
