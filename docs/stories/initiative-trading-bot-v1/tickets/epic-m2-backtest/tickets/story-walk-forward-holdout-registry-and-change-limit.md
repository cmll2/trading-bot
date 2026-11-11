---
id: 9
type: story
title: "Walk-forward, holdout registry and change limit"
parent: epic-m2-backtest
covers: ["R9", "R10", "R11", "R14"]
after: [8]
refined: false
hitl: false
risk: high
protected: false
---

# Walk-forward, holdout registry and change limit

## Description

Walk-forward and parameter search refuse the fixed holdout range, record configurations tried, and the holdout run is once per strategy, recorded in results/holdout_runs.jsonl; `--change N` enforces ≤ 5 logged changes.

## Requirements

Verify: Tests: a search touching 2025-11-11 is refused; a second holdout run without `--rerun-holdout --reason` is refused; a dirty tree is refused; `--change 6` is refused; configs-tried count is in the results file.

1. **Holdout never tuned on** (FR-15, AD-21)
   **Given** a walk-forward or search range touching backtest.holdout_start
   **When** it runs
   **Then** it is refused naming the boundary
2. **One holdout run, visible** (FR-16, AD-21)
   **Given** an existing holdout_runs.jsonl line for the strategy, or a dirty git tree
   **When** a holdout run is requested
   **Then** it is refused unless `--rerun-holdout --reason` is given, which writes `rerun: true` and banners later reports
3. **Change discipline** (FR-17, AD-21)
   **Given** `bot backtest --change N`
   **When** N > 5 or changes.md lacks entry N
   **Then** it is refused
4. **Trials counted** (FR-20)
   **Given** a parameter search
   **When** it ends
   **Then** the results file states the number of configurations tried

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements R9, R10, R11, R14
- prd — docs/planning/prd.md, FR-15, FR-16, FR-17, FR-20
- architecture — docs/planning/architecture.md, AD-21

## Notes

- High risk: overfitting evidence. Extra check: the auditor diffs holdout_runs.jsonl against git log.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
