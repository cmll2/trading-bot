---
id: 6
type: story
title: "Record Kraken's real post-only crossing response"
parent: epic-m6-live
covers: ["R3"]
after: [5]
refined: false
hitl: true
risk: medium
protected: false
---

# Record Kraken's real post-only crossing response

## Description

With the operator present, one minimum-size post-only order priced to cross is placed to record Kraken's actual response, saved as a test fixture, and the adapter mapping is confirmed.

## Requirements

Verify: tests/fixtures/kraken_post_only_cross.json exists (scrubbed of ids/keys) and the KrakenBroker test using it maps to PostOnlyWouldCross.

1. **Real response captured** (WR-04, AD §1)
   **Given** the operator's explicit go-ahead in chat
   **When** one minimum-size crossing post-only order is sent
   **Then** the response is saved scrubbed and the mapping test passes against it
   **And** a difference from the assumed behaviour is reported to the operator with a proposed change
2. **Nothing secret saved** (SAF-02, NFR-07)
   **Given** the fixture
   **When** committed
   **Then** it contains no key, signature or account identifier

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m6-live/epic-m6-live.md, Requirements R3
- prd — docs/planning/prd.md, FR-27, NFR-07, SAF-02, WR-04
- architecture — docs/planning/architecture.md, §1 KrakenBroker (post-only crossing)

## Notes

- hitl: a real order; the operator places or explicitly authorises it.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
