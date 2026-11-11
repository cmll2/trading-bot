---
id: 4
type: story
title: "Signals and trades page with journal"
parent: epic-m4-dashboard
covers: ["R9", "R1"]
after: [1]
refined: false
hitl: false
risk: low
protected: false
---

# Signals and trades page with journal

## Description

Price chart with the strategy indicator, entry and exit markers and current target, plus the signal journal with outcomes and would-have-returned values.

## Requirements

Verify: Against a fixture store with each outcome value, the journal lists each with its reason; markers match fills.

1. **Chart and markers** (FR-51)
   **Given** signals with indicators_json and fills
   **When** the page renders
   **Then** price, indicator, entry/exit markers and current target are shown
2. **Journal outcomes** (FR-40, AD-28)
   **Given** signals of every outcome
   **When** the journal renders
   **Then** each shows its outcome and reason, and untraded ones show the counterfactual return when `bot review` has computed it, else 'not computed'

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R9, R1
- prd — docs/planning/prd.md, FR-40, FR-51
- design — docs/planning/ux-dashboard/EXPERIENCE.md Signals & trades

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
