---
title: 'Manual and autonomous approval modes'
type: feature
ticket: '7'
created: '2026-11-14'
status: built
baseline_revision: 'ccbf9bc'
route: full
route_source: coordinator
risk: medium
review: quick
review_source: batched review of stories 5-8
---

## Intent

`execution.approval` manual or autonomous (AD-16). In manual mode a new intent starts in
`awaiting_approval` with `approval_deadline_at = window_end_at`; the engine prints and logs
the order with its allowed price band (+/- `price_sanity_fraction` of the reference price).
`bot approve <id>` / `bot reject <id> --note` insert `operator_actions`; the engine consumes
them. Reject and deadline both end with signal outcome `skipped_by_operator`. Approval covers
the intent: re-prices inside the band need no re-approval and every submission still passes
the risk checks (a move outside the band is rejected by `price_sanity`).

`bot dry-run --approval autonomous` overrides the config for one session (logged with the
config value). The 48 h unattended dry-run uses it (decision in PROGRESS.md): nobody is
there to approve, and config.yaml keeps `manual` as the default for the first live weeks.

## Built

bot/engine.py: `_action_approve`, `_action_reject`, `_expire_if_due`, `_announce_approval`
(stdout + log, the CLI approval channel, OD-13).

## Verification

`tests/engine/test_approval.py` (7): autonomous sends at once; manual waits and prints the
band; approve -> working and the order goes out; reject and deadline -> skipped_by_operator;
approve after the deadline is too late; re-price inside the band without a new approval,
outside the band rejected by price_sanity.
