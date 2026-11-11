---
id: 7
type: story
title: "M5 closing report and go-live evidence"
parent: epic-m5-dry-run
covers: ["R2", "R3", "R4", "R5", "R1"]
after: [5, 6]
refined: false
hitl: true
risk: medium
protected: false
---

# M5 closing report and go-live evidence

## Description

docs/reviews/M5-report.md states GL-01 and GL-02 PASS/FAIL over the window, DECAYING status, incidents and the evidence matrix, as input to the M6 decision.

## Requirements

Verify: The report exists with a PASS/FAIL line for GL-01 to GL-04, each citing evidence files and store queries.

1. **Verdicts with evidence** (GL-01, GL-02, GL-03, GL-04)
   **Given** the four weekly notes, the evidence matrix and the store
   **When** the report is written
   **Then** each GL line says PASS or FAIL and cites its evidence; profit is not a criterion (GL-06)
2. **Honest framing** (WR-05, WR-06, NFR-09)
   **Given** results
   **When** described
   **Then** every figure is labelled simulated and not presented as evidence of future profit

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m5-dry-run/epic-m5-dry-run.md, Requirements R2, R3, R4, R5, R1
- prd — docs/planning/prd.md, GL-01, GL-02, GL-03, GL-04, NFR-04, NFR-09, WR-05, WR-06
- architecture — docs/planning/architecture.md, AD-20

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
