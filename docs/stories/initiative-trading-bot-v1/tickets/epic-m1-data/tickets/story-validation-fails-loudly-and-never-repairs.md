---
id: 2
type: story
title: "Validation fails loudly and never repairs"
parent: epic-m1-data
covers: ["R3"]
after: [1]
refined: false
hitl: false
risk: medium
protected: false
---

# Validation fails loudly and never repairs

## Description

data/validate.py checks uniqueness, monotonic and interval-aligned UTC timestamps and OHLC consistency, classifies missing intervals, and applies the no-trade policy.

## Requirements

Verify: Fixture tests: each defect type makes `bot data validate` exit non-zero naming the defect; a no-trade gap inside the archive range is filled flat with source=synthetic under `fill_flat`, and fails under `fail`.

1. **Every defect fails** (FR-03)
   **Given** a dataset with a duplicate, a non-monotonic step, a misaligned or non-UTC timestamp, or high < low
   **When** validation runs
   **Then** it exits non-zero naming the first defect and its timestamp, and the file is not rewritten
2. **No-trade vs download gap** (FR-03, AD-18)
   **Given** a missing interval inside the archive range and one inside the API range
   **When** validation runs with `fill_flat`
   **Then** the archive-range gap becomes an O=H=L=C=previous-close, volume-0 candle with source=synthetic; the API-range gap fails
3. **Synthetic ratio cap** (AD-18)
   **Given** synthetic candles above `data.max_synthetic_ratio` (0.1%) after `data.history_start`
   **When** validation runs
   **Then** it fails and reports the ratio

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m1-data/epic-m1-data.md, Requirements R3
- prd — docs/planning/prd.md, FR-03
- architecture — docs/planning/architecture.md, AD-18

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
