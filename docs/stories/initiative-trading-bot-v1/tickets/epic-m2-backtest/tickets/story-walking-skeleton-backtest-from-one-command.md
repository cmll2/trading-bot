---
id: 4
type: story
title: "Walking-skeleton backtest from one command"
parent: epic-m2-backtest
covers: ["R1", "R2", "R3", "R4", "R5", "R18"]
after: [1, 2, 3]
refined: false
hitl: false
risk: medium
protected: false
---

# Walking-skeleton backtest from one command

## Description

Tracer: `bot backtest --strategy v0_trend` runs Engine(PaperBroker, SimClock, ReplayMarketData, :memory: store) over cached 1d candles with the v0 MA filter and writes a results file with total return versus buy-and-hold and cash.

## Requirements

Verify: On a synthetic series with a known trend the command produces the expected trades and return; on the real cache it writes results/*.json labelled SIMULATED.

1. **Same engine, adapters swapped** (FR-11, SAF-08, AD-1)
   **Given** the backtest command
   **When** it runs
   **Then** it builds the same Engine class as dry-run with PaperBroker, SimClock, ReplayMarketData and an in-memory store, with approval forced to autonomous; engine.py has no mode branch except labels
2. **Pure v0 strategy** (FR-05, FR-06, FR-07, AD-3)
   **Given** v0_trend built by the registry with frozen params from config
   **When** on_candle is called
   **Then** it returns 0 or 1 from closed candles only and touches no broker, clock or network
3. **Benchmarks beside the result** (FR-08)
   **Given** a run
   **When** the results file is written
   **Then** it shows strategy, buy-and-hold and cash total return for the same range
4. **Every submission passes risk** (FR-30, AD-10)
   **Given** an order intent
   **When** the engine submits
   **Then** risk.check_order is called first and its decision is passed to place_order

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements R1, R2, R3, R4, R5, R18
- prd — docs/planning/prd.md, FR-05, FR-06, FR-07, FR-08, FR-11, FR-24, FR-30, SAF-08
- architecture — docs/planning/architecture.md, AD-1
- architecture — docs/planning/architecture.md, AD-3
- architecture — docs/planning/architecture.md, AD-6
- architecture — docs/planning/architecture.md, AD-10

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
