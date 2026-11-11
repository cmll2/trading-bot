---
id: 2
type: story
title: "Crash-safe restart mid-order with no duplicates"
parent: epic-m3-paper-engine-risk
covers: ["R6", "R7", "R13", "R16"]
after: [1]
refined: false
hitl: false
risk: high
protected: false
---

# Crash-safe restart mid-order with no duplicates

## Description

Startup sequence of AD-8: created→not_found, submitting→unknown, find_order resolution with grace, idempotent fill ingestion, pending signal resume, intent continuation; persist-before-act everywhere.

## Requirements

Verify: FakeBroker/FakeClock tests restart in every open-like order state, after a timeout-after-accept, with created and pending rows, and assert no duplicate placement and Σfills = filled_qty.

1. **Persist before acting** (FR-39, AD-7)
   **Given** any order submission
   **When** the process dies at any line
   **Then** the store holds the order row committed before the broker call
2. **Unknown is never resent** (FR-26, AD-8)
   **Given** a place_order timeout after acceptance
   **When** the engine recovers
   **Then** find_order checks open AND closed orders every 10 s up to 60 s; only not_found frees the intent for a new cl_ord_id; no duplicate exists
3. **Fills counted once** (FR-27, AD-27)
   **Given** partial fills re-polled after restart
   **When** they are ingested
   **Then** fills(exchange, trade id) is unique and orders/intents filled_qty equal Σ fills
   **And** the next attempt waits until ingested fills equal the exchange's filled_qty, else halt reconcile_mismatch after 60 s
4. **Rate limits and transient reads** (FR-27, AD-8)
   **Given** RateLimited or TransientReadError
   **When** raised
   **Then** the engine sleeps retry_after_s or retries ≤ 3 times, records api_calls, and changes no state
5. **Illegal transition halts** (AD-8)
   **Given** a transition not in the state machine
   **When** attempted
   **Then** IllegalTransition halts with rule fatal_error

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R6, R7, R13, R16
- prd — docs/planning/prd.md, FR-26, FR-27, FR-39, FR-59
- architecture — docs/planning/architecture.md, AD-7
- architecture — docs/planning/architecture.md, AD-8
- architecture — docs/planning/architecture.md, AD-27
- architecture — docs/planning/architecture.md, AD-28

## Notes

- High risk: a duplicate order is real money in M6. Extra check: auditor kills the process at random points in a FakeBroker loop (100 iterations).
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
