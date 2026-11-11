"""The ``data:`` config section (DataSettings)."""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from bot.config import ConfigError, Settings, load_settings
from tests.conftest import REPO_ROOT


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(REPO_ROOT / "config.yaml", root / "config.yaml")
    return root


def _load(repo: Path) -> Settings:
    return load_settings(repo / "config.yaml", repo / "none.env", repo_root=repo)


def _set_data(repo: Path, **changes: object) -> None:
    path = repo / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    for key, value in changes.items():
        if value is None:
            raw["data"].pop(key)
        else:
            raw["data"][key] = value
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")


def test_repo_config_data_section() -> None:
    s = load_settings(REPO_ROOT / "config.yaml", REPO_ROOT / "no-such.env")
    assert s.data.timeframes == ("1d", "4h", "15m")
    assert s.data.fetch_max_retries == 5
    assert s.data.fetch_retry_base_seconds == 2.0
    assert s.data.overlap_price_tolerance_ticks == 1
    assert s.data.overlap_volume_tolerance_fraction == Decimal("0.01")


def test_overlap_tolerances_are_above_protected_block() -> None:
    text = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    protected = text.index("# PROTECTED")
    for key in ("overlap_price_tolerance_ticks:", "overlap_volume_tolerance_fraction:"):
        assert text.index(key) < protected


def test_data_section_is_above_protected_block() -> None:
    text = (REPO_ROOT / "config.yaml").read_text(encoding="utf-8")
    assert text.index("\ndata:") < text.index("# PROTECTED")


def test_missing_data_section_is_refused(repo: Path) -> None:
    path = repo / "config.yaml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    del raw["data"]
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError, match="data"):
        _load(repo)


@pytest.mark.parametrize(
    "changes",
    [
        {"timeframes": ["1h"]},
        {"timeframes": ["5m"]},
        {"timeframes": []},
        {"timeframes": ["1d", "1d"]},
        {"fetch_max_retries": -1},
        {"fetch_max_retries": 2.5},
        {"fetch_max_retries": "3"},
        {"fetch_retry_base_seconds": 0},
        {"fetch_retry_base_seconds": float("inf")},
        {"fetch_retry_base_seconds": float("nan")},
        {"fetch_retry_base_seconds": 301},
        {"fetch_max_retries": None},
        {"overlap_price_tolerance_ticks": -1},
        {"overlap_price_tolerance_ticks": 1.5},
        {"overlap_price_tolerance_ticks": "1"},
        {"overlap_price_tolerance_ticks": True},
        {"overlap_price_tolerance_ticks": None},
        {"overlap_volume_tolerance_fraction": "-0.01"},
        {"overlap_volume_tolerance_fraction": "1"},
        {"overlap_volume_tolerance_fraction": "NaN"},
        {"overlap_volume_tolerance_fraction": None},
        {"unknown_key": 1},
    ],
)
def test_bad_data_settings_are_refused(repo: Path, changes: dict[str, object]) -> None:
    _set_data(repo, **changes)
    with pytest.raises(ConfigError):
        _load(repo)
