---
type: epic
title: "M6 Live with €20: the bot trades real money only after every go-live criterion is met"
parent: initiative-trading-bot-v1
covers: ["R23", "R26", "R27", "R28", "R45", "R63", "R65", "R66", "R73", "R77", "R78", "R81", "R82"]
sources: []
companions: [docs/planning/architecture.md]
after: ["epic-m5-dry-run"]
refined: true
risk: high
---

# M6 Live with €20: the bot trades real money only after every go-live criterion is met

## Description

Brief §9 M6 and §10. Builds the live-only adapter and gate (KrakenBroker, key-permission check, double gate, banner), then runs the operator's go-live checklist, including the IP-restriction reminder and the operator's own reading of the broker, risk and engine code, before a manually approved first live run.

## Outcome

The operator decides go-live on fixed criteria and, if yes, the bot runs live on €20 with manual approval (brief §10).

## Requirements

Each line is the parent's line in the PRD's words (refined from the initiative's lines alone; operator unavailable). Stories cite these R ids in `covers` and PRD/AD ids in each criterion.

- R1 (parent R23, FR-23): A single broker abstraction offers: get balance, get ticker, place order, cancel order, get open orders, get fills. It does not preclude a second exchange later. — this epic delivers: Kraken adapter.
- R2 (parent R26, FR-26): The live broker uses client order IDs so that a retried request can never create a duplicate order. — this epic delivers: client order ids on Kraken.
- R3 (parent R27, FR-27): The live broker handles partial fills, rejections, timeouts and rate limits without losing or duplicating state. — this epic delivers: Kraken error mapping.
- R4 (parent R28, FR-28): At startup the system verifies the API key's permissions where the API allows it and refuses to start if withdrawals are enabled (SAF-07; fallback: OD-12).
- R5 (parent R45, FR-45): In `live` mode, startup requires both the CLI flag and the environment variable and shows the confirmation banner with account balance and active limits (SAF-09).
- R6 (parent R63, FR-63): A test proves the plumbing strategy cannot start in `live` mode (FR-10). — this epic delivers: live-gate refusal.
- R7 (parent R81, GL-05): I have read the code of the broker, risk and engine modules myself.
- R8 (parent R82, GL-06): Go-live does not depend on the dry-run being profitable. If the strategy shows no edge after costs, that is a valid result and the decision to put €20 on it is mine.
- R9 (parent R77, GL-01): Four weeks of dry-run with no unhandled errors and no state mismatch on reconciliation. — this epic delivers: checked at go-live.
- R10 (parent R78, GL-02): Dry-run fills within a stated tolerance of backtest predictions over the same period. (Tolerance value: OD-08.) — this epic delivers: checked at go-live.
- R11 (parent R73, NFR-07): Secret hygiene: no secret appears in logs, error messages, tracebacks, the store, the dashboard or the repository (SAF-01, SAF-02). — this epic delivers: live secrets path.
- R12 (parent R65, FR-65): At the end of each milestone, a reviewer that did not write the code (a fresh session, a separate subagent, or BMAD's review step) runs the tests itself, reads the git history for deleted, skipped or weakened tests and for extra holdout runs, looks for look-ahead bias, missing costs and overfitting, and rates each result PASS, FAIL or INCONCLUSIVE. — this epic delivers: M6 audit.
- R13 (parent R66, FR-66): The operator sees the audit report (FR-65) before reviewing the milestone. — this epic delivers: M6 audit.

## Constraints

- Binding from the initiative: CON-01..CON-11, SAF-01..SAF-15, WR-01..WR-08 and architecture AD-1..AD-30.
- SAF-04: any story touching config.yaml `risk:`, bot/risk/ or tests/risk/ is marked PROTECTED and lands in a dedicated commit touching nothing else, only on the operator's explicit request.
- Brief §9: stop at the end of the milestone, summarize, list known limitations, and wait for the operator's review after the audit story.

## Done when

- KrakenBroker and the live gate pass offline tests with an injected fake ccxt; every gate refusal is tested
- Go-live checklist signed in PROGRESS.md: GL-01 to GL-05 evidence, SAF-03 IP restriction answered, key permissions printed
- The operator has read bot/broker/, bot/risk/ and bot/engine.py and recorded it (GL-05)
- If the operator says go: first live run started with banner, manual approval and €20 allocation; else the no-go reason recorded (GL-06)
- Independent M6 audit report seen by the operator

## Boundaries

- Out: changes to engine.py, risk/ or strategy code after the M5 freeze, except bug fixes that restart M5's clock.
- Out: autonomous approval in the first live weeks (PROGRESS). Out: more pairs or capital (later).

## References

- parent — docs/stories/initiative-trading-bot-v1/initiative-trading-bot-v1.md, Requirements
- prd — docs/planning/prd.md, Milestones and acceptance criteria (M6)
- brief — first_brief.txt, §9 M6
- architecture — docs/planning/architecture.md, Capability to architecture map
- decisions — PROGRESS.md, Decisions log

## Notes

- Decision: 2026-11-11 — KrakenBroker is built at M6, not M3: it is live-only, and as an adapter it does not change the engine that ran M5 (brief places no milestone on it). Flag at M6 kickoff.
- Decision: 2026-11-11 — Refactor sweep declined: a cleanup after the operator's code reading would invalidate GL-05.
- Decision: 2026-11-11 — Tracer bullet: story 1 (KrakenBroker against fake ccxt).
- Decision: 2026-11-11 (PROGRESS) — Manual approval per order for the first live weeks; key permissions via GetApiKeyInfo, fail closed.
- Open question: architecture Q-5 (typed confirmation on the live banner), Q-9 (BTC held outside the bot), Q-10 (query-only key in dry-run) — answer at story 4.
- Waits on epic-m5-dry-run because: brief §9 — one milestone at a time; the previous milestone must be accepted after its audit.
