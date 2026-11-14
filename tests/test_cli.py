"""Tests for the CLI run modes and the live double gate (SAF-08, SAF-09, FR-10, AD-15)."""

from __future__ import annotations

from pathlib import Path

import pytest

from bot import cli
from bot.config import LIVE_GATE_ENV, LIVE_GATE_VALUE, load_settings
from bot.strategy.registry import (
    DRY_RUN_STRATEGIES,
    LIVE_STRATEGIES,
    StrategyNotAllowed,
    strategy_class_for,
)
from tests.conftest import REPO_ROOT

GATE_ON = {LIVE_GATE_ENV: LIVE_GATE_VALUE}


@pytest.fixture
def base_args(tmp_path: Path) -> list[str]:
    # Real config.yaml, a non-existent .env: no secrets involved.
    return ["--config", str(REPO_ROOT / "config.yaml"), "--env-file", str(tmp_path / "none.env")]


def _run(command: str, base_args: list[str], *extra: str, env: dict[str, str]) -> int:
    return cli.main([command, *base_args, *extra], env=env)


@pytest.fixture
def no_broker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail loudly if anything tries to load secrets during a CLI test."""

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("load_secrets must never be called in M0")

    # Patch the definition AND any name imported into cli, so a future
    # ``from bot.config import load_secrets`` in cli.py is caught too (audit M0 F-7).
    monkeypatch.setattr("bot.config.load_secrets", _boom)
    monkeypatch.setattr("bot.cli.load_secrets", _boom, raising=False)


# --- live double gate -----------------------------------------------------------------


def test_live_without_flag_and_without_env_is_refused(base_args, no_broker, capsys) -> None:
    assert _run("live", base_args, env={}) == cli.EXIT_REFUSED
    assert "--live" in capsys.readouterr().err


def test_live_with_flag_but_without_env_is_refused(base_args, no_broker, capsys) -> None:
    assert _run("live", base_args, "--live", env={}) == cli.EXIT_REFUSED
    assert LIVE_GATE_ENV in capsys.readouterr().err


def test_live_with_env_but_without_flag_is_refused(base_args, no_broker, capsys) -> None:
    assert _run("live", base_args, env=GATE_ON) == cli.EXIT_REFUSED
    assert "--live" in capsys.readouterr().err


@pytest.mark.parametrize("value", ["", "1", "true", "yes", "i_accept_real_orders"])
def test_live_with_wrong_env_value_is_refused(base_args, no_broker, value) -> None:
    assert _run("live", base_args, "--live", env={LIVE_GATE_ENV: value}) == cli.EXIT_REFUSED


def test_live_with_both_gates_still_refuses_in_m0(base_args, no_broker, capsys) -> None:
    code = _run("live", base_args, "--live", env=GATE_ON)
    assert code == cli.EXIT_NOT_IMPLEMENTED
    assert code != cli.EXIT_OK
    assert "not implemented" in capsys.readouterr().err


def test_live_gate_env_var_in_env_file_does_not_open_gate(tmp_path: Path, no_broker) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(f"{LIVE_GATE_ENV}={LIVE_GATE_VALUE}\n", encoding="utf-8")
    args = ["live", "--config", str(REPO_ROOT / "config.yaml"), "--env-file", str(env_file)]
    assert cli.main([*args, "--live"], env={}) == cli.EXIT_REFUSED
    # Even with the shell variable set, a gate value in .env is refused as a config error.
    assert cli.main([*args, "--live"], env=GATE_ON) == cli.EXIT_REFUSED


def test_live_gate_cannot_be_constructed_directly() -> None:
    with pytest.raises(cli.LiveGateRefused):
        cli.LiveGate(object(), "v0_trend")


def test_open_live_gate_requires_flag_and_env() -> None:
    settings = load_settings(REPO_ROOT / "config.yaml", REPO_ROOT / "no-such.env")
    with pytest.raises(cli.LiveGateRefused):
        cli.open_live_gate(False, GATE_ON, "v0_trend", settings)
    with pytest.raises(cli.LiveGateRefused):
        cli.open_live_gate(True, {}, "v0_trend", settings)
    gate = cli.open_live_gate(True, GATE_ON, "v0_trend", settings)
    assert gate.strategy_id == "v0_trend"


# --- plumbing can never run live ------------------------------------------------------


def test_plumbing_in_live_is_refused_even_with_both_gates(base_args, no_broker, capsys) -> None:
    code = _run("live", base_args, "--live", "--strategy", "plumbing", env=GATE_ON)
    assert code == cli.EXIT_REFUSED
    assert "plumbing" in capsys.readouterr().err


def test_open_live_gate_refuses_plumbing() -> None:
    settings = load_settings(REPO_ROOT / "config.yaml", REPO_ROOT / "no-such.env")
    with pytest.raises(cli.LiveGateRefused, match="plumbing"):
        cli.open_live_gate(True, GATE_ON, "plumbing", settings)


def test_plumbing_is_structurally_excluded_from_live() -> None:
    assert "plumbing" not in LIVE_STRATEGIES
    assert "plumbing" in DRY_RUN_STRATEGIES
    assert "live" not in DRY_RUN_STRATEGIES["plumbing"].allowed_modes
    with pytest.raises(StrategyNotAllowed):
        strategy_class_for("plumbing", "live")
    with pytest.raises(TypeError):
        LIVE_STRATEGIES["plumbing"] = DRY_RUN_STRATEGIES["plumbing"]  # type: ignore[index]


def test_every_live_strategy_declares_live_and_slow_timeframe() -> None:
    for sid, strategy_cls in LIVE_STRATEGIES.items():
        assert "live" in strategy_cls.allowed_modes, sid
        assert strategy_cls.timeframe in cli.LIVE_TIMEFRAMES, sid


def test_unknown_strategy_is_refused(base_args, no_broker) -> None:
    assert _run("dry-run", base_args, "--strategy", "nope", env={}) == cli.EXIT_REFUSED


# --- other modes are stubs -------------------------------------------------------------


# M2: ``backtest`` is implemented for v0_trend (tests/backtest/). M3: ``dry-run`` is
# implemented (tests/engine/test_dry_run.py drives it with a fake public exchange; running
# it here would reach the network, which the autouse block forbids). The plumbing strategy
# is a dry-run exercise: its backtest stays not implemented.
@pytest.mark.parametrize(("command", "strategy"), [("backtest", "plumbing")])
def test_backtest_and_dry_run_are_stubs(base_args, no_broker, command, strategy) -> None:
    code = _run(command, base_args, "--strategy", strategy, env={})
    assert code == cli.EXIT_NOT_IMPLEMENTED


def test_invalid_config_is_refused(tmp_path: Path, no_broker) -> None:
    bad = tmp_path / "config.yaml"
    bad.write_text("pairs: []\n", encoding="utf-8")
    code = cli.main(["dry-run", "--config", str(bad), "--env-file", str(tmp_path / "x")], env={})
    assert code == cli.EXIT_REFUSED


def test_live_subcommand_rejects_unknown_flags(base_args) -> None:
    with pytest.raises(SystemExit):
        cli.main(["live", *base_args, "--i-dont-know"], env=GATE_ON)


@pytest.mark.parametrize("abbrev", ["--liv", "--li", "--l"])
def test_live_flag_abbreviations_do_not_open_the_gate(base_args, abbrev) -> None:
    # Audit M0 F-6: only the exact --live flag counts.
    with pytest.raises(SystemExit):
        cli.main(["live", *base_args, abbrev], env=GATE_ON)
