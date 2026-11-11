---
type: epic
title: "M0 Scaffold: an empty, safe, pinned skeleton whose tests and lint pass"
parent: initiative-trading-bot-v1
covers: ["R43", "R64", "R65", "R66", "R67", "R69", "R73", "R76"]
sources: []
companions: [docs/planning/architecture.md]
after: []
refined: true
risk: high
---

# M0 Scaffold: an empty, safe, pinned skeleton whose tests and lint pass

## Description

Brief §9 M0: repo, lockfile, config, `.env.example`, `.gitignore` and a CI-style test command, plus the guard rails every later milestone relies on (network-blocked tests, no silent skips, secret redaction, import-graph and clock rules, the protected risk-limit section). M0 is being implemented concurrently by another agent; these stories describe the target and are the audit baseline.

## Outcome

The operator can run one command on an empty skeleton and see tests and lint pass (brief §9 M0 done-when).

## Requirements

Each line is the parent's line in the PRD's words (refined from the initiative's lines alone; operator unavailable). Stories cite these R ids in `covers` and PRD/AD ids in each criterion.

- R1 (parent R76, NFR-10): Dependency hygiene: dependencies pinned by lockfile; no dependency outside brief §6 without operator approval (SAF-12 to SAF-14). — this epic delivers: lockfile and dependency set.
- R2 (parent R64, FR-64): Never delete, skip or weaken a test to make the suite pass. If a test fails, fix the code or report the failure and stop. — this epic delivers: no-silent-skip guard.
- R3 (parent R43, FR-43): Structured logs are written to file with secrets redacted. — this epic delivers: logging setup with redaction; engine log lines come in M3.
- R4 (parent R73, NFR-07): Secret hygiene: no secret appears in logs, error messages, tracebacks, the store, the dashboard or the repository (SAF-01, SAF-02). — this epic delivers: redaction filter and secrets-path guard.
- R5 (parent R67, NFR-01): Auditability: modules are small and readable over clever abstractions; the operator must be able to read the broker, risk and engine code in full (GL-05). — this epic delivers: import-graph rule that keeps broker, risk and engine readable.
- R6 (parent R69, NFR-03): Time: all timestamps stored and compared in UTC. — this epic delivers: clock ban and UTC conventions.
- R7 (parent R65, FR-65): At the end of each milestone, a reviewer that did not write the code (a fresh session, a separate subagent, or BMAD's review step) runs the tests itself, reads the git history for deleted, skipped or weakened tests and for extra holdout runs, looks for look-ahead bias, missing costs and overfitting, and rates each result PASS, FAIL or INCONCLUSIVE. — this epic delivers: M0 audit.
- R8 (parent R66, FR-66): The operator sees the audit report (FR-65) before reviewing the milestone. — this epic delivers: M0 audit.

## Constraints

- Binding from the initiative: CON-01..CON-11, SAF-01..SAF-15, WR-01..WR-08 and architecture AD-1..AD-30.
- SAF-04: any story touching config.yaml `risk:`, bot/risk/ or tests/risk/ is marked PROTECTED and lands in a dedicated commit touching nothing else, only on the operator's explicit request.
- Brief §9: stop at the end of the milestone, summarize, list known limitations, and wait for the operator's review after the audit story.

## Done when

- `uv sync --locked` then the single check command (pytest, ruff check, ruff format --check) exits 0 on a clean clone
- The test suite cannot open a network connection and fails on any unexplained skip or xfail
- `config.yaml` loads into a frozen typed Settings; its `risk:` section exists with the PROGRESS.md values and no code path writes it
- No secret value can reach a log line; `.env.example` holds empty values only
- Independent M0 audit report seen by the operator

## Boundaries

- Out: any trading logic, data download, broker or engine code (M1-M3).
- Out: adding any dependency beyond brief §6 (SAF-13).

## References

- parent — docs/stories/initiative-trading-bot-v1/initiative-trading-bot-v1.md, Requirements
- prd — docs/planning/prd.md, Milestones and acceptance criteria (M0)
- brief — first_brief.txt, §9 M0
- architecture — docs/planning/architecture.md, Capability to architecture map
- decisions — PROGRESS.md, Decisions log

## Notes

- Decision: 2026-11-11 — Refactor sweep declined for M0: the skeleton has no deferred findings to clean (headless; operator may override).
- Decision: 2026-11-11 — Tracer bullet: story 1 (skeleton + lockfile + one check command).
- Assumption: Python 3.12 (uv-managed) per architecture Stack and the existing pyproject; brief says ≥3.11.
- Open question: M0 code is being written concurrently by another agent; the M0 audit compares its result against these stories.

