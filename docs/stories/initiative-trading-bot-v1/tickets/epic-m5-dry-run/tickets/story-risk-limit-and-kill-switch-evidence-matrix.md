---
id: 6
type: story
title: "Risk-limit and kill-switch evidence matrix"
parent: epic-m5-dry-run
covers: ["R4", "R5"]
after: [1]
refined: false
hitl: true
risk: medium
protected: false
---

# Risk-limit and kill-switch evidence matrix

## Description

One table mapping every AD-11 rule to the test that triggers it and the dry-run or plumbing event that showed it working, plus kill-switch engage from file and from the dashboard observed in dry-run.

## Requirements

Verify: docs/reviews/gl03-gl04-evidence.md lists every rule with a passing test id and an observed risk_events row (or an operator-witnessed scripted run), and two kill_on events with source=file and source=dashboard.

1. **Every limit triggered and seen** (GL-03, FR-61)
   **Given** the AD-11 rule list
   **When** the matrix is compiled
   **Then** each rule has a test id that triggers it and an observed event; a rule never seen in dry-run is triggered in an operator-witnessed run on a scratch store copy
2. **Kill switch both ways** (GL-04, FR-62)
   **Given** the plumbing dry-run
   **When** the operator engages from the file and later from the dashboard, then re-arms via CLI
   **Then** both kill_on events and the cancelled orders are recorded

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m5-dry-run/epic-m5-dry-run.md, Requirements R4, R5
- prd — docs/planning/prd.md, FR-61, FR-62, GL-03, GL-04
- architecture — docs/planning/architecture.md, AD-11
- architecture — docs/planning/architecture.md, AD-12
- architecture — docs/planning/architecture.md, AD-24

## Notes

- hitl: the operator engages the switch and witnesses the runs. Use the plumbing store so the v0 GL-01 window is not disturbed.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
