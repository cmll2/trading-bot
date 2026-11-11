---
id: 10
type: story
title: "Plumbing strategy on its own store, never live"
parent: epic-m3-paper-engine-risk
covers: ["R1", "R2", "R20"]
after: [1]
refined: false
hitl: false
risk: medium
protected: false
---

# Plumbing strategy on its own store, never live

## Description

strategy/plumbing.py trades a short timeframe in dry-run only on var/state/dry-run-plumbing.sqlite to exercise orders, restarts and the dashboard; the registry refuses it outside backtest and dry-run.

## Requirements

Verify: Tests: plumbing builds for dry-run, is absent from LIVE_STRATEGIES, and a live build request is refused; a 1-hour dry-run produces several simulated orders tagged plumbing.

1. **Dry-run only** (FR-10, FR-63, AD-30)
   **Given** the registry
   **When** plumbing is requested for live
   **Then** it is refused; allowed_modes is {backtest, dry-run}
2. **Enough orders, isolated** (FR-09, AD-30)
   **Given** a dry-run plumbing session
   **When** it runs
   **Then** it generates orders on its own store and its trades never feed v0 review
3. **No edge claimed** (FR-09, NFR-09)
   **Given** its outputs
   **When** shown or logged
   **Then** they carry `plumbing — no edge` and SIMULATED

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R1, R2, R20
- prd — docs/planning/prd.md, FR-09, FR-10, FR-63, NFR-09
- architecture — docs/planning/architecture.md, AD-15
- architecture — docs/planning/architecture.md, AD-30

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
