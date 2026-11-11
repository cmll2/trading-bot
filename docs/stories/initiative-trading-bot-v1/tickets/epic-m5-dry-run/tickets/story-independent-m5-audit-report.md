---
id: 8
type: story
title: "Independent M5 audit report"
parent: epic-m5-dry-run
covers: ["R8", "R9"]
after: [1, 2, 3, 4, 5, 6, 7]
refined: false
hitl: true
risk: medium
protected: false
---

# Independent M5 audit report

## Description

A reviewer who wrote none of the M5 code audits the milestone per brief §8 and the operator reads the report before the M5 review.

## Requirements

Verify: docs/audits/M5-audit.md exists, rates every M5 criterion PASS/FAIL/INCONCLUSIVE with evidence, and PROGRESS.md points to it.

1. **Fresh reviewer runs the suite** (FR-65)
   **Given** the M5 stories are in review and the reviewer did not write any of the M5 code
   **When** the reviewer runs the single check command (tests, lint, format) itself in a fresh session or subagent
   **Then** the audit report records the command, its exit code and the test counts it observed, not the builder's
2. **Git history is read for weakened tests and protected-file discipline** (FR-64, WR-08, FR-65, SAF-04)
   **Given** the commits made during M5
   **When** the reviewer reads the history
   **Then** every deleted, skipped, xfailed or weakened test and every commit that mixes protected paths (config.yaml `risk:`, bot/risk/, tests/risk/) with other paths is listed as FAIL
   **And** every extra holdout run in results/holdout_runs.jsonl is listed (AD-21)
3. **Bias, cost and overfitting checks** (FR-65, CON-04, NFR-08)
   **Given** the M5 deliverables
   **When** the reviewer looks for look-ahead bias, missing fees or slippage and overfitting
   **Then** each finding and each milestone acceptance criterion is rated PASS, FAIL or INCONCLUSIVE with its evidence
4. **Operator sees the report first** (FR-66, WR-01, WR-06, WR-07)
   **Given** the audit report is written
   **When** the milestone is handed to the operator
   **Then** docs/audits/M5-audit.md exists, PROGRESS.md names it with the milestone summary, the design choices explained at the milestone start and anything flagged as wrong or unsafe, and known limitations, and work stops until the operator has reviewed it
   **And** no FAIL is left unresolved without an operator decision recorded in PROGRESS.md (SM-1)

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m5-dry-run/epic-m5-dry-run.md, Requirements R8, R9
- prd — docs/planning/prd.md, CON-04, FR-64, FR-65, FR-66, NFR-08, SAF-04, WR-01, WR-06, WR-07, WR-08
- architecture — docs/planning/architecture.md, AD-21
- architecture — docs/planning/architecture.md, AD-24

## Notes

- hitl: the operator reads the report and runs the milestone review; the reviewer is a fresh session, a separate subagent or `bmad-code-review` (brief §8).
- The builder of this milestone may not perform this story.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
