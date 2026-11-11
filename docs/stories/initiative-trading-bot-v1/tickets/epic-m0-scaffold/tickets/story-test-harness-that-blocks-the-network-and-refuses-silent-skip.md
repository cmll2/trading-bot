---
id: 2
type: story
title: "Test harness that blocks the network and refuses silent skips"
parent: epic-m0-scaffold
covers: ["R2"]
after: [1]
refined: false
hitl: false
risk: medium
protected: false
---

# Test harness that blocks the network and refuses silent skips

## Description

tests/conftest.py makes every network call raise and a meta-test fails on any skip or xfail without a referenced operator decision.

## Requirements

Verify: `pytest` passes; a scratch test that opens a socket fails with NetworkBlocked, and a scratch `@pytest.mark.skip` without a decision reference fails the suite.

1. **Network blocked in every test** (SAF-10, SAF-11)
   **Given** the autouse fixture
   **When** a test calls socket.connect, socket.create_connection or getaddrinfo
   **Then** the call raises NetworkBlocked and a self-test proves it for all three
2. **No silent skips** (FR-64)
   **Given** a test marked skip or xfail
   **When** the suite runs
   **Then** the suite fails unless the marker's reason cites an operator decision id recorded in PROGRESS.md

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m0-scaffold/epic-m0-scaffold.md, Requirements R2
- prd — docs/planning/prd.md, FR-64, SAF-10, SAF-11
- architecture — docs/planning/architecture.md, AD-24

## Notes

- Risk medium: a hole here lets later tests reach Kraken.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
