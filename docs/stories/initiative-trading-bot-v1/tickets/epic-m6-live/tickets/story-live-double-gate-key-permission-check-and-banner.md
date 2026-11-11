---
id: 2
type: story
title: "Live double gate, key-permission check and banner"
parent: epic-m6-live
covers: ["R4", "R5", "R6", "R11"]
after: [1]
refined: false
hitl: false
risk: high
protected: false
---

# Live double gate, key-permission check and banner

## Description

cli.open_live_gate requires the --live flag, TRADING_BOT_LIVE=I_ACCEPT_REAL_ORDERS, a live-allowed strategy and timeframe, explicit approval mode, live fees equal to config, and a passing GetApiKeyInfo check; then prints the banner.

## Requirements

Verify: Tests (fake ccxt, temp secrets file outside repo) cover each refusal with exit code 2 and its named condition, withdraw permission refusal, call failure refusal, and the banner content.

1. **Both flag and env var** (SAF-09, FR-45, AD-15)
   **Given** `bot live` without --live or without the env value
   **When** it runs
   **Then** it exits 2 naming the missing condition and creates no broker
2. **Plumbing can never go live** (FR-10, FR-63, CON-08, SAF-08, AD-15)
   **Given** --strategy plumbing or a timeframe other than 4h/1d
   **When** `bot live --live` runs with the env var
   **Then** it exits 2
3. **Permissions fail closed** (SAF-06, SAF-07, FR-28, AD-14)
   **Given** GetApiKeyInfo failing, returning withdraw-funds/add-withdraw-address/update-withdraw-address, or missing a query/trade permission
   **When** startup runs
   **Then** it refuses before any other private call, writes permission_refusal and exits non-zero
   **And** it prints the IP allowlist or NOT RESTRICTED (SAF-03)
4. **Banner** (SAF-09, AD-15)
   **Given** all conditions met
   **When** startup completes
   **Then** the banner shows mode, balances, initial_*, baseline, every limit and limits_hash, and is logged
5. **Secrets only here** (SAF-01, SAF-02, AD-22)
   **Given** live startup
   **When** secrets load
   **Then** they come from the external file into SecretStr, only KrakenBroker receives them, and a planted-secret test finds them in no log or store row

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m6-live/epic-m6-live.md, Requirements R4, R5, R6, R11
- prd — docs/planning/prd.md, CON-08, FR-10, FR-28, FR-45, FR-63, NFR-07, SAF-01, SAF-02, SAF-06, SAF-07, SAF-08, SAF-09
- architecture — docs/planning/architecture.md, AD-14
- architecture — docs/planning/architecture.md, AD-15
- architecture — docs/planning/architecture.md, AD-22

## Notes

- High risk: the gate to real money. Extra check: auditor runs each refusal manually with a dummy key file outside the repo.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
