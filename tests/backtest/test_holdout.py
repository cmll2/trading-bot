"""Walk-forward, holdout registry and change limit (story 9; FR-15..FR-17, FR-20, AD-21).

Every holdout run here uses SYNTHETIC data and a temporary results directory with a
synthetic holdout window: the real holdout (2025-11-11 -> 2026-11-10) is never touched.
"""

from __future__ import annotations

import json
import math
from datetime import date

import pytest

from bot import cli
from bot.backtest import command as command_mod
from bot.backtest.command import BacktestRefused, default_request, execute
from bot.backtest.dataset import HoldoutViolation
from bot.backtest.holdout import (
    ChangeRefused,
    check_change,
    check_tuning_range,
    holdout_runs,
    registry_path,
)
from bot.backtest.search import run_search
from bot.config import load_settings
from tests.backtest.synth import make_env
from tests.conftest import REPO_ROOT

N_DAYS = 80
# Gentle oscillation (daily moves < 3%): trades happen and no risk halt ends the run.
CLOSES = [100.0 + 8.0 * math.sin(i / 4) for i in range(N_DAYS)]
HOLDOUT = {"backtest.holdout_start": "2020-02-20", "backtest.holdout_end": "2020-03-10"}


@pytest.fixture
def env(tmp_path, monkeypatch):  # noqa: ANN001, ANN201
    monkeypatch.setattr(command_mod, "git_dirty", lambda: False)
    monkeypatch.setattr(command_mod, "git_commit", lambda: "a" * 40)
    return make_env(
        tmp_path, CLOSES, wiggle=0.005,
        config_edits={**HOLDOUT, "backtest.walk_forward_fold_days": 30},
    )  # fmt: skip


def _req(env, **kw):  # noqa: ANN001, ANN003, ANN202
    req = default_request(env.settings, "v0_trend", date(2026, 11, 13))
    return req.__class__(**{**req.__dict__, **kw})


# --- holdout never tuned on (FR-15) -----------------------------------------------------


def test_real_config_tuning_range_touching_the_holdout_is_refused() -> None:
    settings = load_settings(REPO_ROOT / "config.yaml", REPO_ROOT / "no-such.env")
    with pytest.raises(HoldoutViolation, match="2025-11-11"):
        check_tuning_range(settings, date(2017, 1, 1), date(2025, 11, 12))
    check_tuning_range(settings, date(2017, 1, 1), date(2025, 11, 11))  # end exclusive: ok


def test_search_touching_the_holdout_is_refused(env, tmp_path) -> None:
    with pytest.raises(HoldoutViolation):
        run_search(env.settings, "v0_trend", [{"sma_days": 3}], date(2020, 1, 1),
                   date(2020, 2, 21), tmp_path / "s.json")  # fmt: skip


def test_search_records_the_number_of_configurations_tried(env, tmp_path) -> None:
    out = tmp_path / "search.json"
    payload = run_search(
        env.settings, "v0_trend", [{"sma_days": 3}, {"sma_days": 5}],
        date(2020, 1, 1), date(2020, 2, 20), out,
    )  # fmt: skip
    assert payload["configurations_tried"] == 2
    assert json.loads(out.read_text("utf-8"))["configurations_tried"] == 2


def test_default_backtest_excludes_the_holdout_and_reports_walk_forward(env) -> None:
    _, md, payload = execute(env.settings, _req(env))
    assert payload["data"]["end_exclusive"].startswith("2020-02-20")
    assert payload["holdout"]["status"].startswith("excluded")
    assert payload["holdout"]["runs_recorded"] == 0
    folds = payload["walk_forward"]
    assert folds and all(f["end"] < "2020-02-20" for f in folds)
    assert "Walk-forward folds" in md.read_text("utf-8")
    assert not registry_path(env.settings).exists()


# --- one holdout run, visible (FR-16) ------------------------------------------------


def test_holdout_run_is_recorded_before_it_runs_and_evaluates_only_the_holdout(env) -> None:
    j, md, payload = execute(env.settings, _req(env, holdout=True))
    runs = holdout_runs(env.settings, "v0_trend")
    assert len(runs) == 1
    entry = runs[0]
    assert entry["run_date"] == "2026-11-13" and entry["git_commit"] == "a" * 40
    assert entry["rerun"] is False and len(entry["config_hash"]) == 64
    assert set(entry["data_hashes"]) == {"1d", "15m"}
    assert j.name.endswith("_HOLDOUT.json")
    assert payload["results"]["maker"]["strategy"]["start"] >= "2020-02-20"
    assert payload["holdout"]["status"].startswith("THIS IS THE HOLDOUT RUN")


def test_second_holdout_run_without_rerun_flag_is_refused(env) -> None:
    execute(env.settings, _req(env, holdout=True))
    with pytest.raises(BacktestRefused, match="already has 1 holdout run"):
        execute(env.settings, _req(env, holdout=True))
    assert len(holdout_runs(env.settings, "v0_trend")) == 1


def test_rerun_with_reason_is_recorded_and_banners_later_reports(env) -> None:
    execute(env.settings, _req(env, holdout=True))
    execute(env.settings, _req(env, holdout=True, rerun_reason="data fix after audit"))
    runs = holdout_runs(env.settings, "v0_trend")
    assert [r["rerun"] for r in runs] == [False, True]
    assert runs[1]["reason"] == "data fix after audit"
    _, md, payload = execute(env.settings, _req(env))  # a later ordinary backtest
    assert payload["holdout"]["banner"].startswith("HOLDOUT RE-RUN WARNING")
    lines = md.read_text("utf-8").splitlines()
    assert lines[0].startswith("VERDICT") and "HOLDOUT RE-RUN WARNING" in lines[4]


def test_holdout_run_on_a_dirty_tree_is_refused(env, monkeypatch) -> None:
    monkeypatch.setattr(command_mod, "git_dirty", lambda: True)
    with pytest.raises(BacktestRefused, match="dirty"):
        execute(env.settings, _req(env, holdout=True))
    assert not registry_path(env.settings).exists()


def test_cli_holdout_flag_rules(env, capsys) -> None:
    base = ["backtest", "--config", str(env.config_path), "--env-file", str(env.env_path)]
    assert cli.main([*base, "--rerun-holdout", "--reason", "x"], env={}) == cli.EXIT_REFUSED
    assert cli.main([*base, "--holdout", "--rerun-holdout"], env={}) == cli.EXIT_REFUSED
    assert cli.main([*base, "--holdout", "--end", "2020-03-01"], env={}) == cli.EXIT_REFUSED
    assert not registry_path(env.settings).exists()
    capsys.readouterr()


# --- change discipline (FR-17) ---------------------------------------------------------


def test_change_above_five_is_refused(env) -> None:
    with pytest.raises(BacktestRefused, match="exceeds the limit of 5"):
        execute(env.settings, _req(env, change=6))


def test_change_needs_a_changes_md_entry(tmp_path) -> None:
    log = tmp_path / "changes.md"
    log.write_text("# Strategy change log\n\n## Change 1\nwhat and why\n", encoding="utf-8")
    check_change(0, log)
    check_change(1, log)
    with pytest.raises(ChangeRefused, match="Change 2"):
        check_change(2, log)
    with pytest.raises(ChangeRefused):
        check_change(-1, log)


def test_repo_changes_md_documents_the_rule_and_has_no_change_yet() -> None:
    text = (REPO_ROOT / "changes.md").read_text("utf-8")
    assert "at most five changes per strategy" in text
    with pytest.raises(ChangeRefused):
        check_change(1)


def test_cli_change_six_is_refused(env, capsys) -> None:
    base = ["backtest", "--config", str(env.config_path), "--env-file", str(env.env_path)]
    assert cli.main([*base, "--change", "6"], env={}) == cli.EXIT_REFUSED
    assert "limit of 5" in capsys.readouterr().err
