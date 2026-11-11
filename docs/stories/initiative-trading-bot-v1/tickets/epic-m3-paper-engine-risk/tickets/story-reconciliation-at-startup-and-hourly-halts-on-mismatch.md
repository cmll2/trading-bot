---
id: 3
type: story
title: "Reconciliation at startup and hourly halts on mismatch"
parent: epic-m3-paper-engine-risk
covers: ["R8", "R11"]
after: [2]
refined: false
hitl: false
risk: high
protected: false
---

# Reconciliation at startup and hourly halts on mismatch

## Description

The engine compares open orders, base balance, quote balance and fills between store and broker (paper tables in dry-run) at startup and hourly, and halts on any mismatch.

## Requirements

Verify: FakeBroker tests: an unknown open order, a base balance off by one step, or an unmatched fill each write risk_events, insert a reconcile_mismatch halt, cancel own orders and exit non-zero.

1. **Mismatch stops the bot** (FR-29, AD-9)
   **Given** a foreign open order, base balance ≠ derived position, quote balance < derived cash, or an unmatched fill
   **When** reconciliation runs
   **Then** a risk_events row and a halts(reconcile_mismatch) row are written, both sides are logged, own resting orders are cancelled best-effort, and the process exits non-zero
2. **When it runs** (AD-9, AD-29)
   **Given** startup, every hour, and after more than 10 minutes without a tick (sleep)
   **When** the engine runs
   **Then** reconciliation executes

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R8, R11
- prd — docs/planning/prd.md, FR-29, FR-37
- architecture — docs/planning/architecture.md, AD-9
- architecture — docs/planning/architecture.md, AD-29

## Notes

- High risk: GL-01 depends on it. Extra check: auditor edits a paper_fills row in a copy of the store and confirms the halt.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
