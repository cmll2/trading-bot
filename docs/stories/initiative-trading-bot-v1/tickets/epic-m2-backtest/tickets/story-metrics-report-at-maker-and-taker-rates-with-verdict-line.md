---
id: 8
type: story
title: "Metrics report at maker and taker rates with verdict line"
parent: epic-m2-backtest
covers: ["R8", "R12", "R13", "R15", "R26", "R28", "R30"]
after: [6]
refined: false
hitl: false
risk: medium
protected: false
---

# Metrics report at maker and taker rates with verdict line

## Description

backtest/metrics.py and the report writer produce every FR-14 metric for strategy and benchmarks at both fee variants, the bootstrap Sharpe CI, and the provenance record.

## Requirements

Verify: Synthetic known-outcome series reproduce hand-computed metrics; the report's first line states whether the strategy beat buy-and-hold after costs; results JSON holds commit, dirty flag, config hash, data range and hash.

1. **All metrics, both rates** (FR-14, CON-06)
   **Given** a run
   **When** the report is written
   **Then** total and annualized return, max drawdown, Sharpe, trades, turnover, fees, time in market appear for strategy, buy-and-hold and cash at maker and taker rates
2. **Verdict first** (FR-19, WR-05)
   **Given** a strategy that does not beat buy-and-hold after costs
   **When** the report is written
   **Then** its first line says so
3. **Provenance and CI** (FR-18, FR-21, NFR-02, AD-21)
   **Given** a run
   **When** results/{date}_{strategy}_{commit}.json is written
   **Then** it contains commit, dirty flag, config hash, data range, data hash, change number and a bootstrap CI on Sharpe; the same inputs give the same file content
4. **Labelled simulated** (NFR-09)
   **Given** the report
   **When** it is read
   **Then** it is labelled SIMULATED

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements R8, R12, R13, R15, R26, R28, R30
- prd — docs/planning/prd.md, CON-06, FR-14, FR-18, FR-19, FR-21, FR-58, NFR-02, NFR-09, WR-05
- architecture — docs/planning/architecture.md, AD-21

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
