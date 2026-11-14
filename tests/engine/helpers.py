"""Shared helpers for the M3 dry-run engine tests (FakeClock + fake public ccxt)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import yaml

from bot.clock import FakeClock
from bot.config import Settings, load_settings
from bot.runtime import DryRun, EngineLock, StopFlag, build_dry_run, run_loop
from tests.conftest import REPO_ROOT
from tests.fakes.ccxt_public import FakePublicKraken

T0 = datetime(2026, 11, 14, 0, 0, 0, tzinfo=UTC)


def make_settings(tmp_path: Path, **execution: object) -> Settings:
    """The real config.yaml with var_dir and the kill-switch path under ``tmp_path``.
    No risk limit value is changed."""
    data = yaml.safe_load((REPO_ROOT / "config.yaml").read_text(encoding="utf-8"))
    data["paths"]["var_dir"] = str(tmp_path / "var")
    data["risk"]["kill_switch_path"] = str(tmp_path / "var" / "KILL")
    data["execution"].update(execution)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_settings(path, tmp_path / "none.env")


def dry_run(
    tmp_path: Path,
    clock: FakeClock,
    exchange: FakePublicKraken | None = None,
    strategy: str = "v0_trend",
    approval: str = "autonomous",
    settings: Settings | None = None,
) -> tuple[DryRun, FakePublicKraken]:
    settings = settings or make_settings(tmp_path)
    exchange = exchange or FakePublicKraken(clock)
    return build_dry_run(settings, strategy, exchange, clock, approval=approval), exchange


def run(dry: DryRun, ticks: int, *, pid: int = 4242, skew: float = 0.0):  # noqa: ANN201
    lock = EngineLock(dry.db_path.with_name(dry.db_path.name + ".lock"), pid=pid)
    result = run_loop(dry, StopFlag(), max_ticks=ticks, lock=lock, skew=lambda: skew)
    return result
