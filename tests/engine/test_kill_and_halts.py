"""Story M3-5: kill switch and halts stop trading, cancel orders, keep the position
(FR-33, FR-36, FR-37, FR-61, FR-62, AD-11, AD-12; GL-03, GL-04 engine level)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

import bot.engine as engine_mod
from bot import cli
from bot.risk.kill_switch import engage
from bot.store import iso
from tests.engine.fake_env import FakeEnv


def _resting_half_filled(env: FakeEnv) -> tuple[str, Decimal]:
    env.tick()
    order = env.orders()[0]
    half = Decimal(order["qty"]) / 2
    env.broker.fill(order["cl_ord_id"], half)
    return order["cl_ord_id"], half


def _assert_stopped(env: FakeEnv, cl: str, half: Decimal, rule: str) -> None:
    assert cl in env.broker.cancel_calls  # cancelled in the same tick
    order = env.orders()[0]
    assert order["state"] == "cancelled"
    assert Decimal(order["filled_qty"]) == half  # final fills ingested
    intent = env.intents()[0]
    assert intent["state"] == "halted"
    assert env.signals()[0]["outcome"] == "halted"
    assert env.store.position("BTC/EUR") == half  # position kept, nothing sold
    assert all(r.side == "buy" for r in env.broker.submitted)
    n_submitted = len(env.broker.submitted)
    for _ in range(3):
        env.tick()
    assert len(env.broker.submitted) == n_submitted  # no new order while stopped
    events = [e for e in env.store.all("SELECT * FROM risk_events") if e["rule"] == rule]
    assert events and events[0]["reason"]


@pytest.mark.parametrize("source", ["file", "cli", "dashboard"])
def test_kill_switch_cancels_resting_order_and_keeps_position(tmp_path, source: str) -> None:
    env = FakeEnv(tmp_path)
    cl, half = _resting_half_filled(env)
    if source == "file":
        env.kill_path.parent.mkdir(parents=True, exist_ok=True)
        env.kill_path.write_bytes(b"")  # created by hand
    else:
        engage(env.kill_path, source, env.clock.now())
    env.tick()
    _assert_stopped(env, cl, half, "kill_switch")
    kill_on = env.risk_events("kill_on")
    assert len(kill_on) == 1  # once per state change, not per tick
    assert f"source={source}" in kill_on[0]["reason"]


def test_daily_loss_halt_cancels_and_keeps_position(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    cl, half = _resting_half_filled(env)
    day = iso(env.clock.now())[:10]
    env.store.execute(  # the day opened much higher: today's loss exceeds 10%
        "UPDATE equity_snapshots SET equity = '30' WHERE is_day_open = 1 AND substr(at,1,10) = ?",
        (day,),
    )
    env.tick()
    assert "daily_loss" in env.halts()
    _assert_stopped(env, cl, half, "daily_loss")


def test_total_drawdown_halt_cancels_and_keeps_position(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    cl, half = _resting_half_filled(env)
    env.store.insert(  # an active baseline far above equity: 25% drawdown reached
        "equity_baselines", at=iso(env.clock.now()), equity="40", reason="test"
    )
    env.tick()
    assert "total_drawdown" in env.halts()
    _assert_stopped(env, cl, half, "total_drawdown")


def test_halt_never_expires_on_a_timer(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.engine.raise_halt(env.clock.now(), "daily_loss", "test")
    for _ in range(4):
        env.tick(timedelta(hours=12))  # crosses a UTC day: a new day-open equity
    assert env.halts() == ["daily_loss"]


def test_kill_switch_is_re_read_just_before_place_order(tmp_path, monkeypatch) -> None:
    env = FakeEnv(tmp_path)
    real = engine_mod.check_order

    def check_then_engage(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        decision = real(*args, **kwargs)
        engage(env.kill_path, "dashboard", env.clock.now())  # arrives after the check
        return decision

    monkeypatch.setattr(engine_mod, "check_order", check_then_engage)
    env.tick()
    assert env.broker.submitted == []  # blocked before persist and send
    assert env.orders() == []
    assert len(env.risk_events("kill_on")) == 1


def test_new_intents_are_blocked_while_killed(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    engage(env.kill_path, "cli", env.clock.now())
    env.tick()
    assert env.broker.submitted == []
    assert env.signals() == []  # no signal evaluation while stopped


def test_kill_off_deletes_the_file_only_through_the_engine(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    engage(env.kill_path, "cli", env.clock.now())
    env.tick()
    env.store.insert("operator_actions", at=iso(env.clock.now()), kind="kill_off", note="all clear")
    assert env.kill_path.exists()  # writing the action deletes nothing
    env.tick()
    assert not env.kill_path.exists()
    action = env.store.one("SELECT * FROM operator_actions WHERE kind = 'kill_off'")
    assert action["consumed_at"] is not None and action["result"] == "kill switch file deleted"
    assert len(env.risk_events("kill_off")) == 1
    env.tick()  # trading resumes: the daily signal is evaluated and an order placed
    assert len(env.broker.submitted) == 1


def test_cli_kill_on_engages_and_off_only_records_an_action(tmp_path, monkeypatch) -> None:
    from bot.clock import FakeClock
    from tests.engine.helpers import T0, dry_run, run

    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, _ = dry_run(tmp_path, clock)
    run(dry, ticks=1)
    monkeypatch.setattr(cli, "_clock_factory", lambda: clock)
    cfg = ["--config", str(tmp_path / "config.yaml"), "--env-file", str(tmp_path / "none.env")]
    kill = dry.settings.risk.kill_switch_path
    assert cli.main(["kill", "on", "--note", "test", *cfg], env={}) == cli.EXIT_OK
    assert kill.read_text(encoding="utf-8").startswith("source=cli at=")
    clock.advance(timedelta(seconds=5))  # the operator disengages later (a tie keeps it on)
    assert cli.main(["kill", "off", "--note", "test", *cfg], env={}) == cli.EXIT_OK
    assert kill.exists()  # the CLI never deletes the file
    kinds = [
        r["kind"] for r in dry.store.all("SELECT kind FROM operator_actions ORDER BY action_id")
    ]
    assert kinds == ["kill_on", "kill_off"]
    run(dry, ticks=2)  # the engine consumes kill_off and deletes the file
    assert not kill.exists()
    assert dry.store.one("SELECT count(*) FROM operator_actions WHERE consumed_at IS NULL")[0] == 0
