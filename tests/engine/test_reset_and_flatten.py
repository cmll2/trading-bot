"""Story M3-6: manual halt reset and flatten from the CLI (FR-33, FR-37, AD-11, AD-12,
AD-17, AD-25, AD-26, SAF-05)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from bot import cli
from bot.broker.base import Ticker
from bot.clock import FakeClock
from bot.risk.kill_switch import engage
from bot.store import iso
from tests.engine.fake_env import FakeEnv
from tests.engine.helpers import T0, dry_run, run


def _action(env: FakeEnv, kind: str, target: str | None = None, rebase: bool = False) -> int:
    return env.store.insert(
        "operator_actions", at=iso(env.clock.now()), kind=kind, target_id=target,
        note=f"test {kind}", rebase_baseline=int(rebase),
    )  # fmt: skip


def _long(env: FakeEnv) -> Decimal:
    """Buy and fully fill: the account holds a sellable position."""
    env.tick()
    order = env.orders()[0]
    env.broker.fill(order["cl_ord_id"], Decimal(order["qty"]))
    env.tick()
    assert env.intents()[0]["state"] == "done"
    return env.store.position("BTC/EUR")


def _baselines(env: FakeEnv) -> list[dict]:
    return [dict(r) for r in env.store.all("SELECT * FROM equity_baselines ORDER BY baseline_id")]


def test_daily_loss_halt_stays_until_reset_without_rebase(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.engine.raise_halt(env.clock.now(), "daily_loss", "test")
    env.tick(timedelta(hours=30))
    assert env.halts() == ["daily_loss"]
    action = _action(env, "reset_halt", "daily_loss")
    before = _baselines(env)
    env.tick()
    assert env.halts() == []
    halt = env.store.one("SELECT * FROM halts")
    assert halt["reset_action_id"] == action and halt["reset_at"] is not None
    assert _baselines(env) == before  # no rebase without --rebase-baseline
    assert len(env.risk_events("halt_reset")) == 1
    row = env.store.one("SELECT * FROM operator_actions WHERE action_id = ?", (action,))
    assert row["result"] == "reset daily_loss"


def test_total_drawdown_reset_with_rebase_appends_a_baseline_with_the_action(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.engine.raise_halt(env.clock.now(), "total_drawdown", "test")
    action = _action(env, "reset_halt", "total_drawdown", rebase=True)
    env.tick()
    rows = _baselines(env)
    assert len(rows) == 2 and rows[-1]["action_id"] == action
    assert env.halts() == []


def test_rebase_flag_does_nothing_for_a_daily_loss_reset(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.engine.raise_halt(env.clock.now(), "daily_loss", "test")
    _action(env, "reset_halt", "daily_loss", rebase=True)
    env.tick()
    assert len(_baselines(env)) == 1


def test_reset_of_an_inactive_rule_changes_nothing(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.engine.raise_halt(env.clock.now(), "daily_loss", "test")
    action = _action(env, "reset_halt", "total_drawdown")
    env.tick()
    assert env.halts() == ["daily_loss"]
    row = env.store.one("SELECT result FROM operator_actions WHERE action_id = ?", (action,))
    assert row["result"].startswith("no active halt")


def test_pending_reset_is_applied_at_startup_before_reconciliation(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.engine.raise_halt(env.clock.now(), "reconcile_mismatch", "test")
    _action(env, "reset_halt", "all")
    env.restart()  # recover() consumes reset_halt actions (AD-8 step 2)
    assert env.halts() == []


def test_flatten_while_halted_sells_the_full_base(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    position = _long(env)
    env.engine.raise_halt(env.clock.now(), "daily_loss", "test")
    engage(env.kill_path, "cli", env.clock.now())  # killed as well: flatten is exempt
    action = _action(env, "flatten")
    env.tick()
    flat = env.intents()[-1]
    assert flat["is_flatten"] == 1 and flat["source_action_id"] == action
    assert flat["side"] == "sell"
    sells = [r for r in env.broker.submitted if r.side == "sell"]
    assert len(sells) == 1 and sells[0].qty == position
    env.broker.fill(sells[0].cl_ord_id, position)
    env.tick()
    assert env.store.position("BTC/EUR") == 0
    assert env.intents()[-1]["state"] == "done"


def test_flatten_is_not_exempt_from_stale_ticker(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    _long(env)
    env.engine.raise_halt(env.clock.now(), "daily_loss", "test")
    _action(env, "flatten")
    env.clock.advance(timedelta(seconds=30))
    p = env.price
    env.broker.ticker = Ticker("BTC/EUR", p - 1, p + 1, p, env.clock.now() - timedelta(seconds=300))
    env.engine.tick()
    assert [r.side for r in env.broker.submitted] == ["buy"]  # no sell while blind
    env.tick()  # a fresh ticker: the flatten sell goes out
    assert [r.side for r in env.broker.submitted] == ["buy", "sell"]


def test_flatten_cancels_the_active_intent_as_skipped_by_operator(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    position = _long(env)
    env.strategy.target = Decimal(0)  # the next daily signal asks to sell
    env.tick(timedelta(days=1))
    sell_intent = env.intents()[-1]
    assert sell_intent["side"] == "sell" and sell_intent["state"] == "working"
    _action(env, "flatten")
    env.tick()
    intents = env.intents()
    assert intents[-2]["state"] == "cancelled"
    assert env.signals()[-1]["outcome"] == "skipped_by_operator"
    assert intents[-1]["is_flatten"] == 1
    assert env.broker.submitted[-1].qty == position


def test_flatten_with_no_position_is_a_no_op(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.engine.raise_halt(env.clock.now(), "daily_loss", "test")
    action = _action(env, "flatten")
    env.tick()
    row = env.store.one("SELECT result FROM operator_actions WHERE action_id = ?", (action,))
    assert row["result"].startswith("nothing to flatten")
    assert env.broker.submitted == []


def _table_counts(store) -> dict[str, int]:  # noqa: ANN001
    names = [r[0] for r in store.all("SELECT name FROM sqlite_master WHERE type='table'")]
    return {n: store.one(f"SELECT count(*) FROM {n}")[0] for n in names}  # noqa: S608


@pytest.fixture
def cli_env(tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, _ = dry_run(tmp_path, clock)
    run(dry, ticks=1)
    monkeypatch.setattr(cli, "_clock_factory", lambda: clock)
    cfg = ["--config", str(tmp_path / "config.yaml"), "--env-file", str(tmp_path / "none.env")]
    return dry, cfg


@pytest.mark.parametrize(
    "argv",
    [
        ["reset-halt", "daily_loss", "--note", "n"],
        ["flatten", "--note", "n"],
        ["approve", "1"],
        ["reject", "1", "--note", "n"],
        ["kill", "off", "--note", "n"],
    ],
)
def test_cli_writes_only_operator_actions(cli_env, argv) -> None:  # noqa: ANN001
    dry, cfg = cli_env
    before = _table_counts(dry.store)
    assert cli.main([*argv, *cfg], env={}) == cli.EXIT_OK
    after = _table_counts(dry.store)
    changed = {k for k in after if after[k] != before[k]}
    assert changed == {"operator_actions"}


def test_cli_rebase_needs_the_typed_confirmation(cli_env, monkeypatch) -> None:  # noqa: ANN001
    dry, cfg = cli_env
    monkeypatch.setattr("builtins.input", lambda: "yes")
    argv = ["reset-halt", "total_drawdown", "--note", "n", "--rebase-baseline", *cfg]
    assert cli.main(argv, env={}) == cli.EXIT_REFUSED
    assert dry.store.one("SELECT count(*) FROM operator_actions")[0] == 0
    monkeypatch.setattr("builtins.input", lambda: "REBASE")
    assert cli.main(argv, env={}) == cli.EXIT_OK
    row = dry.store.one("SELECT * FROM operator_actions")
    assert row["kind"] == "reset_halt" and row["rebase_baseline"] == 1


def test_cli_rebase_is_refused_for_other_rules(cli_env) -> None:  # noqa: ANN001
    dry, cfg = cli_env
    argv = ["reset-halt", "daily_loss", "--note", "n", "--rebase-baseline", *cfg]
    assert cli.main(argv, env={}) == cli.EXIT_REFUSED
    assert dry.store.one("SELECT count(*) FROM operator_actions")[0] == 0
