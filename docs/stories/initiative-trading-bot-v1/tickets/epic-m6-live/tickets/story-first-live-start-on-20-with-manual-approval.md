---
id: 5
type: story
title: "First live start on €20 with manual approval"
parent: epic-m6-live
covers: ["R5", "R4"]
after: [4]
refined: false
hitl: true
risk: high
protected: false
---

# First live start on €20 with manual approval

## Description

The operator starts `bot live --live` with the env var; the banner, permission output and reconciliation are checked; the first intent is approved or rejected by hand.

## Requirements

Verify: PROGRESS.md records the run id, banner snapshot (no secrets), IP allowlist line, reconciliation result and the first intent's outcome.

1. **Live start** (SAF-09, FR-45)
   **Given** a go decision
   **When** the operator starts live
   **Then** the banner is shown and logged, initial_quote = min(EUR balance, €20 allocation) and reconciliation passes
2. **Manual approval** (FR-44, AD-16)
   **Given** the first live intent
   **When** it is created
   **Then** it waits for `bot approve` or `bot reject` and nothing is sent before

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m6-live/epic-m6-live.md, Requirements R5, R4
- prd — docs/planning/prd.md, FR-28, FR-44, FR-45, SAF-09
- architecture — docs/planning/architecture.md, AD-15
- architecture — docs/planning/architecture.md, AD-16
- architecture — docs/planning/architecture.md, AD-26

## Notes

- hitl: only the operator runs live. Never started by an agent (SAF-10).
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
