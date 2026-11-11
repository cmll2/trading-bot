---
id: 5
type: story
title: "Clock port and closed-candle history view"
parent: epic-m1-data
covers: ["R4", "R5"]
after: [1]
refined: false
hitl: false
risk: high
protected: false
---

# Clock port and closed-candle history view

## Description

clock.py (SystemClock, SimClock, FakeClock) and an immutable CandleHistory that exposes only candles with open_at + interval ≤ clock.now(), plus MarketData port with a Replay adapter.

## Requirements

Verify: Unit tests with FakeClock: a candle becomes visible exactly at its close; mutating the view raises; ReplayMarketData serves the cache.

1. **Closed candles only** (FR-04, AD-3)
   **Given** FakeClock at 23:59:59 UTC and a 1d candle opened at 00:00
   **When** history is read
   **Then** the candle is absent; at 00:00:00 next day it is present
2. **Immutable view** (FR-06, AD-3)
   **Given** a CandleHistory
   **When** a caller tries to modify it
   **Then** it raises and the source cache is unchanged
3. **Dataset hash** (NFR-02, AD-21)
   **Given** a loaded dataset
   **When** it is loaded twice
   **Then** the same data hash is produced and is exposed for results records

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m1-data/epic-m1-data.md, Requirements R4, R5
- prd — docs/planning/prd.md, FR-04, FR-06, NFR-02
- architecture — docs/planning/architecture.md, AD-2
- architecture — docs/planning/architecture.md, AD-3
- architecture — docs/planning/architecture.md, AD-21

## Notes

- High risk: a leak here is look-ahead in every mode. Extra check: the M2 look-ahead guard (3.5) runs through this view.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
