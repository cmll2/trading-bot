---
id: 3
type: story
title: "Typed settings loaded once from config.yaml and .env"
parent: epic-m0-scaffold
covers: ["R6"]
after: [1]
refined: false
hitl: false
risk: medium
protected: false
---

# Typed settings loaded once from config.yaml and .env

## Description

config.py loads every non-risk section of config.yaml plus `.env` into one frozen pydantic Settings, with paths made absolute.

## Requirements

Verify: Unit tests load a fixture config into Settings, reject an unknown key, a second pair and a relative-path escape, and Settings attributes cannot be reassigned.

1. **Frozen typed settings** (FR-30, AD-10)
   **Given** a valid config.yaml
   **When** Settings is loaded and an attribute is assigned
   **Then** the assignment raises; settings are loaded once in cli.py and passed down
2. **Sections and one pair** (CON-07, CON-08, CON-11, Conventions: Config)
   **Given** config.yaml
   **When** it is loaded
   **Then** sections exchange, pairs, capital, paper, strategy, execution, fees, slippage_bps, data, backtest, review, paths, fiat_currencies are validated; `pairs` is a list and v1 rejects any length other than 1; pair is `BTC/EUR`
   **And** an unknown key fails validation with its name; a timeframe other than 4h or 1d for v0 is refused, and the EUR quote means the stablecoin check (CON-07) does not apply
3. **PROGRESS.md values present** (PROGRESS decisions log)
   **Given** the committed config.yaml
   **When** it is read
   **Then** timeframe is 1d, approval is manual, execution window is 6 h with re-price every 30 min, backtest.holdout_start/holdout_end are 2025-11-11 and 2026-11-10 UTC, fees are 0.40%/0.80%

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m0-scaffold/epic-m0-scaffold.md, Requirements R6
- prd — docs/planning/prd.md, CON-07, CON-08, CON-11, FR-30, NFR-03
- architecture — docs/planning/architecture.md, Consistency conventions: Config, Paths

## Notes

- The `risk:` section and its model are story 4 (protected); this story must not touch them.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
