---
type: epic
title: "M4 Dashboard: seven read-only views work against the dry-run database"
parent: initiative-trading-bot-v1
covers: ["R40", "R41", "R42", "R46", "R47", "R48", "R49", "R50", "R51", "R52", "R53", "R54", "R55", "R56", "R62", "R65", "R66", "R72", "R75"]
sources: []
companions: [docs/planning/architecture.md, docs/planning/ux-dashboard/EXPERIENCE.md, docs/planning/ux-dashboard/DESIGN.md]
after: ["epic-m3-paper-engine-risk"]
refined: true
risk: high
---

# M4 Dashboard: seven read-only views work against the dry-run database

## Description

Brief §7 and §9 M4, specified by docs/planning/ux-dashboard/{EXPERIENCE,DESIGN}.md. A Streamlit app bound to 127.0.0.1 reads the store read-only; its only write is engaging the kill switch. Includes `bot review` (weekly comparison, counterfactuals, DECAYING) and `bot ledger export`, which the views display.

## Outcome

The operator can open 127.0.0.1 and use all seven views against the dry-run database (brief §9 M4).

## Requirements

Each line is the parent's line in the PRD's words (refined from the initiative's lines alone; operator unavailable). Stories cite these R ids in `covers` and PRD/AD ids in each criterion.

- R1 (parent R40, FR-40): Every signal is journaled with its outcome (filled, not filled, rejected by risk, skipped by the operator); for signals not traded, the journal records what the trade would have returned. — this epic delivers: counterfactual returns for untraded signals.
- R2 (parent R41, FR-41): A weekly review compares realized results with what the backtest expected for the same period and is shown in the dashboard.
- R3 (parent R42, FR-42): Once there are 20 or more trades, if the average result per trade is below half the backtest's, the strategy is flagged DECAYING (edge case: OD-15).
- R4 (parent R46, FR-46): Every fill is recorded in the ledger with timestamp, amount, price, fee and quote currency, and the ledger exports to CSV (CON-09).
- R5 (parent R47, FR-47): Fills that convert crypto to euros are marked, and the running total of crypto-to-euro sales for the calendar year is computed (CON-10).
- R6 (parent R48, FR-48): The ledger and all FRs work for both EUR-quoted and stablecoin-quoted pairs (CON-11).
- R7 (parent R49, FR-49): A local web dashboard reads the persisted store, auto-refreshes, binds to `127.0.0.1` only (SAF-15), and can take exactly one action: toggling the kill switch.
- R8 (parent R50, FR-50): **Overview:** current mode shown prominently (DRY-RUN or LIVE), engine status and last heartbeat, equity, cash, open position, return since start, total fees paid, and an equity curve against buy-and-hold and cash.
- R9 (parent R51, FR-51): **Signals and trades:** price chart with the strategy's indicator, entry and exit markers, and the current target position.
- R10 (parent R52, FR-52): **Orders and fills:** table of orders with status; fills with price, fee and slippage versus the signal price; filterable by date.
- R11 (parent R53, FR-53): **Risk:** each limit with its current usage, history of rejections and halts with reasons, kill switch state and button.
- R12 (parent R54, FR-54): **Dry-run vs backtest:** for the same period, backtester-predicted equity versus paper-broker-recorded equity, with the difference per trade.
- R13 (parent R55, FR-55): **Health:** recent errors, API latency, rate-limit events, data freshness, uptime.
- R14 (parent R56, FR-56): **Ledger:** fills ledger with CSV export, including the calendar-year running total of crypto-to-euro sales.
- R15 (parent R62, FR-62): Kill-switch tests cover both the file and the dashboard trigger (GL-04). — this epic delivers: dashboard trigger.
- R16 (parent R72, NFR-06): Locality: everything runs on the operator's computer; no cloud services; no network listener beyond `127.0.0.1`. — this epic delivers: 127.0.0.1 only.
- R17 (parent R75, NFR-09): Simulation labeling: every output derived from simulation (backtest, dry-run, paper fills) is labeled as simulated. — this epic delivers: SIMULATED tags and CSV naming.
- R18 (parent R65, FR-65): At the end of each milestone, a reviewer that did not write the code (a fresh session, a separate subagent, or BMAD's review step) runs the tests itself, reads the git history for deleted, skipped or weakened tests and for extra holdout runs, looks for look-ahead bias, missing costs and overfitting, and rates each result PASS, FAIL or INCONCLUSIVE. — this epic delivers: M4 audit.
- R19 (parent R66, FR-66): The operator sees the audit report (FR-65) before reviewing the milestone. — this epic delivers: M4 audit.

## Constraints

- Binding from the initiative: CON-01..CON-11, SAF-01..SAF-15, WR-01..WR-08 and architecture AD-1..AD-30.
- SAF-04: any story touching config.yaml `risk:`, bot/risk/ or tests/risk/ is marked PROTECTED and lands in a dedicated commit touching nothing else, only on the operator's explicit request.
- Brief §9: stop at the end of the milestone, summarize, list known limitations, and wait for the operator's review after the audit story.

## Done when

- All seven views render real data from the M3 dry-run store, each tagged SIMULATED, verified by the operator
- A test asserts the server binds 127.0.0.1 only via config.toml and CLI flags
- Dashboard kill-switch engage works end to end and there is no disengage control
- `bot review` and `bot ledger export --year Y` produce the GL-02 metrics and the Europe/Paris-year CSV
- Independent M4 audit report seen by the operator

## Boundaries

- Out: any write to the store, config or limits from the dashboard; approve/reject buttons; halt reset button.
- Out: notifications (brief §12).

## References

- parent — docs/stories/initiative-trading-bot-v1/initiative-trading-bot-v1.md, Requirements
- prd — docs/planning/prd.md, Milestones and acceptance criteria (M4)
- brief — first_brief.txt, §9 M4
- architecture — docs/planning/architecture.md, Capability to architecture map
- decisions — PROGRESS.md, Decisions log
- design — docs/planning/ux-dashboard/EXPERIENCE.md
- design — docs/planning/ux-dashboard/DESIGN.md

## Notes

- Decision: 2026-11-11 — Tracer bullet: story 1 (app shell on 127.0.0.1 with mode banner, status strip and a minimal Overview from the read-only store). Next: Risk page and kill switch (least certain: write path from a read-only app).
- Decision: 2026-11-11 — 14 entries exceed the typical 8–12; split declined because epics map one-to-one onto milestones (operator instruction).
- Decision: 2026-11-11 (PROGRESS) — Dashboard engages the kill switch only; disengage and halt reset are CLI-only. Flag the narrowing of brief 'toggle' to the operator at the M4 review (OQ-UX-01).
- Source conflict: UX AS-UX-04 (disposal year in UTC) vs PROGRESS 2026-11-11 (tax year in Europe/Paris). PROGRESS wins; the year selector uses Europe/Paris.
- Decision: 2026-11-11 (architecture Q-11 default) — Disposal total is gross proceeds; fees shown separately. Open question for operator confirmation at M4.
- Waits on epic-m3-paper-engine-risk because: brief §9 — one milestone at a time; the previous milestone must be accepted after its audit.
