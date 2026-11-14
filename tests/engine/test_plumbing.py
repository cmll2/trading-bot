"""Story M3-10: plumbing strategy on its own store, never live (FR-09, FR-10, FR-63,
AD-15, AD-30)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest

from bot import cli, ops
from bot.candles import CandleHistory
from bot.clock import FakeClock
from bot.config import LIVE_GATE_ENV, LIVE_GATE_VALUE
from bot.strategy.plumbing import LABEL, Plumbing
from bot.strategy.registry import LIVE_STRATEGIES, StrategyNotAllowed, build
from tests.engine.helpers import T0, dry_run, run
from tests.fakes.ccxt_public import FakePublicKraken


def _hist(hours: list[int]) -> CandleHistory:
    base = datetime(2026, 11, 14, tzinfo=UTC)
    opens = [base + timedelta(hours=h) for h in hours]
    frame = pd.DataFrame(
        {
            "open_at": pd.to_datetime(opens, utc=True), "open": 1.0, "high": 1.0, "low": 1.0,
            "close": 1.0, "volume": 1.0, "source": "api",
        }
    )  # fmt: skip
    return CandleHistory.from_frame(frame, "1h", base + timedelta(hours=max(hours) + 1))


def test_plumbing_builds_for_dry_run_and_backtest_only() -> None:
    assert build("plumbing", {"flip_hours": 2, "target_pct": 50}, "dry-run").id == "plumbing"
    assert "plumbing" not in LIVE_STRATEGIES
    assert Plumbing.allowed_modes == frozenset({"backtest", "dry-run"})
    with pytest.raises(StrategyNotAllowed):
        build("plumbing", {}, "live")


def test_plumbing_cannot_start_live_even_with_both_gates(tmp_path) -> None:
    from tests.conftest import REPO_ROOT

    argv = ["live", "--live", "--strategy", "plumbing", "--config", str(REPO_ROOT / "config.yaml"),
            "--env-file", str(tmp_path / "none.env")]  # fmt: skip
    assert cli.main(argv, env={LIVE_GATE_ENV: LIVE_GATE_VALUE}) == cli.EXIT_REFUSED


def test_plumbing_alternates_every_flip_hours_and_claims_no_edge() -> None:
    s = Plumbing({"flip_hours": 2, "target_pct": 50})
    targets = [s.on_candle(_hist([h])) for h in range(6)]
    # 2026-11-14 00:00 is hour 493,512 since the epoch: an even 2-hour block
    assert targets == [Decimal("0.5"), Decimal("0.5"), 0, 0, Decimal("0.5"), Decimal("0.5")]
    assert s.indicators(_hist([0]))["no_edge"] == 1.0
    assert s.label == LABEL == "plumbing - no edge"


def test_plumbing_dry_run_produces_several_orders_on_its_own_store(tmp_path) -> None:
    # Start just before 01:00: the 00:00 hourly candle is in a "hold 50 %" block.
    clock = FakeClock(T0 + timedelta(minutes=59, seconds=55))
    exchange = FakePublicKraken(clock)
    dry, _ = dry_run(tmp_path, clock, exchange, strategy="plumbing")
    assert dry.db_path.name == "dry-run-plumbing.sqlite"
    assert run(dry, ticks=240).exit_code == 0  # two hours of 30 s ticks (SIMULATED)
    st = dry.store
    assert st.get_meta("strategy_id") == "plumbing" and st.get_meta("mode") == "dry-run"
    orders = st.one("SELECT count(*) FROM orders")[0]
    assert orders >= 3  # 2 per hourly intent (first + one 30-min re-price), unfilled
    assert {r[0] for r in st.all("SELECT strategy_id FROM signals")} == {"plumbing"}
    assert not (tmp_path / "var" / "state" / "dry-run-v0_trend.sqlite").exists()
    status = ops.status(dry.db_path, clock.now(), 30, tmp_path / "KILL")
    assert "plumbing - no edge" in status.lines[0] and "SIMULATED" in status.lines[0]


def test_plumbing_execution_window_fits_its_timeframe(tmp_path) -> None:
    dry, _ = dry_run(tmp_path, FakeClock(T0), strategy="plumbing")
    cfg = dry.engine.cfg
    assert cfg.timeframe == "1h" and cfg.window == timedelta(minutes=60)
    assert cfg.reprice_interval == timedelta(minutes=30)
