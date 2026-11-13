"""Look-ahead guard (FR-22, AD-4): a planted t+1 leak is caught and no report is written.

The leaky strategy reads candle t+1 through a module-level reference to the frame the
dataset loader returned, exactly the path AD-4 names; v0_trend passes the same guard.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from bot import cli
from bot.backtest import command as command_mod
from bot.backtest import dataset as dataset_mod
from bot.backtest import runner as runner_mod
from bot.backtest.command import default_request, execute
from bot.backtest.lookahead import LookAheadError, check_prefix_invariance
from bot.candles import CandleHistory
from bot.strategy.base import Mode
from tests.backtest.synth import end_date, make_env

# Gentle zig-zag (daily moves < 4%, so no risk halt ends the run): the next close's
# direction is not predictable from the past.
ZIGZAG = [100.0 + ((i * 7) % 5 - 2) * 0.8 + i * 0.05 for i in range(60)]

_LOADED: dict[str, pd.DataFrame] = {}  # module-level reference to "the loaded frame"


class LeakyTomorrow:
    """Plants a t+1 leak: long when TOMORROW's close is higher than today's."""

    id = "leaky_tomorrow"
    timeframe = "1d"
    warmup = 2
    allowed_modes: frozenset[Mode] = frozenset({"backtest"})

    def __init__(self, params: object = None) -> None:
        self.params = params

    def on_candle(self, history: CandleHistory) -> Decimal:
        frame = _LOADED["1d"]
        t = pd.Timestamp(history.last_open_at)
        nxt = frame[frame["open_at"] > t]
        if nxt.empty:
            return Decimal(0)
        return Decimal(1) if float(nxt["close"].iloc[0]) > float(history.close[-1]) else Decimal(0)

    def indicators(self, history: CandleHistory) -> dict[str, float]:
        return {}


@pytest.fixture
def leaky(monkeypatch: pytest.MonkeyPatch) -> None:
    real_load = dataset_mod.load_dataset

    def load_and_stash(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        ds = real_load(*args, **kwargs)
        _LOADED.clear()
        _LOADED.update(ds.frames)
        return ds

    real_build = runner_mod.build

    def build(strategy_id, params, mode):  # noqa: ANN001, ANN202
        if strategy_id == LeakyTomorrow.id:
            return LeakyTomorrow(params)
        return real_build(strategy_id, params, mode)

    monkeypatch.setattr(dataset_mod, "load_dataset", load_and_stash)
    monkeypatch.setattr(runner_mod, "build", build)
    monkeypatch.setattr(command_mod, "build", build)


def test_planted_t_plus_1_leak_raises_and_no_report_is_written(tmp_path, leaky) -> None:
    env = make_env(tmp_path, ZIGZAG, wiggle=0.01)
    req = default_request(env.settings, LeakyTomorrow.id, date(2026, 11, 13))
    req = req.__class__(**{**req.__dict__, "end": end_date(env, len(ZIGZAG))})
    with pytest.raises(LookAheadError, match="look-ahead detected"):
        execute(env.settings, req)
    assert not env.results_dir.exists() or list(env.results_dir.iterdir()) == []


def test_cli_exits_with_the_look_ahead_code_and_writes_nothing(
    tmp_path, leaky, capsys, monkeypatch
) -> None:
    env = make_env(tmp_path, ZIGZAG, wiggle=0.01)
    real = cli.strategy_class_for
    monkeypatch.setattr(
        cli,
        "strategy_class_for",
        lambda sid, mode: LeakyTomorrow if sid == LeakyTomorrow.id else real(sid, mode),
    )
    code = cli.main(
        ["backtest", "--config", str(env.config_path), "--env-file", str(env.env_path),
         "--strategy", LeakyTomorrow.id, "--end", end_date(env, len(ZIGZAG)).isoformat()],
        env={},
    )  # fmt: skip
    assert code == cli.EXIT_LOOKAHEAD
    assert not env.results_dir.exists() or list(env.results_dir.iterdir()) == []
    assert "LOOK-AHEAD GUARD FAILED" in capsys.readouterr().err


def test_guard_reruns_the_whole_pipeline_with_fresh_loads(tmp_path, monkeypatch) -> None:
    env = make_env(tmp_path, ZIGZAG, wiggle=0.01)
    end = end_date(env, len(ZIGZAG))
    calls = []
    real_load = dataset_mod.load_dataset

    def counting(*args, **kwargs):  # noqa: ANN002, ANN003, ANN202
        calls.append(kwargs.get("replace_after"))
        return real_load(*args, **kwargs)

    monkeypatch.setattr(dataset_mod, "load_dataset", counting)
    built = []
    real_build = runner_mod.build

    def counting_build(*a):  # noqa: ANN002, ANN202
        s = real_build(*a)
        built.append(s)
        return s

    monkeypatch.setattr(runner_mod, "build", counting_build)
    ds = dataset_mod.load_dataset(env.settings, env.start, end, ("1d", "15m"))
    base = runner_mod.run_backtest(env.settings, ds, "maker")
    report = check_prefix_invariance(
        env.settings, env.start, end, ("1d", "15m"), base, n_cutpoints=4
    )
    assert len(report.cutpoints) == 4
    # One baseline load, then a walk and its mirror per cutpoint, each a fresh load.
    assert calls[0] is None and len(calls) == 1 + 8 and all(c is not None for c in calls[1:])
    assert len(built) == 1 + 8 and len({id(s) for s in built}) == 9  # a fresh strategy each
    assert report.candles_compared > 0


def test_v0_trend_passes_the_guard_and_the_report_records_it(tmp_path) -> None:
    env = make_env(tmp_path, ZIGZAG, wiggle=0.01)
    req = default_request(env.settings, "v0_trend", date(2026, 11, 13))
    req = req.__class__(**{**req.__dict__, "end": end_date(env, len(ZIGZAG))})
    json_path, _, payload = execute(env.settings, req)
    assert json_path.exists()
    assert payload["lookahead_guard"]["passed"] is True
    assert len(payload["lookahead_guard"]["cutpoints"]) == env.settings.backtest.lookahead_cutpoints


def test_guard_with_a_second_seed_also_catches_the_leak(tmp_path, leaky) -> None:
    env = make_env(tmp_path, ZIGZAG, wiggle=0.01)
    end = end_date(env, len(ZIGZAG))
    ds = dataset_mod.load_dataset(env.settings, env.start, end, ("1d", "15m"))
    base = runner_mod.run_backtest(env.settings, ds, "maker", strategy_id=LeakyTomorrow.id)
    with pytest.raises(LookAheadError):
        check_prefix_invariance(
            env.settings, env.start, end, ("1d", "15m"), base,
            strategy_id=LeakyTomorrow.id, seed=7, n_cutpoints=2,
        )  # fmt: skip


def test_replaced_future_stays_finite_over_a_long_horizon(tmp_path) -> None:
    import numpy as np

    from bot.backtest.dataset import _random_walk_after

    env = make_env(tmp_path, ZIGZAG, wiggle=0.01)
    ds = dataset_mod.load_dataset(env.settings, env.start, end_date(env, len(ZIGZAG)), ("15m",))
    frame = pd.concat([ds.frames["15m"]] * 40, ignore_index=True)  # ~230k rows to replace
    cut = frame["open_at"].iloc[10]
    out = _random_walk_after(frame, "15m", cut.to_pydatetime(), np.random.default_rng(1))
    assert np.isfinite(out[["open", "high", "low", "close"]].to_numpy()).all()
