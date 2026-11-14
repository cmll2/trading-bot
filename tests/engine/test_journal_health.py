"""Story M3-8: complete journal outcomes, snapshots, health records and backups (FR-38,
FR-39, FR-40, NFR-05, NFR-07, AD-11, AD-22, AD-28, architecture §2 Backups)."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

import pytest

from bot import journal
from bot.clock import FakeClock
from bot.store import Store, iso
from tests.engine.fake_env import FakeEnv
from tests.engine.helpers import T0, dry_run, run


def _outcome(env: FakeEnv) -> str:
    return env.signals()[0]["outcome"]


def _scenario(env: FakeEnv, outcome: str) -> None:  # noqa: C901, PLR0912
    if outcome == "no_action":
        env.strategy.target = Decimal(0)  # flat target, no position
        env.tick()
    elif outcome == "filled":
        env.tick()
        o = env.orders()[0]
        env.broker.fill(o["cl_ord_id"], Decimal(o["qty"]))
        env.tick()
    elif outcome == "not_filled":
        env.tick()
        env.tick(timedelta(hours=6))
    elif outcome == "partially_filled":
        env.tick()
        o = env.orders()[0]
        env.broker.fill(o["cl_ord_id"], Decimal(o["qty"]) / 2)
        env.tick(timedelta(hours=6))
    elif outcome == "rejected_by_risk":
        env.price = Decimal("41000")  # ticker 2.5% away from the 40000 signal close
        env.tick()
    elif outcome == "skipped_by_operator":
        env.engine.cfg = env.engine.cfg.__class__(
            **{**env.engine.cfg.__dict__, "approval": "manual"}
        )
        env.tick()
        env.store.insert(
            "operator_actions", at=iso(env.clock.now()), kind="reject",
            target_id=str(env.intents()[0]["intent_id"]), note="no",
        )  # fmt: skip
        env.tick()
    elif outcome == "below_minimum":
        env.strategy.target = Decimal("0.01")  # EUR 0.20: below the exchange minimums
        env.tick()
    elif outcome == "halted":
        env.tick()
        env.engine.raise_halt(env.clock.now(), "daily_loss", "test")
        env.tick()
    elif outcome == "dust":
        env.tick()
        env.broker.fill(env.orders()[0]["cl_ord_id"], Decimal("0.00001"))  # unsellable
        env.tick(timedelta(hours=6))  # window end: a completion intent starts
        assert len(env.intents()) == 2
        env.tick(timedelta(hours=24))  # its window passes unfilled
    else:  # pragma: no cover
        raise AssertionError(outcome)


ALL_OUTCOMES = [
    "no_action", "filled", "partially_filled", "not_filled", "rejected_by_risk",
    "skipped_by_operator", "below_minimum", "halted", "dust",
]  # fmt: skip


@pytest.mark.parametrize("outcome", ALL_OUTCOMES)
def test_every_ad28_outcome_is_produced(tmp_path, outcome: str) -> None:
    env = FakeEnv(tmp_path)
    _scenario(env, outcome)
    assert _outcome(env) == outcome
    pending = env.store.one("SELECT count(*) FROM signals WHERE outcome = 'pending'")[0]
    assert pending == 0  # one final outcome per signal


def test_outcome_and_final_intent_state_are_written_together(tmp_path, monkeypatch) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    real = env.engine._set_outcome  # noqa: SLF001

    def boom(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise RuntimeError("crash while journaling")

    monkeypatch.setattr(env.engine, "_set_outcome", boom)
    with pytest.raises(RuntimeError):
        env.tick(timedelta(hours=6))
    monkeypatch.setattr(env.engine, "_set_outcome", real)
    # the intent did NOT move to its final state without its outcome (one transaction)
    assert env.intents()[0]["state"] == "working"
    assert _outcome(env) == "pending"


def test_each_tick_writes_equity_and_risk_snapshots_and_one_day_open_per_day(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    for _ in range(3):
        env.tick()
    env.tick(timedelta(days=1))
    env.tick()
    snaps = env.store.one("SELECT count(*) FROM equity_snapshots")[0]
    risk = env.store.all("SELECT * FROM risk_snapshots ORDER BY at")
    assert snaps == 5 and len(risk) == 5
    days = env.store.all("SELECT substr(at,1,10) d FROM equity_snapshots WHERE is_day_open = 1")
    assert [d["d"] for d in days] == ["2026-11-14", "2026-11-15"]
    usage = json.loads(risk[-1]["usage_json"])
    assert usage["orders_today"][1] == env.limits.max_order_intents_per_day
    assert set(usage) >= {"daily_loss", "total_drawdown", "ticker_age_s", "candle_age_s"}
    context = json.loads(risk[-1]["context_json"])
    assert context["limits_hash"] == "l" and context["kill_switch_engaged"] is False


def test_day_open_equity_is_written_before_any_risk_check(tmp_path, monkeypatch) -> None:
    import bot.engine as engine_mod

    env = FakeEnv(tmp_path)
    seen: list[int] = []
    real = engine_mod.check_order

    def spy(*a, **k):  # noqa: ANN002, ANN003, ANN202
        seen.append(env.store.one("SELECT count(*) FROM equity_snapshots WHERE is_day_open=1")[0])
        return real(*a, **k)

    monkeypatch.setattr(engine_mod, "check_order", spy)
    env.tick()
    assert seen and seen[0] == 1


def test_error_rows_are_redacted(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    secret = "kR4k3nS3cr3tV4lu3=="  # noqa: S105 - a fake value planted on purpose
    msg = f"request failed: API-Key: AbCdEf123456 secret={secret}"
    env.engine.error(env.clock.now(), "test", RuntimeError(msg), tb=f"Tb ... apiKey='{secret}'")
    row = env.store.one("SELECT message, traceback FROM errors")
    assert "AbCdEf123456" not in row["message"] and secret not in row["message"]
    assert secret not in row["traceback"]
    assert "REDACTED" in row["message"]


def test_dry_run_records_api_calls_and_writes_a_daily_backup(tmp_path) -> None:
    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, _ = dry_run(tmp_path, clock)
    assert run(dry, ticks=3).exit_code == 0
    calls = dry.store.all("SELECT endpoint, latency_ms, ok, rate_limited FROM api_calls")
    assert {"fetch_ticker", "load_markets"} <= {c["endpoint"] for c in calls}
    backups = sorted((tmp_path / "var" / "backups").glob("*.sqlite"))
    assert [b.name for b in backups] == ["dry-run-v0_trend-20261114.sqlite"]
    copy = Store.open_readonly(backups[0])
    assert copy.get_meta("mode") == "dry-run"
    copy.close()


def test_housekeeping_keeps_30_backups_and_prunes_health_rows(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    old = iso(env.clock.now() - timedelta(days=31))
    env.store.insert("api_calls", at=old, endpoint="x", latency_ms=1, ok=1, rate_limited=0)
    env.store.insert("heartbeats", run_id=env.engine.run_id, at=old, loop_state="tick")
    backups = tmp_path / "backups"
    for day in range(35):
        env.engine.housekeeping(env.clock.now() + timedelta(days=day), backups)
    assert len(list(backups.glob("*.sqlite"))) == 30
    assert env.store.one("SELECT count(*) FROM api_calls WHERE at = ?", (old,))[0] == 0
    assert env.store.one("SELECT count(*) FROM heartbeats WHERE at = ?", (old,))[0] == 0


def test_journal_estimates_would_have_returned_for_untraded_signals(tmp_path) -> None:
    env = FakeEnv(tmp_path)
    env.tick()
    env.tick(timedelta(hours=6))  # not_filled
    assert _outcome(env) == "not_filled"
    env.store.insert(
        "equity_snapshots", at=iso(env.clock.now() + timedelta(seconds=1)), equity="20",
        cash="20", base_qty="0", mark_price="44000", buy_hold_equity="22",
    )  # fmt: skip
    rows = journal.rows(env.store)
    assert rows[0].outcome == "not_filled" and rows[0].exit_kind == "open"
    expected = Decimal(44000) * Decimal("0.996") / (Decimal(40000) * Decimal("1.004")) - 1
    assert rows[0].would_have_returned == expected
    assert journal.would_have_returned("sell", Decimal(100), Decimal(90), Decimal(0)) > 0
