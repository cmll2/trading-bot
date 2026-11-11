---
id: 9
type: story
title: "Ledger CSV export by Europe/Paris tax year"
parent: epic-m4-dashboard
covers: ["R4", "R5", "R6"]
after: ["epic-m3-paper-engine-risk"]
refined: false
hitl: false
risk: medium
protected: false
---

# Ledger CSV export by Europe/Paris tax year

## Description

ledger.py and `bot ledger export --year Y` write the ledger view as CSV with UTC and Paris times, disposal flag, simulated column and mode in the filename.

## Requirements

Verify: Fixture fills around 31 Dec 23:30 UTC land in the right Paris year; a stablecoin-quoted fixture is not marked a disposal; dry-run file is named …_dry-run_SIMULATED.csv.

1. **Columns** (FR-46, CON-09, AD-19)
   **Given** the ledger view
   **When** export runs
   **Then** columns at_utc, at_paris, pair, side, qty, price, quote_ccy, gross_quote, fee, fee_ccy, is_crypto_to_fiat_disposal, simulated, exchange_trade_id are written
2. **Disposals and year** (FR-47, CON-10, AD-19)
   **Given** fills across a year boundary
   **When** --year Y runs
   **Then** rows belong to Y by Europe/Paris date and the disposal total sums gross_quote of sell-to-fiat rows
3. **Stablecoin support** (FR-48, CON-11)
   **Given** a fill quoted in a non-fiat currency
   **When** exported
   **Then** it is not a disposal
4. **Simulated never mixed** (NFR-09)
   **Given** a dry-run store
   **When** export runs
   **Then** the filename carries SIMULATED and simulated and live rows never share a file

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R4, R5, R6
- prd — docs/planning/prd.md, CON-09, CON-10, CON-11, FR-46, FR-47, FR-48, NFR-09
- architecture — docs/planning/architecture.md, AD-19

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
