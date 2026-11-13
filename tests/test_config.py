"""Tests for bot.config (brief §5, SAF-01, SAF-02, SAF-05, AD-10, AD-22).

All .env and secrets files here are dummy tmp_path files. No real secrets file is read.
"""

from __future__ import annotations

import os
import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bot.config import (
    ConfigError,
    Settings,
    is_inside,
    load_settings,
)
from tests.conftest import REPO_ROOT


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A fake repository directory holding a copy of the real config.yaml."""
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(REPO_ROOT / "config.yaml", root / "config.yaml")
    return root


def _load(repo: Path, env_text: str | None = None) -> Settings:
    env = repo / ".env"
    if env_text is not None:
        env.write_text(env_text, encoding="utf-8")
    return load_settings(repo / "config.yaml", env, repo_root=repo)


def _edit_config(repo: Path, **changes: object) -> None:
    path = repo / "config.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    for dotted, value in changes.items():
        node = data
        *parents, leaf = dotted.split("__")
        for key in parents:
            node = node[key]
        if value is None:
            del node[leaf]
        else:
            node[leaf] = value
    path.write_text(yaml.safe_dump(data), encoding="utf-8")


def test_repo_config_loads_with_expected_values() -> None:
    s = load_settings(REPO_ROOT / "config.yaml", REPO_ROOT / "no-such.env")
    assert s.pairs == ("BTC/EUR",)
    assert s.strategy.timeframe == "1d"
    assert s.execution.window_hours == 6
    assert s.execution.reprice_interval_minutes == 30
    assert s.risk.max_submissions_per_intent == 12  # moved to protected risk:
    assert str(s.backtest.holdout_start) == "2025-11-11"
    assert str(s.backtest.holdout_end) == "2026-11-10"
    assert s.review.gl02_max_fill_price_diff_fraction == Decimal("0.005")
    assert s.review.gl02_max_equity_diff_pp == Decimal("2")
    assert s.fiat_currencies == ("EUR",)
    assert s.secrets_file is None


def test_paths_are_resolved_to_absolute(repo: Path) -> None:
    s = _load(repo)
    assert s.risk.kill_switch_path.is_absolute()
    assert s.risk.kill_switch_path == (repo / "var" / "KILL").resolve()
    assert s.paths.var_dir == (repo / "var").resolve()


def test_config_has_no_hardcoded_minimums_or_fees() -> None:
    text = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8").lower()
    for word in ("amount_min", "cost_min", "tick_size", "min_order"):
        assert word not in text, word
    # Fee rates live ONLY in the `fees:` section (coordinator decision 2026-11-13: published
    # entry tier, verified against fetch_trading_fee at live startup); nowhere else.
    raw = yaml.safe_load(text)
    outside = {k: v for k, v in raw.items() if k != "fees"}
    assert "maker" not in yaml.safe_dump(outside) and "taker" not in yaml.safe_dump(outside)


def test_fees_are_kraken_published_entry_tier_with_source_label() -> None:
    s = load_settings(REPO_ROOT / "config.yaml", REPO_ROOT / "no-such.env")
    assert s.fees.maker == Decimal("0.0040")
    assert s.fees.taker == Decimal("0.0080")
    assert s.fees.source == "published_schedule"
    assert s.strategy.params == {"sma_days": 200}


def test_settings_are_frozen(repo: Path) -> None:
    s = _load(repo)
    with pytest.raises(ValidationError):
        s.risk = s.risk  # type: ignore[misc]
    with pytest.raises(ValidationError):
        s.risk.max_position_abs_quote = Decimal("1000")  # type: ignore[misc]
    with pytest.raises(ValidationError):
        s.execution.window_hours = 24  # type: ignore[misc]


def test_missing_env_file_is_fine(repo: Path) -> None:
    assert _load(repo).secrets_file is None


def test_empty_values_like_env_example_are_fine(repo: Path) -> None:
    example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert _load(repo, example).secrets_file is None


def test_secrets_path_outside_repo_is_accepted(repo: Path, tmp_path: Path) -> None:
    outside = tmp_path / "elsewhere" / "kraken.env"
    s = _load(repo, f"TRADING_BOT_SECRETS_FILE={outside}\n")
    assert s.secrets_file == outside


def test_secrets_file_is_not_read_at_load(repo: Path, tmp_path: Path) -> None:
    # The path does not even exist: loading must not try to open it.
    outside = tmp_path / "does-not-exist" / "kraken.env"
    assert _load(repo, f"TRADING_BOT_SECRETS_FILE={outside}\n").secrets_file == outside


@pytest.mark.parametrize(
    "relpath",
    ["kraken.env", "sub/dir/kraken.env", "sub/../kraken.env"],
)
def test_secrets_path_inside_repo_is_refused(repo: Path, relpath: str) -> None:
    inside = repo / relpath
    with pytest.raises(ConfigError, match="inside the repository"):
        _load(repo, f"TRADING_BOT_SECRETS_FILE={inside}\n")


def test_secrets_path_equal_to_repo_is_refused(repo: Path) -> None:
    with pytest.raises(ConfigError, match="inside the repository"):
        _load(repo, f"TRADING_BOT_SECRETS_FILE={repo}\n")


def test_secrets_path_escaping_with_dotdot_then_back_in_is_refused(repo: Path) -> None:
    sneaky = repo / ".." / repo.name / "kraken.env"
    with pytest.raises(ConfigError, match="inside the repository"):
        _load(repo, f"TRADING_BOT_SECRETS_FILE={sneaky}\n")


def test_relative_secrets_path_is_refused(repo: Path) -> None:
    with pytest.raises(ConfigError, match="absolute"):
        _load(repo, "TRADING_BOT_SECRETS_FILE=../kraken.env\n")


def test_sibling_dir_with_repo_name_prefix_is_outside(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    assert not is_inside(tmp_path / "repo-secrets" / "k.env", repo)
    assert is_inside(repo / "k.env", repo)


def test_real_repo_root_is_the_default_guard() -> None:
    from bot.config import REPO_ROOT as CONFIG_REPO_ROOT

    assert CONFIG_REPO_ROOT == REPO_ROOT
    assert is_inside(REPO_ROOT / "secrets" / "k.env", CONFIG_REPO_ROOT)


def test_unknown_env_key_is_refused_without_echoing_value(repo: Path) -> None:
    with pytest.raises(ConfigError) as info:
        _load(repo, "KRAKEN_API_KEY=dummy-not-a-real-key-123\n")
    assert "KRAKEN_API_KEY" in str(info.value)
    assert "dummy-not-a-real-key-123" not in str(info.value)


def test_live_gate_in_env_file_is_refused(repo: Path) -> None:
    with pytest.raises(ConfigError, match="must not be set in .env"):
        _load(repo, "TRADING_BOT_LIVE=I_ACCEPT_REAL_ORDERS\n")


def test_env_file_values_are_not_injected_into_os_environ(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("TRADING_BOT_SECRETS_FILE", raising=False)
    _load(repo, f"TRADING_BOT_SECRETS_FILE={tmp_path / 'x.env'}\n")

    assert "TRADING_BOT_SECRETS_FILE" not in os.environ


def test_secrets_file_cannot_be_set_in_config_yaml(repo: Path, tmp_path: Path) -> None:
    _edit_config(repo, secrets_file=str(tmp_path / "k.env"))
    with pytest.raises(ConfigError, match="secrets_file"):
        _load(repo)


def test_exactly_one_pair_required(repo: Path) -> None:
    _edit_config(repo, pairs=["BTC/EUR", "ETH/EUR"])
    with pytest.raises(ConfigError, match="exactly one pair"):
        _load(repo)


def test_unknown_top_level_key_is_refused(repo: Path) -> None:
    _edit_config(repo, leverage=5)
    with pytest.raises(ConfigError):
        _load(repo)


def test_missing_risk_section_is_refused(repo: Path) -> None:
    _edit_config(repo, risk=None)
    with pytest.raises(ConfigError):
        _load(repo)


def test_window_longer_than_timeframe_is_refused(repo: Path) -> None:
    _edit_config(repo, strategy__timeframe="4h", execution__window_hours=6)
    with pytest.raises(ConfigError, match="window"):
        _load(repo)


def test_per_intent_cap_above_daily_cap_is_refused(repo: Path) -> None:
    daily = yaml.safe_load((repo / "config.yaml").read_text(encoding="utf-8"))["risk"][
        "max_exchange_submissions_per_day"
    ]
    _edit_config(repo, risk__max_submissions_per_intent=daily + 1)
    with pytest.raises(ConfigError, match="max_submissions_per_intent"):
        _load(repo)


def test_per_intent_cap_is_refused_in_unprotected_execution_section(repo: Path) -> None:
    # The cap is protected (risk:); it must not be settable from execution:.
    _edit_config(repo, execution__max_submissions_per_intent=12)
    with pytest.raises(ConfigError):
        _load(repo)


def test_holdout_must_be_ordered(repo: Path) -> None:
    _edit_config(repo, backtest__holdout_end="2025-01-01")
    with pytest.raises(ConfigError, match="holdout"):
        _load(repo)


def test_repo_config_no_trade_policy_settings() -> None:
    from datetime import date

    s = load_settings(REPO_ROOT / "config.yaml", REPO_ROOT / "no-such.env")
    assert s.data.history_start == date(2017, 1, 1)
    assert s.data.no_trade_policy == "fill_flat"
    assert s.data.max_synthetic_ratio == Decimal("0.001")


@pytest.mark.parametrize("policy", ["interpolate", "forward_fill", "", "FILL_FLAT"])
def test_bad_no_trade_policy_is_refused(repo: Path, policy: str) -> None:
    _edit_config(repo, data__no_trade_policy=policy)
    with pytest.raises(ConfigError, match="no_trade_policy"):
        _load(repo)


@pytest.mark.parametrize("key", ["history_start", "no_trade_policy", "max_synthetic_ratio"])
def test_no_trade_settings_are_required(repo: Path, key: str) -> None:
    _edit_config(repo, **{f"data__{key}": None})
    with pytest.raises(ConfigError, match=key):
        _load(repo)


@pytest.mark.parametrize("start", ["2025-11-11", "2026-01-01"])
def test_history_start_on_or_after_holdout_is_refused(repo: Path, start: str) -> None:
    _edit_config(repo, data__history_start=start)
    with pytest.raises(ConfigError, match="history_start"):
        _load(repo)


@pytest.mark.parametrize("ratio", ["-0.1", "1", "1.5", "NaN", "Infinity"])
def test_bad_max_synthetic_ratio_is_refused(repo: Path, ratio: str) -> None:
    _edit_config(repo, data__max_synthetic_ratio=ratio)
    with pytest.raises(ConfigError, match="max_synthetic_ratio"):
        _load(repo)


def test_zero_max_synthetic_ratio_is_accepted(repo: Path) -> None:
    _edit_config(repo, data__max_synthetic_ratio="0")
    assert _load(repo).data.max_synthetic_ratio == Decimal(0)


def test_no_trade_settings_are_above_protected_block() -> None:
    text = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    protected = text.index("# PROTECTED")
    for key in ("history_start:", "no_trade_policy:", "max_synthetic_ratio:"):
        assert text.index(key) < protected
