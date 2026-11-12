"""Per-timeframe cap on synthetic (no-trade) candles (coordinator decision 2026-11-12).

15m: 0.5%; 1d and 4h keep the default 0.1%. All data here is synthetic test data.
"""

from __future__ import annotations

import shutil
from decimal import Decimal
from pathlib import Path

import pandas as pd
import pytest
import yaml

from bot.config import ConfigError, load_settings
from bot.data.cache import interval_ms, normalize
from bot.data.validate import DataValidationError, apply_no_trade_policy, validate_frame
from tests.conftest import REPO_ROOT
from tests.data.fakes import DATA

CAPPED = DATA.model_copy(update={"max_synthetic_ratio_by_timeframe": {"15m": Decimal("0.005")}})


def _archive_with_holes(tf: str, n: int, holes: int) -> pd.DataFrame:
    """``n`` archive candles from 2024-01-01 with ``holes`` single missing intervals, filled
    flat under ``fill_flat``. Ratio = holes / (n + holes)."""
    step = interval_ms(tf)
    start = int(pd.Timestamp("2024-01-01", tz="UTC").timestamp() * 1000)
    skip = {10 + 3 * k for k in range(holes)}
    ts = [start + i * step for i in range(n + holes) if i not in skip]
    df = normalize(
        pd.DataFrame(
            {
                "open_at": pd.to_datetime(ts, unit="ms", utc=True),
                "open": 100.0,
                "high": 101.0,
                "low": 99.0,
                "close": 100.5,
                "volume": 1.0,
                "trades": pd.array([3] * len(ts), dtype="Int64"),
                "source": "archive",
            }
        )
    )
    return apply_no_trade_policy(df, tf, "fill_flat")


def test_repo_config_sets_15m_cap_only() -> None:
    s = load_settings(REPO_ROOT / "config.yaml", REPO_ROOT / "no-such.env")
    assert s.data.synthetic_cap("15m") == Decimal("0.005")
    assert s.data.synthetic_cap("1d") == Decimal("0.001")
    assert s.data.synthetic_cap("4h") == Decimal("0.001")
    assert s.data.history_start.isoformat() == "2017-01-01"


def test_ratio_between_caps_passes_15m_and_fails_1d_and_4h() -> None:
    # 3 holes in 1000 rows = 0.3%: above 0.1%, below 0.5%.
    report = validate_frame(_archive_with_holes("15m", 997, 3), "15m", CAPPED)
    assert report.synthetic_rows == 3
    for tf in ("1d", "4h"):
        with pytest.raises(DataValidationError, match=r"exceeds max_synthetic_ratio 0\.001"):
            validate_frame(_archive_with_holes(tf, 997, 3), tf, CAPPED)


def test_15m_above_its_own_cap_fails() -> None:
    # 6 holes in 1000 rows = 0.6% > 0.5%.
    with pytest.raises(DataValidationError, match=r"exceeds max_synthetic_ratio 0\.005"):
        validate_frame(_archive_with_holes("15m", 994, 6), "15m", CAPPED)


def test_default_applies_without_override() -> None:
    with pytest.raises(DataValidationError, match=r"0\.001"):
        validate_frame(_archive_with_holes("15m", 997, 3), "15m", DATA)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(REPO_ROOT / "config.yaml", root / "config.yaml")
    return root


@pytest.mark.parametrize(
    "caps",
    [{"15m": "1"}, {"15m": "-0.1"}, {"15m": "NaN"}, {"1h": "0.01"}, {"15m": "abc"}],
)
def test_bad_overrides_refused(repo: Path, caps: dict[str, str]) -> None:
    cfg = repo / "config.yaml"
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    raw["data"]["max_synthetic_ratio_by_timeframe"] = caps
    cfg.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(cfg, repo / "none.env")
