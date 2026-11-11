---
id: 8
type: story
title: "Health page"
parent: epic-m4-dashboard
covers: ["R13"]
after: [1]
refined: false
hitl: false
risk: low
protected: false
---

# Health page

## Description

Recent errors, API latency, rate-limit events, data freshness against the stale thresholds, uptime.

## Requirements

Verify: Fixture store: a ticker older than 120 s shows stale; errors list shows redacted messages; uptime from runs.

1. **Health facts** (FR-55, NFR-05)
   **Given** api_calls, errors, heartbeats, runs
   **When** the page renders
   **Then** latency, rate-limit counts, freshness vs 2 intervals and 120 s, recent errors and uptime are shown

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R13
- prd — docs/planning/prd.md, FR-55, NFR-05
- design — docs/planning/ux-dashboard/EXPERIENCE.md Health

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
