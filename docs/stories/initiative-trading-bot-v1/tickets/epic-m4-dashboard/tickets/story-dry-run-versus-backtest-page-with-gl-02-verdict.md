---
id: 7
type: story
title: "Dry-run versus backtest page with GL-02 verdict"
parent: epic-m4-dashboard
covers: ["R12", "R2", "R3"]
after: [6]
refined: false
hitl: false
risk: medium
protected: false
---

# Dry-run versus backtest page with GL-02 verdict

## Description

View 5: two-line GL-02 verdict, per-trade diff table with MISSING rows failing, equity overlay with ±2 pp band, weekly reviews and DECAYING status.

## Requirements

Verify: Fixture with one 0.71% fill and one missing trade shows `Per fill: FAIL` with the worst value and failures first; zero fills show `Not evaluable`, never PASS.

1. **Verdict lines** (FR-54, GL-02)
   **Given** weekly_reviews and predictions
   **When** the page renders
   **Then** per-fill and equity verdicts show PASS/FAIL with n of N, worst value and fixed tolerances 0.5% and 2 pp
2. **Never PASS on empty** (UX State Patterns)
   **Given** no fills or no covering backtest
   **When** the page renders
   **Then** it shows Not evaluable or FAIL/n.a.
3. **DECAYING status** (FR-42)
   **Given** a decaying flag
   **When** any page renders
   **Then** the badge appears in the status strip

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m4-dashboard/epic-m4-dashboard.md, Requirements R12, R2, R3
- prd — docs/planning/prd.md, FR-41, FR-42, FR-54, GL-02
- architecture — docs/planning/architecture.md, AD-20
- design — docs/planning/ux-dashboard/EXPERIENCE.md GL-02 verdict block

## Notes

- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
