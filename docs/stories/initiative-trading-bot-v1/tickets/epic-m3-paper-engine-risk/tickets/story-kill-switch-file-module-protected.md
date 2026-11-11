---
id: 4
type: story
title: "Kill-switch file module (protected)"
parent: epic-m3-paper-engine-risk
covers: ["R10", "R19"]
after: ["epic-m2-backtest"]
refined: false
hitl: false
risk: high
protected: true
---

# Kill-switch file module (protected)

## Description

bot/risk/kill_switch.py: engage(path, source) writes `source=… at=…`, kill_switch_engaged(path) reads; tests/risk/ cover hand-made, CLI and dashboard-source files. PROTECTED: see Constraints.

## Requirements

Verify: tests/risk/test_kill_switch.py passes: engage creates the file with one line, an empty hand-made file counts as engaged with source=file, and the module offers no delete.

1. **Engage only** (FR-36, AD-12)
   **Given** the kill_switch module
   **When** it is inspected
   **Then** it exposes engage and kill_switch_engaged and no function that deletes the file
2. **Any file counts** (FR-36, GL-04)
   **Given** a file created by hand with no content at risk.kill_switch_path
   **When** kill_switch_engaged runs
   **Then** it returns engaged with source=file
3. **Dedicated commit** (SAF-04)
   **Given** the change
   **When** committed
   **Then** only bot/risk/kill_switch.py and tests/risk/ are touched, on the operator's explicit request

## Constraints

- PROTECTED (SAF-04): touches bot/risk/kill_switch.py, tests/risk/. Start only when the operator has asked for it explicitly in the chat; land it in a dedicated commit that touches nothing else.

## Boundaries

- Must not change: any file outside the protected paths in this story's commit.
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m3-paper-engine-risk/epic-m3-paper-engine-risk.md, Requirements R10, R19
- prd — docs/planning/prd.md, FR-36, FR-62, GL-04, SAF-04
- architecture — docs/planning/architecture.md, AD-12
- architecture — docs/planning/architecture.md, AD-17

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
