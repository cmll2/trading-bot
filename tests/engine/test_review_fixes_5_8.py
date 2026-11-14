"""Regression tests for the quick-review findings on M3 stories 5-8 (triage log in the
story 8 plan)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest

import bot.store as store_mod
from bot import cli, ops
from bot.broker.base import Fill
from bot.broker.errors import TransientReadError
from bot.risk.kill_switch import engage
from bot.store import StoreError, iso
from tests.engine.fake_env import FakeEnv


class Crash(BaseException):
    pass


def _act(env: FakeEnv, kind: str, target: str | None = None, rebase: bool = False) -> int:
    return env.store.insert(
        "operator_actions", at=iso(env.clock.now()), kind=kind, target_id=target,
        note="t", rebase_baseline=int(rebase),
    )  # fmt: skip


def test_an_action_is_never_applied_twice_after_a_crash(tmp_path, monkeypatch) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.engine.raise_halt(env.clock.now(), "total_drawdown", "t")
    _act(env, "reset_halt", "total_drawdown", rebase=True)
    real = env.engine._apply_reset_halt  # noqa: SLF001

    def apply_then_crash(*a):  # noqa: ANN002, ANN202
        real(*a)
        raise Crash  # dies before the transaction commits

    monkeypatch.setattr(env.engine, "_apply_reset_halt", apply_then_crash)
    with pytest.raises(Crash):
        env.tick()
    assert env.halts() == ["total_drawdown"]  # effect rolled back with consumed_at
    env.restart()  # recover() applies the pending reset exactly once
    assert env.halts() == []
    assert env.store.one("SELECT count(*) FROM equity_baselines")[0] == 2
    env.restart()
    assert env.store.one("SELECT count(*) FROM equity_baselines")[0] == 2


def test_kill_off_never_deletes_a_switch_engaged_after_it(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    engage(env.kill_path, "cli", env.clock.now())
    env.tick()
    _act(env, "kill_off")
    env.kill_path.unlink()  # (simulates a clean slate) then the dashboard engages again
    engage(env.kill_path, "dashboard", env.clock.now() + timedelta(seconds=5))
    env.tick(timedelta(seconds=30))
    assert env.kill_path.exists()
    row = env.store.one("SELECT result FROM operator_actions WHERE kind = 'kill_off'")
    assert row["result"].startswith("kept")


def test_kill_file_held_open_does_not_crash_and_is_retried(tmp_path, monkeypatch) -> None:
    env = FakeEnv(tmp_path)
    engage(env.kill_path, "cli", env.clock.now())
    env.tick()
    _act(env, "kill_off")

    def locked(self, missing_ok=False):  # noqa: ANN001, ANN202
        raise PermissionError(32, "The process cannot access the file")

    monkeypatch.setattr(Path, "unlink", locked)
    env.tick()  # no exception
    assert env.store.one("SELECT consumed_at FROM operator_actions")[0] is None
    assert env.store.one("SELECT count(*) FROM errors WHERE component LIKE 'operator_action%'")[0]
    monkeypatch.undo()
    env.tick()
    assert not env.kill_path.exists()


def test_reset_never_closes_a_halt_raised_after_the_command(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    _act(env, "reset_halt", "all")
    env.clock.advance(timedelta(seconds=5))
    env.engine.raise_halt(env.clock.now(), "clock_skew", "raised after the command")
    env.tick()
    assert env.halts() == ["clock_skew"]


def test_kill_switch_cancels_the_resting_order_even_while_the_ticker_fails(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    engage(env.kill_path, "file", env.clock.now())
    env.broker.ticker = None
    env.clock.advance(timedelta(seconds=30))
    env.engine.tick()
    assert env.orders()[0]["state"] == "cancelled"
    assert env.intents()[0]["state"] == "halted"


def test_halt_raised_while_syncing_ends_the_intent_halted(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.broker.inject_fill(
        Fill("T999", "O999", "ghost", "BTC/EUR", "buy", Decimal("0.0001"), Decimal("40000"),
             Decimal("0.016"), "EUR", "maker", env.clock.now())
    )  # fmt: skip
    env.tick(timedelta(minutes=31))  # a re-price would be due
    assert "reconcile_mismatch" in env.halts()
    assert env.intents()[0]["state"] == "halted"
    assert env.signals()[0]["outcome"] == "halted"
    assert len(env.broker.submitted) == 1  # no re-price after the halt


def test_pending_flatten_freezes_the_active_intent(tmp_path, monkeypatch) -> None:
    env = FakeEnv(tmp_path)
    env.tick()

    def cancel_times_out(pair, cl):  # noqa: ANN001, ANN202
        raise TransientReadError("cancel timed out")

    monkeypatch.setattr(env.broker, "cancel_order", cancel_times_out)
    _act(env, "flatten")
    for _ in range(3):
        env.tick(timedelta(minutes=31))
    assert len(env.broker.submitted) == 1  # no re-price while the flatten waits
    assert env.store.one("SELECT consumed_at FROM operator_actions")[0] is None


def test_manual_completion_intent_waits_for_its_own_approval(tmp_path) -> None:
    env = FakeEnv(tmp_path, approval="manual")
    env.tick()
    env.store.insert(
        "operator_actions", at=iso(env.clock.now()), kind="approve",
        target_id=str(env.intents()[0]["intent_id"]), note="ok",
    )  # fmt: skip
    env.tick()
    env.broker.fill(env.orders()[0]["cl_ord_id"], Decimal("0.00001"))  # unsellable part
    env.tick(timedelta(hours=6))
    child = env.intents()[-1]
    assert child["parent_intent_id"] is not None
    assert child["state"] == "awaiting_approval"
    assert len(env.broker.submitted) == 1  # nothing bought without approval


def test_cli_never_migrates_a_store(tmp_path, monkeypatch) -> None:
    env = FakeEnv(tmp_path)
    db = tmp_path / "engine.sqlite"
    monkeypatch.setattr(store_mod, "SCHEMA_VERSION", store_mod.SCHEMA_VERSION + 1)
    with pytest.raises(StoreError):
        ops.write_action(db, env.clock.now(), "flatten", "n")
    monkeypatch.undo()
    assert env.store.one("SELECT count(*) FROM operator_actions")[0] == 0


def test_rebase_confirmation_without_a_terminal_is_refused(tmp_path, monkeypatch) -> None:
    from bot.clock import FakeClock
    from tests.engine.helpers import T0, dry_run, run

    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, _ = dry_run(tmp_path, clock)
    run(dry, ticks=1)

    def no_tty() -> str:
        raise EOFError

    monkeypatch.setattr("builtins.input", no_tty)
    cfg = ["--config", str(tmp_path / "config.yaml"), "--env-file", str(tmp_path / "none.env")]
    argv = ["reset-halt", "total_drawdown", "--note", "n", "--rebase-baseline", *cfg]
    assert cli.main(argv, env={}) == cli.EXIT_REFUSED
    assert dry.store.one("SELECT count(*) FROM operator_actions")[0] == 0
