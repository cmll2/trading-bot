---
title: 'Broker port, domain types, error taxonomy and FakeBroker'
type: feature
ticket: '1'
created: '2026-11-13'
status: built
baseline_revision: 'ee3905d'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: false
context: []
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** The Broker port exists only as M0 signatures; nothing enforces the risk decision at the adapter, and tests have no scriptable broker for engine work.

**Approach:** Keep the §1 port and the six-error taxonomy, add one shared adapter guard (`require_approved`) every adapter calls first in `place_order`, and a scriptable `FakeBroker` under `tests/fakes/`.

## Boundaries & Constraints

**Always:** Decimal money, tz-aware UTC datetimes; FakeBroker raises only the six taxonomy errors for scripted failures; the guard raises before any state change.

**Never:** touch bot/risk/, tests/risk/, config.yaml `risk:`; add exchange-specific methods to the port; network access.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|---|---|---|---|
| approved | decision approved, same cl_ord_id | OrderAck, order open | none |
| missing decision | decision None | nothing placed | RiskGateViolation |
| rejected decision | approved False | nothing placed | RiskGateViolation |
| mismatched id | decision.cl_ord_id differs | nothing placed | RiskGateViolation |
| partial fill | script fill qty < order qty | order open, filled_qty updated, Fill returned by get_fills | none |
| timeout after accept | script `timeout_after_accept` | order exists (find_order sees it) | OrderOutcomeUnknown |
| reject / cross | script `reject` / `cross` | nothing exists | OrderRejected / PostOnlyWouldCross |
| rate limit / read failure | script on reads | state unchanged | RateLimited / TransientReadError |
| exchange-side cancel | `exchange_cancel(id)` | find_order state canceled | none |

</intent-contract>

## Code Map

- `bot/broker/base.py` -- port + types (M0); add `RiskGateViolation` and `require_approved(req, decision)`.
- `bot/broker/errors.py` -- the six errors; unchanged.
- `bot/risk/checks.py` -- `RiskDecision` (protected, read-only here).
- `tests/fakes/broker.py` -- new FakeBroker; `tests/fakes/__init__.py`.
- `tests/broker/test_broker_port.py` -- new tests.

## Tasks & Acceptance

**Execution:**
- [x] `bot/broker/base.py` -- add guard and violation type -- AD-10 enforced at every adapter.
- [x] `tests/fakes/broker.py` -- scriptable FakeBroker -- engine tests (stories 4, 6).
- [x] `tests/broker/test_broker_port.py` -- protocol shape, guard, every matrix row.

**Acceptance Criteria:**
- Given the Broker protocol, when inspected, then it exposes exactly the ten §1 methods plus `name`.
- Given scripted failures, when raised, then each is an instance of exactly one of the six taxonomy classes.

## Implementation Notes

Implemented in the coordinator's main session (deviation from the full-route coding subagent: the coordinator holds the cross-story M2 design; recorded in PROGRESS.md).

## Plan Change Log

## Review Triage Log

### 2026-11-13 — Review pass
- verdicts: 11 findings — high 0, medium 2, low 7, false 2, maybe-false 0
- findings:
  - `[low]` `[patch]` taxonomy check "at least one" and missing on timeout/read failures — added `isinstance(TAXONOMY)` on every scripted failure and `type(exc) is scripted`; PostOnlyWouldCross ⊂ OrderRejected is by design (§1).
  - `[low]` `[patch]` signature test covered 5 of 10 methods — now iterates every public protocol member.
  - `[medium]` `[patch]` no late/unknown fill injection — added `FakeBroker.inject_fill(Fill)` + test.
  - `[low]` `[patch]` `exchange_cancel` could cancel a closed order — now refuses non-open orders.
  - `[medium]` `[patch]` `cancel_order` consumed the read script and could raise TransientReadError — cancel no longer uses the read script.
  - `[low]` `[patch]` `placed` missed refused submissions — added `submitted` (every request past the risk gate); `placed` = accepted.
  - `[low]` `[patch]` `cancel_order` ignored pair — now OrderRejected for a wrong pair.
  - `[low]` `[patch]` non-positive fill accepted — refused.
  - `[low]` `[patch]` `name` not the only annotation — test asserts `{"name"}`.
  - `[false]` `[reject]` deviation not yet in PROGRESS.md — recorded in the M2 PROGRESS commit (process step, not code).
  - `[false]` `[reject]` protected files in the working tree — they are committed separately with explicit paths (SAF-04); not part of this commit.

## Auto Run Result

- Summary: `require_approved` + `RiskGateViolation` (AD-10 adapter gate); scriptable FakeBroker (place/read scripts, partial fills, late/unknown fill injection, exchange-side cancel).
- Files: `bot/broker/base.py` (guard), `tests/fakes/broker.py` (FakeBroker), `tests/broker/test_broker_port.py` (tests).
- Review: 9 patches, 0 deferred, 2 rejected (reasons above). Follow-up review recommended: false (2 medium patched in test doubles only; no production-risk code path).
- Verification: `uv run ruff check . && uv run ruff format --check . && uv run pytest` → 654 passed.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass
