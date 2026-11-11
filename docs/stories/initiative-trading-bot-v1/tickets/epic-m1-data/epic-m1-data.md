---
type: epic
title: "M1 Data: several years of validated BTC/EUR candles cached locally"
parent: initiative-trading-bot-v1
covers: ["R1", "R2", "R3", "R4", "R65", "R66", "R68"]
sources: []
companions: [docs/planning/architecture.md]
after: ["epic-m0-scaffold"]
refined: true
risk: high
---

# M1 Data: several years of validated BTC/EUR candles cached locally

## Description

Brief §9 M1: downloader, cache, validation for the chosen pair BTC/EUR (PROGRESS pair decision). History comes from Kraken's official OHLCVT archive plus ccxt for the recent gap (PROGRESS, research B6), with a no-trade-period policy, closed-candle access through the Clock port, and the fixed holdout window.

## Outcome

The operator can see several years of daily, 4h and 15m BTC/EUR candles cached as Parquet and passing validation (brief §9 M1).

## Requirements

Each line is the parent's line in the PRD's words (refined from the initiative's lines alone; operator unavailable). Stories cite these R ids in `covers` and PRD/AD ids in each criterion.

- R1 (parent R1, FR-01): The system downloads OHLCV candles for the configured pair and timeframe from Kraken (CON-01), handling pagination and rate limits. — this epic delivers: download with pagination and rate limits.
- R2 (parent R2, FR-02): Downloaded candles are cached locally and reused without re-downloading (brief specifies Parquet). — this epic delivers: Parquet cache.
- R3 (parent R3, FR-03): Candle data is validated for no gaps, no duplicates, monotonic timestamps and UTC timestamps; any violation is reported and the run fails. Bad data is never silently repaired. — this epic delivers: validation that fails loudly.
- R4 (parent R4, FR-04): Signals are computed only on closed candles. — this epic delivers: closed-candle-only history view.
- R5 (parent R68, NFR-02): Reproducibility: the same code version, configuration and data range produce the same backtest result. — this epic delivers: data hash recorded with every dataset.
- R6 (parent R65, FR-65): At the end of each milestone, a reviewer that did not write the code (a fresh session, a separate subagent, or BMAD's review step) runs the tests itself, reads the git history for deleted, skipped or weakened tests and for extra holdout runs, looks for look-ahead bias, missing costs and overfitting, and rates each result PASS, FAIL or INCONCLUSIVE. — this epic delivers: M1 audit.
- R7 (parent R66, FR-66): The operator sees the audit report (FR-65) before reviewing the milestone. — this epic delivers: M1 audit.

## Constraints

- Binding from the initiative: CON-01..CON-11, SAF-01..SAF-15, WR-01..WR-08 and architecture AD-1..AD-30.
- SAF-04: any story touching config.yaml `risk:`, bot/risk/ or tests/risk/ is marked PROTECTED and lands in a dedicated commit touching nothing else, only on the operator's explicit request.
- Brief §9: stop at the end of the milestone, summarize, list known limitations, and wait for the operator's review after the audit story.

## Done when

- `bot data validate` exits 0 for 1d, 4h and 15m BTC/EUR Parquet files covering several years
- Bad data (gap, duplicate, non-monotonic, non-UTC, inconsistent OHLC) makes the run fail loudly, proven by tests
- Strategies can read only closed candles through an immutable history view
- Data history depth, 2013–2016 gaps and synthetic-candle ratio reported in PROGRESS.md
- Independent M1 audit report seen by the operator

## Boundaries

- Out: strategy, backtest and execution (M2). Out: live ticker polling for trading (M3).
- Touch point: config.yaml `data:` and `backtest:` sections — values only; owner: epic-m0-scaffold.

## References

- parent — docs/stories/initiative-trading-bot-v1/initiative-trading-bot-v1.md, Requirements
- prd — docs/planning/prd.md, Milestones and acceptance criteria (M1)
- brief — first_brief.txt, §9 M1
- architecture — docs/planning/architecture.md, Capability to architecture map
- decisions — PROGRESS.md, Decisions log

## Notes

- Decision: 2026-11-11 — Tracer bullet: story 1 (`bot data update` → Parquet → `bot data validate` on recent 1d candles).
- Decision: 2026-11-11 — Tests never touch the network, public endpoints included (AD-24 answers PRD OD-17).
- Assumption: overlap tolerance archive vs API = 1 tick on OHLC and 1% on volume (architecture A-3).
- Assumption: 15m candles are cached in M1 because the fill model needs them (AD-6 sim_timeframe).
- Waits on epic-m0-scaffold because: brief §9 — one milestone at a time; the previous milestone must be accepted after its audit.
