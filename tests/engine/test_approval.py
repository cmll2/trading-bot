"""Story M3-7: manual and autonomous approval modes (FR-40, FR-44, AD-16, AD-28)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from bot.store import iso
from tests.engine.fake_env import FakeEnv


def _act(env: FakeEnv, kind: str, intent_id: int, note: str = "n") -> int:
    return env.store.insert(
        "operator_actions", at=iso(env.clock.now()), kind=kind, target_id=str(intent_id), note=note
    )


def test_autonomous_intent_is_sent_at_once(tmp_path) -> None:
    env = FakeEnv(tmp_path, approval="autonomous")
    env.tick()
    assert env.intents()[0]["state"] == "working"
    assert len(env.broker.submitted) == 1


def test_manual_intent_waits_and_prints_the_band(tmp_path, capsys) -> None:
    env = FakeEnv(tmp_path, approval="manual")
    env.tick()
    intent = env.intents()[0]
    assert intent["state"] == "awaiting_approval"
    assert intent["approval_deadline_at"] == intent["window_end_at"]
    assert env.broker.submitted == []
    out = capsys.readouterr().out
    assert f"APPROVAL NEEDED (intent {intent['intent_id']})" in out
    assert "39200.00..40800.00" in out  # +/-2% price-sanity band around 40000
    for _ in range(3):
        env.tick()
    assert env.broker.submitted == []  # still waiting


def test_approve_moves_to_working_and_the_order_goes_out(tmp_path) -> None:
    env = FakeEnv(tmp_path, approval="manual")
    env.tick()
    intent_id = env.intents()[0]["intent_id"]
    action = _act(env, "approve", intent_id)
    env.tick()
    assert env.intents()[0]["state"] == "working"
    assert len(env.broker.submitted) == 1
    row = env.store.one("SELECT result FROM operator_actions WHERE action_id = ?", (action,))
    assert row["result"] == f"intent {intent_id} approved"


def test_reject_gives_skipped_by_operator(tmp_path) -> None:
    env = FakeEnv(tmp_path, approval="manual")
    env.tick()
    _act(env, "reject", env.intents()[0]["intent_id"], note="not today")
    env.tick()
    assert env.intents()[0]["state"] == "cancelled"
    sig = env.signals()[0]
    assert sig["outcome"] == "skipped_by_operator" and "not today" in sig["outcome_reason"]
    assert env.broker.submitted == []


def test_deadline_gives_skipped_by_operator(tmp_path) -> None:
    env = FakeEnv(tmp_path, approval="manual")
    env.tick()
    env.tick(timedelta(hours=6))  # past the window end
    assert env.intents()[0]["state"] == "expired"
    sig = env.signals()[0]
    assert (sig["outcome"], sig["outcome_reason"]) == ("skipped_by_operator", "approval expired")
    assert env.broker.submitted == []


def test_approve_after_the_deadline_is_too_late(tmp_path) -> None:
    env = FakeEnv(tmp_path, approval="manual")
    env.tick()
    intent_id = env.intents()[0]["intent_id"]
    env.clock.advance(timedelta(hours=6))
    action = _act(env, "approve", intent_id)
    env.tick()
    assert env.intents()[0]["state"] == "expired"
    assert env.broker.submitted == []
    row = env.store.one("SELECT result FROM operator_actions WHERE action_id = ?", (action,))
    assert row["result"] == "too late: the intent expired"


def test_reprices_inside_the_band_need_no_new_approval_but_pass_risk(tmp_path) -> None:
    env = FakeEnv(tmp_path, approval="manual")
    env.tick()
    _act(env, "approve", env.intents()[0]["intent_id"])
    env.tick()
    env.price = Decimal("40400")  # +1%: inside the band
    env.tick(timedelta(minutes=31))
    assert len(env.broker.submitted) == 2  # re-priced, no approval asked
    assert env.broker.submitted[-1].limit_price > env.broker.submitted[0].limit_price
    env.price = Decimal("41000")  # +2.5%: outside the band, price_sanity rejects
    env.tick(timedelta(minutes=31))
    assert len(env.broker.submitted) == 2
    assert env.intents()[0]["state"] == "cancelled"
    assert env.signals()[0]["outcome"] == "rejected_by_risk"
    assert any(e["rule"] == "price_sanity" for e in env.risk_events("rejection"))
