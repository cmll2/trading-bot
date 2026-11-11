---
id: 1
type: story
title: "Broker port, domain types, error taxonomy and FakeBroker"
parent: epic-m2-backtest
covers: ["R17"]
after: ["epic-m1-data"]
refined: false
hitl: false
risk: medium
protected: false
---

# Broker port, domain types, error taxonomy and FakeBroker

## Description

bot/broker/base.py and errors.py define the Broker protocol, frozen Decimal/UTC domain types and the six-error taxonomy; tests/fakes provide a scriptable FakeBroker.

## Requirements

Verify: Unit tests: FakeBroker satisfies the protocol, scripts partial fill, timeout-after-accept, reject, rate limit and exchange-side cancel, and place_order raises without an approved matching RiskDecision.

1. **Port shape** (FR-23, AD §1)
   **Given** the Broker protocol
   **When** it is inspected
   **Then** it offers load_market, get_fee_rates, get_balance, get_ticker, place_order, cancel_order, get_open_orders, find_order (open and closed), get_fills, check_key_permissions, and nothing exchange-specific
2. **Risk decision enforced at the adapter** (FR-30, AD-10)
   **Given** an OrderRequest
   **When** place_order is called with a missing, rejected or mismatched-cl_ord_id decision
   **Then** the adapter raises and nothing is placed
3. **Error taxonomy only** (AD §1, Conventions: Errors)
   **Given** FakeBroker scripted failures
   **When** they are raised
   **Then** only OrderRejected, PostOnlyWouldCross, OrderOutcomeUnknown, RateLimited, TransientReadError, FatalBrokerError appear

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m2-backtest/epic-m2-backtest.md, Requirements R17
- prd — docs/planning/prd.md, FR-23, FR-30
- architecture — docs/planning/architecture.md, §1 Broker port
- architecture — docs/planning/architecture.md, AD-10

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
