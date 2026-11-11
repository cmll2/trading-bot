---
id: 10
type: story
title: "Refactor sweep"
parent: epic-m2-backtest
covers: []
after: [1, 2, 3, 4, 5, 6, 7, 8, 9]
refined: false
hitl: false
risk: low
protected: false
---

# Refactor sweep

## Description

Cleanup-only pass over the M2 code, scoped at its start from the plans and review findings the epic deferred.

## Requirements

Verify: The single check command passes and the diff contains no new behaviour (reviewer confirms against the sweep scope list in the plan).

1. **Cleanup only** (NFR-01, WR-02)
   **Given** the deferred findings of the M2 stories, listed in this story's plan before it starts
   **When** the sweep is built
   **Then** each change maps to a listed finding and no behaviour, test assertion or protected file changes
   **And** scope pushed out of another story becomes a new story, not part of this one

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements (cleanup; no ids)
- prd — docs/planning/prd.md, NFR-01, WR-02


## Notes

- Never weakens a test (FR-64). Protected paths are out of scope; a protected cleanup is its own dedicated-commit story.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
