---
id: 8
type: story
title: "Complete journal outcomes, snapshots, health records and backups"
parent: epic-m3-paper-engine-risk
covers: ["R12", "R13", "R14", "R22"]
after: [2]
refined: false
hitl: false
risk: medium
protected: false
---

# Complete journal outcomes, snapshots, health records and backups

## Description

Every signal ends with one AD-28 outcome; each tick writes equity and risk snapshots and day-open equity; api_calls, errors (redacted) and heartbeats feed health; a daily store backup keeps 30 copies.

## Requirements

Verify: Engine tests produce each outcome value at least once; a tick writes equity_snapshots, risk_snapshots and one day-open row per UTC day; errors rows pass redaction; backup file appears in var/backups/.

1. **One outcome per signal** (FR-40, AD-28)
   **Given** the AD-28 transitions
   **When** each is driven
   **Then** the signal outcome is the one in the AD-28 table, written in the same transaction as the final intent state
2. **Snapshots each tick** (FR-38, AD-11)
   **Given** a tick
   **When** it runs
   **Then** equity (marked at mid), risk context and usage are stored; the first tick on or after 00:00 UTC writes day-open equity before any risk check
3. **Health data** (NFR-05, NFR-07)
   **Given** API calls and errors
   **When** they occur
   **Then** api_calls stores latency, ok and rate_limited; errors stores redacted messages; retention 30 days
4. **Daily backup** (§2 Backups)
   **Given** a new UTC day
   **When** the engine runs
   **Then** sqlite backup writes to var/backups/ keeping 30 copies

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R12, R13, R14, R22
- prd — docs/planning/prd.md, FR-38, FR-39, FR-40, NFR-05, NFR-07
- architecture — docs/planning/architecture.md, AD-11
- architecture — docs/planning/architecture.md, AD-22
- architecture — docs/planning/architecture.md, AD-28
- architecture — docs/planning/architecture.md, §2 Backups

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
