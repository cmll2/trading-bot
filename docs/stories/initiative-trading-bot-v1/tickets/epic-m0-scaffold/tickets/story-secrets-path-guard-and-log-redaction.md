---
id: 5
type: story
title: "Secrets path guard and log redaction"
parent: epic-m0-scaffold
covers: ["R3", "R4"]
after: [3]
refined: false
hitl: false
risk: high
protected: false
---

# Secrets path guard and log redaction

## Description

`.env.example` with empty values, a secrets loader that refuses paths inside the repo, and a root logging filter writing JSON lines with secrets redacted.

## Requirements

Verify: A test plants fake secrets in a temp file outside the repo, logs and raises through a wrapper, and asserts neither value appears in the log file or the exception text.

1. **Secrets file outside the repo only** (SAF-01, AD-22)
   **Given** `TRADING_BOT_SECRETS_FILE` set to a path inside the repository
   **When** the loader runs
   **Then** it refuses with an error that names the rule, not the content
   **And** a path outside the repo is read into SecretStr and never into os.environ
2. **Redaction everywhere** (SAF-02, NFR-07, FR-43)
   **Given** planted fake key and secret values and `API-Key`/`API-Sign` header patterns
   **When** they pass through log calls and an exception traceback
   **Then** the JSON-lines log in var/logs/ shows them redacted, and the same redaction function is exposed for store error rows
3. **Template only** (SAF-01)
   **Given** `.env.example`
   **When** it is read
   **Then** it holds `TRADING_BOT_SECRETS_FILE=` with an empty value and nothing else secret

## Constraints

- None beyond the epic.

## Boundaries

- Must not change: config.yaml `risk:`, bot/risk/, tests/risk/ (protected; SAF-04).
- Must not change: any existing test's assertions to make the suite pass (FR-64).

## References

- parent — docs/stories/initiative-trading-bot-v1/tickets/epic-m0-scaffold/epic-m0-scaffold.md, Requirements R3, R4
- prd — docs/planning/prd.md, FR-43, NFR-07, SAF-01, SAF-02
- architecture — docs/planning/architecture.md, AD-22
- architecture — docs/planning/architecture.md, Consistency conventions: Logging

## Notes

- Never open or read the real secrets file during development (SAF-02); tests use temp files only.
- High risk: a leak exposes the trading key. Extra check: grep var/logs after the suite for the planted values.
- Assumption: criteria drafted headless by Sofia on 2026-11-11 from the PRD, architecture and PROGRESS.md; awaiting operator approval (then `refined: true`).
