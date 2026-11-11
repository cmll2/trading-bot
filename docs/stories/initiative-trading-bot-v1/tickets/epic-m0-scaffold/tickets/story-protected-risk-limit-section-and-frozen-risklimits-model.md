---
id: 4
type: story
title: "Protected risk-limit section and frozen RiskLimits model"
parent: epic-m0-scaffold
covers: ["R6"]
after: [3]
refined: false
hitl: false
risk: high
protected: true
---

# Protected risk-limit section and frozen RiskLimits model

## Description

The `risk:` section of config.yaml and bot/risk/limits.py with tests/risk/test_risk_limits.py: limits load read-only into a frozen model and are hashed. PROTECTED: see Constraints.

## Requirements

Verify: tests/risk/test_risk_limits.py passes: values equal the PROGRESS.md limits, the model is frozen, the file is opened read-only and the limits hash is stable.

1. **Limits equal the adopted values** (SAF-04, FR-30, AD-11)
   **Given** config.yaml `risk:`
   **When** RiskLimits is loaded
   **Then** max position 100% of equity and €25; 20 new order intents/day; 120 exchange submissions/day; max 12 submissions per intent (raised by operator 2026-11-11, commit b415992); daily loss 10%; total drawdown 25% from start; stale candle 2 intervals; stale ticker 120 s; price sanity 2%; absolute kill-switch path
   **And** a missing or extra key fails loading
2. **No write path** (SAF-05, AD-10)
   **Given** the loaded RiskLimits
   **When** code tries to assign a field or reload
   **Then** assignment raises, the config file is opened read-only once, and the limits hash goes to the run record
3. **Dedicated commit** (SAF-04)
   **Given** the change set
   **When** it is committed
   **Then** the commit touches only config.yaml (risk section), bot/risk/ and tests/risk/, after the operator asked for it explicitly in the chat

## Constraints

- PROTECTED (SAF-04): touches config.yaml `risk:` section, bot/risk/limits.py, tests/risk/. Start only when the operator has asked for it explicitly in the chat; land it in a dedicated commit that touches nothing else.

## Boundaries

- Must not change: any file outside the protected paths in this story's commit.
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m0-scaffold/epic-m0-scaffold.md, Requirements R6
- prd — docs/planning/prd.md, FR-30, NFR-03, SAF-04, SAF-05
- architecture — docs/planning/architecture.md, AD-10
- architecture — docs/planning/architecture.md, AD-11
- decisions — PROGRESS.md, Decisions log 2026-11-11 (risk limits, orders/day interpretation, execution window)

## Notes

- High risk: a wrong limit value goes live. Extra check: the operator compares the YAML against PROGRESS.md line by line.
- Source conflict: architecture AD-11/Q-8 says max_reprices 8, window 4 h, re-price 15 min; PROGRESS.md (authoritative) says 6 h, 30 min, 12 submissions per intent and 24/day. PROGRESS wins.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
