---
id: 6
type: story
title: "Manual halt reset and flatten from the CLI"
parent: epic-m3-paper-engine-risk
covers: ["R9", "R11"]
after: [5]
refined: false
hitl: false
risk: high
protected: false
---

# Manual halt reset and flatten from the CLI

## Description

`bot reset-halt <rule> --note [--rebase-baseline]` and `bot flatten --note` write operator_actions; the engine consumes them at startup and each tick per AD-12 and AD-25.

## Requirements

Verify: Tests: a daily_loss halt stays until reset; reset without --rebase keeps the baseline; with it appends an equity_baselines row; flatten while halted sells the full base through every applicable risk check.

1. **Manual only, never timed** (FR-33, AD-12)
   **Given** an active halt
   **When** time passes with no reset action
   **Then** the halt stays active
2. **Baseline rebase explicit** (AD-26, PROGRESS)
   **Given** a total_drawdown reset
   **When** it is consumed
   **Then** the baseline changes only with --rebase-baseline and the action id is recorded
3. **Flatten is the only sell while stopped** (AD-25, AD-11)
   **Given** a halt or engaged kill switch and an open position
   **When** `bot flatten --note` is consumed
   **Then** any active intent is cancelled (skipped_by_operator), a flatten intent sells the full base, exempt from orders/day, stale_candle and halt/kill but not stale_ticker, price_sanity or minimums
4. **CLI writes only operator_actions** (AD-17, SAF-05)
   **Given** any CLI command
   **When** it runs
   **Then** it inserts only into operator_actions and never touches limits

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R9, R11
- prd — docs/planning/prd.md, FR-33, FR-37, SAF-05
- architecture — docs/planning/architecture.md, AD-12
- architecture — docs/planning/architecture.md, AD-17
- architecture — docs/planning/architecture.md, AD-25
- architecture — docs/planning/architecture.md, AD-26

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).

## Added from M2 audit (2026-11-13)

- The backtest models this manual reset as a SIMULATED RESET at the next UTC daily close (`backtest.simulated_halt_reset`), through `Engine.reset_halts`; the CLI path must reuse that method (one writer of `halts`, AD-17), with `--rebase-baseline` mapping to `rebase_rules=("total_drawdown",)`.
- The completion phase is now a separate intent linked by `intents.parent_intent_id` (audit M2 F-3); `bot flatten` must cancel an active completion intent like any other.
