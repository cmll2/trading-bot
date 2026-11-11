---
id: 1
type: story
title: "KrakenBroker adapter tested against a fake ccxt"
parent: epic-m6-live
covers: ["R1", "R2", "R3"]
after: ["epic-m5-dry-run"]
refined: false
hitl: false
risk: high
protected: false
---

# KrakenBroker adapter tested against a fake ccxt

## Description

bot/broker/kraken.py implements the Broker port on ccxt.kraken with clientOrderId, postOnly and oflags=fciq, find_order over open and closed orders, fee rates from fetch_trading_fee, and error mapping to the taxonomy.

## Requirements

Verify: Unit tests with an injected fake ccxt check outgoing order params, find_order lookups, post-only crossing in both forms, minimum/tick errors and fail-closed fees; no network.

1. **Order parameters** (FR-26, AD §1, PROGRESS)
   **Given** any buy or sell
   **When** place_order sends it
   **Then** the request carries clientOrderId=cl_ord_id, postOnly and oflags fciq; a fill with fee in another currency halts (AD-27)
2. **Duplicate lookup** (FR-26, AD-8)
   **Given** a cl_ord_id
   **When** find_order runs
   **Then** it queries OpenOrders then ClosedOrders filtered by cl_ord_id
3. **Error mapping** (FR-27, AD §1)
   **Given** EOrder:Cost minimum not met, Order minimum not met, Tick size check failed, a post-only error or an accepted-then-cancelled post-only, a timeout after send, rate limit, auth error
   **When** raised by fake ccxt
   **Then** they map to OrderRejected, PostOnlyWouldCross, OrderOutcomeUnknown, RateLimited and FatalBrokerError respectively
4. **Fees and rules from the exchange** (CON-03, CON-05)
   **Given** fetch_trading_fee failing
   **When** get_fee_rates runs
   **Then** it fails closed; market metadata fee fields are never read
5. **Requires the live gate** (AD-15)
   **Given** no LiveGate token
   **When** KrakenBroker is constructed
   **Then** it raises

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m6-live/epic-m6-live.md, Requirements R1, R2, R3
- prd — docs/planning/prd.md, CON-03, CON-05, FR-23, FR-26, FR-27
- architecture — docs/planning/architecture.md, §1 KrakenBroker
- architecture — docs/planning/architecture.md, AD-8
- architecture — docs/planning/architecture.md, AD-13
- architecture — docs/planning/architecture.md, AD-15
- architecture — docs/planning/architecture.md, AD-27

## Notes

- High risk: real orders. Extra check: GL-05 reading (story 3) covers this file line by line.
- No test may reach Kraken (SAF-11); the real crossing response is recorded in story 6.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
