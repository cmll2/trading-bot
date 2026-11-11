---
id: 6
type: story
title: "Architecture guards: import graph, clock ban, no config writes"
parent: epic-m0-scaffold
covers: ["R5", "R6"]
after: [1]
refined: false
hitl: false
risk: medium
protected: false
---

# Architecture guards: import graph, clock ban, no config writes

## Description

tests/test_architecture.py and ruff banned-api enforce the dependency rule, the clock rule and the no-write-to-config rule.

## Requirements

Verify: The suite passes on the skeleton, and three scratch violations (strategy importing ccxt, `datetime.now()` outside clock.py, `open(config_path, 'w')`) each make the check command fail.

1. **Dependency rule** (NFR-01, AD-3)
   **Given** a module under bot/strategy or bot/risk
   **When** it imports broker, engine, store, data or a network library
   **Then** the AST import-graph test fails naming the import
   **And** dashboard/ may import only store read helpers, config, ledger and risk.kill_switch
2. **Clock rule** (NFR-03, AD-2)
   **Given** any module other than bot/clock.py
   **When** it calls datetime.now, utcnow, date.today, time.time, time.sleep or pd.Timestamp.now
   **Then** ruff TID251 fails the check command
3. **No config write path** (SAF-05, AD-10)
   **Given** any module
   **When** it opens the config path for write/append or dumps yaml to it
   **Then** the AST test fails

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m0-scaffold/epic-m0-scaffold.md, Requirements R5, R6
- prd — docs/planning/prd.md, NFR-01, NFR-03, SAF-05
- architecture — docs/planning/architecture.md, AD-2
- architecture — docs/planning/architecture.md, AD-3
- architecture — docs/planning/architecture.md, AD-10
- architecture — docs/planning/architecture.md, Design paradigm, Dependency rule

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
