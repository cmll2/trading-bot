---
type: epic
title: "M5 Dry-run period: four weeks of reviewed dry-run produce the go-live evidence"
parent: initiative-trading-bot-v1
covers: ["R41", "R42", "R65", "R66", "R70", "R77", "R78", "R79", "R80"]
sources: []
companions: [docs/planning/architecture.md]
after: ["epic-m4-dashboard"]
refined: true
risk: high
---

# M5 Dry-run period: four weeks of reviewed dry-run produce the go-live evidence

## Description

Brief §9 M5: at least four weeks of dry-run on this PC, reviewed weekly with `bot review` and the dashboard, producing GL-01 to GL-04 evidence. Operational: no new features; a fix is a bug ticket and restarts the clock.

## Outcome

The operator holds four weekly reviews and a closing report that state GL-01 and GL-02 PASS or FAIL with evidence (brief §9 M5, §10).

## Requirements

Each line is the parent's line in the PRD's words (refined from the initiative's lines alone; operator unavailable). Stories cite these R ids in `covers` and PRD/AD ids in each criterion.

- R1 (parent R70, NFR-04): Reliability: dry-run runs 48 hours without intervention and survives a forced restart (M3); four weeks without unhandled errors or reconciliation mismatch (GL-01). — this epic delivers: four weeks.
- R2 (parent R77, GL-01): Four weeks of dry-run with no unhandled errors and no state mismatch on reconciliation.
- R3 (parent R78, GL-02): Dry-run fills within a stated tolerance of backtest predictions over the same period. (Tolerance value: OD-08.)
- R4 (parent R79, GL-03): Every risk limit triggered at least once in tests and seen working. — this epic delivers: evidence.
- R5 (parent R80, GL-04): Kill switch tested from both the file and the dashboard. — this epic delivers: evidence.
- R6 (parent R41, FR-41): A weekly review compares realized results with what the backtest expected for the same period and is shown in the dashboard. — this epic delivers: weekly operation.
- R7 (parent R42, FR-42): Once there are 20 or more trades, if the average result per trade is below half the backtest's, the strategy is flagged DECAYING (edge case: OD-15). — this epic delivers: monitoring.
- R8 (parent R65, FR-65): At the end of each milestone, a reviewer that did not write the code (a fresh session, a separate subagent, or BMAD's review step) runs the tests itself, reads the git history for deleted, skipped or weakened tests and for extra holdout runs, looks for look-ahead bias, missing costs and overfitting, and rates each result PASS, FAIL or INCONCLUSIVE. — this epic delivers: M5 audit.
- R9 (parent R66, FR-66): The operator sees the audit report (FR-65) before reviewing the milestone. — this epic delivers: M5 audit.

## Constraints

- Binding from the initiative: CON-01..CON-11, SAF-01..SAF-15, WR-01..WR-08 and architecture AD-1..AD-30.
- SAF-04: any story touching config.yaml `risk:`, bot/risk/ or tests/risk/ is marked PROTECTED and lands in a dedicated commit touching nothing else, only on the operator's explicit request.
- Brief §9: stop at the end of the milestone, summarize, list known limitations, and wait for the operator's review after the audit story.

## Done when

- 28 consecutive days of v0 dry-run on frozen code with zero unhandled errors and zero reconciliation mismatches (GL-01)
- GL-02 verdict over the period: each paper fill within 0.5% of backtest price and 4-week equity within 2 pp
- Evidence matrix shows every risk limit triggered in tests and seen working, and the kill switch from file and dashboard (GL-03, GL-04)
- Four weekly review notes and a closing report in docs/reviews/
- Independent M5 audit report seen by the operator

## Boundaries

- Out: code changes other than bug fixes, each of which restarts the four-week clock.
- Out: live trading and API keys (M6).

## References

- parent — docs/stories/initiative-trading-bot-v1/initiative-trading-bot-v1.md, Requirements
- prd — docs/planning/prd.md, Milestones and acceptance criteria (M5)
- brief — first_brief.txt, §9 M5
- architecture — docs/planning/architecture.md, Capability to architecture map
- decisions — PROGRESS.md, Decisions log

## Notes

- Decision: 2026-11-11 — Refactor sweep declined: operational epic, code is frozen.
- Decision: 2026-11-11 — Tracer bullet: story 1 (frozen-code dry-run start).
- Decision: 2026-11-11 (PROGRESS) — GL-02 tolerance: 0.5% per fill, 2 pp equity over 4 weeks; dry-run host is this Windows PC.
- Assumption: any unhandled error or reconciliation mismatch, and any code fix, restarts the 28-day GL-01 count (brief: 'four weeks with no unhandled errors'). Operator to confirm at story 1.
- Assumption: plumbing dry-run continues in parallel on its own store to exercise order handling; it is excluded from GL-02.
- Waits on epic-m4-dashboard because: brief §9 — one milestone at a time; the previous milestone must be accepted after its audit.
