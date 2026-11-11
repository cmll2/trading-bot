---
id: 1
type: story
title: "Dashboard shell on 127.0.0.1 with mode banner and status strip"
parent: epic-m4-dashboard
covers: ["R7", "R16", "R17"]
after: ["epic-m3-paper-engine-risk"]
refined: false
hitl: false
risk: medium
protected: false
---

# Dashboard shell on 127.0.0.1 with mode banner and status strip

## Description

Tracer: `bot dashboard` starts Streamlit bound to 127.0.0.1, opens the store with mode=ro, shows the mode banner from the latest run, the status strip and a minimal Overview (equity, cash, last heartbeat).

## Requirements

Verify: Test asserts .streamlit/config.toml and the CLI flags set server.address=127.0.0.1, headless and no usage stats; the builder opens it against the M3 store and sees the DRY-RUN banner.

1. **Bound to localhost** (SAF-15, AD-23)
   **Given** `bot dashboard`
   **When** it starts
   **Then** both config.toml and CLI flags set server.address=127.0.0.1, server.headless=true, gatherUsageStats=false, and the sidebar shows 127.0.0.1:<port>
2. **Read-only store** (FR-49, AD-17)
   **Given** a missing database file
   **When** the dashboard opens
   **Then** it shows MODE UNKNOWN and an empty state and never creates the file; an existing store is opened with mode=ro
3. **Mode from the store** (NFR-09, UX Mode banner)
   **Given** the latest run's mode
   **When** any page renders
   **Then** banner, tab title and SIMULATED tag follow the UX spec; the mode never defaults to dry-run

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R7, R16, R17
- prd — docs/planning/prd.md, FR-49, NFR-06, NFR-09, SAF-15
- architecture — docs/planning/architecture.md, AD-17
- architecture — docs/planning/architecture.md, AD-23
- design — docs/planning/ux-dashboard/EXPERIENCE.md, DESIGN.md

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
