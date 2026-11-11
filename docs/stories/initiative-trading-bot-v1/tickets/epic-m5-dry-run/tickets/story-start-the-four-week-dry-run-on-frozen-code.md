---
id: 1
type: story
title: "Start the four-week dry-run on frozen code"
parent: epic-m5-dry-run
covers: ["R1", "R2"]
after: ["epic-m4-dashboard"]
refined: false
hitl: true
risk: medium
protected: false
---

# Start the four-week dry-run on frozen code

## Description

The operator starts v0 and plumbing dry-runs under Task Scheduler on a tagged commit, with config and limits hashes, review backtest ref and start date recorded.

## Requirements

Verify: PROGRESS.md records the start UTC, commit, config_hash, limits_hash, review.backtest_run_ref and the incident rule; `bot status` shows both engines running.

1. **Frozen and recorded** (GL-01, AD-21)
   **Given** a clean tree at the M4-accepted commit
   **When** the dry-runs start
   **Then** runs rows show git_dirty=0 and the commit, config hash and limits hash are written to PROGRESS.md
2. **Incident rule fixed in advance** (GL-01, WR-03)
   **Given** an unhandled error, mismatch or fix
   **When** it happens
   **Then** the operator logs it, a bug ticket is opened in docs/stories/backlog/, and the 28-day count restarts from the fixed code
3. **Supervision on** (AD-29)
   **Given** the PC
   **When** it reboots or the process dies
   **Then** Task Scheduler restarts the engine and the restart is recorded

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m5-dry-run/epic-m5-dry-run.md, Requirements R1, R2
- prd — docs/planning/prd.md, GL-01, NFR-04, WR-03
- architecture — docs/planning/architecture.md, AD-21
- architecture — docs/planning/architecture.md, AD-29
- decisions — PROGRESS.md, dry-run host, GL-02 tolerance

## Notes

- hitl: operator starts the runs and keeps the PC on.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
