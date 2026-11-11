---
id: 4
type: story
title: "Archive and API merged with an overlap check"
parent: epic-m1-data
covers: ["R1", "R3"]
after: [3]
refined: false
hitl: false
risk: medium
protected: false
---

# Archive and API merged with an overlap check

## Description

Where archive and API ranges overlap, candles must agree within tolerance before the merged cache is written.

## Requirements

Verify: Fixture test: overlapping candles that differ by 2 ticks fail the merge; within 1 tick and 1% volume they merge, keeping per-row source.

1. **Overlap must agree** (FR-03, AD-18)
   **Given** archive and API candles for the same `open_at`
   **When** they are merged
   **Then** OHLC differing by more than 1 tick or volume by more than 1% fails the update and nothing is written
2. **Gap between sources fails** (AD-18)
   **Given** a missing interval between archive end and API start
   **When** validation runs
   **Then** it is a download gap and fails

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m1-data/epic-m1-data.md, Requirements R1, R3
- prd — docs/planning/prd.md, FR-01, FR-03
- architecture — docs/planning/architecture.md, AD-18

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
