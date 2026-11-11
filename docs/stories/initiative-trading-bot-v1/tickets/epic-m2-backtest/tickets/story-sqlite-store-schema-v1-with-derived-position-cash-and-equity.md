---
id: 3
type: story
title: "SQLite store schema v1 with derived position, cash and equity"
parent: epic-m2-backtest
covers: ["R12", "R28"]
after: ["epic-m1-data"]
refined: false
hitl: false
risk: medium
protected: false
---

# SQLite store schema v1 with derived position, cash and equity

## Description

store.py and migrations/0001_init.sql create the §2 schema with pragmas, write-once schema_meta, idempotency keys and derived-quantity helpers; works on a file or :memory:.

## Requirements

Verify: Unit tests: migrations apply and version-check; duplicate signal, cl_ord_id, trade id, active halt and day-open inserts are refused; derived cash/position/equity match a hand-computed fill sequence.

1. **Schema and pragmas** (FR-39, AD-7, §2)
   **Given** a new database
   **When** the store opens it read-write
   **Then** every §2 table, index and the ledger view exist, WAL/synchronous=FULL/foreign_keys are on, and schema_version matches the code or startup fails
2. **Idempotency keys** (§2 Idempotency keys)
   **Given** a second insert of the same signal_id, cl_ord_id, (exchange, trade id), active halt rule or day-open row
   **When** it is attempted
   **Then** it is refused by the database
3. **Derived, never stored balances** (AD-26)
   **Given** initial_quote, initial_base and a fill list
   **When** position, cash and equity_at(t) are requested
   **Then** they are computed from these values plus fills only, as Decimal; schema_meta initial_* cannot be overwritten

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements R12, R28
- prd — docs/planning/prd.md, FR-18, FR-39, NFR-02
- architecture — docs/planning/architecture.md, §2 State store
- architecture — docs/planning/architecture.md, AD-7
- architecture — docs/planning/architecture.md, AD-17
- architecture — docs/planning/architecture.md, AD-26

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
