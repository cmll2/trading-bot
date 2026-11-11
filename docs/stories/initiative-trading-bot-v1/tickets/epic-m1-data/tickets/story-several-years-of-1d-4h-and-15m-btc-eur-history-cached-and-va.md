---
id: 6
type: story
title: "Several years of 1d, 4h and 15m BTC/EUR history cached and validated"
parent: epic-m1-data
covers: ["R1", "R2", "R3"]
after: [3, 4, 5]
refined: false
hitl: true
risk: medium
protected: false
---

# Several years of 1d, 4h and 15m BTC/EUR history cached and validated

## Description

The operator-supplied archive plus `bot data update` produce validated caches for all three timeframes; history depth and early gaps are reported.

## Requirements

Verify: `bot data validate` exits 0 for 1d, 4h and 15m; PROGRESS.md records first/last candle, synthetic ratio and the 2013–2016 gap audit.

1. **Milestone data present** (brief §9 M1, FR-02)
   **Given** the archive and the API
   **When** import and update run
   **Then** 1d, 4h and 15m Parquet files exist covering several years up to the last closed candle
2. **History depth stated** (AS-02, WR-04)
   **Given** the cached data
   **When** the run ends
   **Then** first and last `open_at`, row counts, synthetic ratio and any 2013–2016 daily gaps are written to PROGRESS.md
3. **Holdout window untouched** (FR-15, AD-21)
   **Given** the fixed holdout 2025-11-11 → 2026-11-10 UTC in config
   **When** the data is cached
   **Then** no backtest or search is run on it in this milestone

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m1-data/epic-m1-data.md, Requirements R1, R2, R3
- prd — docs/planning/prd.md, FR-01, FR-02, FR-03, FR-15, WR-04
- architecture — docs/planning/architecture.md, AD-18
- architecture — docs/planning/architecture.md, AD-21
- research — docs/research/pair-selection.md

## Notes

- hitl: the operator supplies the archive (story 3).
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
