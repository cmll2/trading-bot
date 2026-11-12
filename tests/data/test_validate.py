"""bot.data.validate: OHLC/source checks, gap classification, no-trade policy, synthetic cap
(FR-03, AD-18). One test per I/O matrix row; validation never repairs."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pandas as pd
import pytest

from bot.data.validate import (
    DataValidationError,
    apply_no_trade_policy,
    classify_missing,
    validate_frame,
)
from tests.data.fakes import DATA, DAY_MS, START_MS, frame, rows

FAIL = DATA.model_copy(update={"no_trade_policy": "fail"})


def ts(i: int) -> pd.Timestamp:
    return pd.Timestamp(START_MS + i * DAY_MS, unit="ms", tz="UTC")


def _defect(df: pd.DataFrame, settings=DATA, tf: str = "1d") -> DataValidationError:
    snapshot = df.copy()
    with pytest.raises(DataValidationError) as info:
        validate_frame(df, tf, settings)
    pd.testing.assert_frame_equal(df, snapshot)  # read-only even on failure
    return info.value


# --- structural defects keep their names and timestamps --------------------------------


def test_duplicate_named_with_open_at() -> None:
    err = _defect(rows([0, 1, 1, 2], ["archive"] * 4))
    assert err.defect == "duplicate open_at" and err.open_at == ts(1)


def test_non_monotonic_named_with_open_at() -> None:
    err = _defect(rows([0, 2, 1], ["archive"] * 3))
    assert err.defect == "open_at not strictly increasing" and err.open_at == ts(1)


def test_misaligned_named_with_open_at() -> None:
    df = rows([0, 1], ["api", "api"])
    df["open_at"] = (df["open_at"] + pd.Timedelta(hours=1)).dt.as_unit("ms")
    err = _defect(df)
    assert "not aligned" in err.defect and err.open_at == ts(0) + pd.Timedelta(hours=1)


def test_naive_and_non_utc_refused() -> None:
    df = rows([0, 1], ["api", "api"])
    assert (
        "timezone-aware UTC"
        in _defect(df.assign(open_at=df["open_at"].dt.tz_localize(None))).defect
    )
    assert (
        "open_at dtype"
        in _defect(df.assign(open_at=df["open_at"].dt.tz_convert("Asia/Tokyo"))).defect
    )


# --- OHLC consistency -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("col", "value"),
    [
        ("high", 50.0),  # high < low
        ("high", 101.2),  # high < close (open 101, close 101.5)
        ("low", 101.2),  # low > open
        ("open", 0.0),
        ("close", -1.0),
        ("high", float("inf")),
        ("low", float("-inf")),
    ],
)
def test_inconsistent_ohlc(col: str, value: float) -> None:
    df = rows([0, 1, 2], ["api"] * 3)
    df.loc[1, col] = value
    err = _defect(df)
    assert err.defect == "inconsistent OHLC" and err.open_at == ts(1)


@pytest.mark.parametrize("value", [-0.5, float("inf")])
def test_negative_volume(value: float) -> None:
    df = rows([0, 1, 2], ["api"] * 3)
    df.loc[2, "volume"] = value
    err = _defect(df)
    assert err.defect == "non-finite or negative volume" and err.open_at == ts(2)


def test_negative_trades() -> None:
    df = rows([0, 1, 2], ["archive"] * 3)
    df.loc[1, "trades"] = -1
    err = _defect(df)
    assert err.defect == "negative trades" and err.open_at == ts(1)


def test_unknown_source() -> None:
    df = rows([0, 1, 2], ["archive", "foo", "archive"])
    err = _defect(df)
    assert "unknown source" in err.defect and err.open_at == ts(1)


# --- gap classification and the writer-side policy -------------------------------------


def test_classify_missing() -> None:
    df = rows([0, 3, 4, 6, 8], ["archive", "archive", "api", "api", "archive"])
    assert classify_missing(df, "1d") == [
        (ts(1), "no_trade"),
        (ts(2), "no_trade"),
        (ts(5), "download"),
        (ts(7), "download"),
    ]


def test_archive_gap_fill_flat_inserts_synthetic_then_validates() -> None:
    df = rows([0, 2], ["archive", "archive"])
    snapshot = df.copy()
    out = apply_no_trade_policy(df, "1d", "fill_flat")
    pd.testing.assert_frame_equal(df, snapshot)  # input untouched
    assert list(out["open_at"]) == [ts(0), ts(1), ts(2)]
    filled = out.iloc[1]
    prev_close = df["close"].iloc[0]
    assert filled["source"] == "synthetic"
    assert filled[["open", "high", "low", "close"]].tolist() == [prev_close] * 4
    assert filled["volume"] == 0 and filled["trades"] == 0
    report = validate_frame(
        out, "1d", DATA.model_copy(update={"max_synthetic_ratio": Decimal("0.5")})
    )
    assert report.synthetic_rows == 1
    assert report.synthetic_by_year == {2024: 1}


def test_fill_flat_fills_multi_interval_holes() -> None:
    df = rows([0, 4], ["archive", "archive"])
    out = apply_no_trade_policy(df, "1d", "fill_flat")
    assert list(out["open_at"]) == [ts(i) for i in range(5)]
    assert list(out["source"]) == ["archive", "synthetic", "synthetic", "synthetic", "archive"]
    assert (out["close"].iloc[1:4] == df["close"].iloc[0]).all()


def test_apply_policy_refuses_unsorted_input() -> None:
    with pytest.raises(DataValidationError, match="not strictly increasing"):
        apply_no_trade_policy(rows([4, 0], ["archive", "archive"]), "1d", "fill_flat")


def test_apply_policy_refuses_wrong_dtypes_before_casting() -> None:
    df = rows([0, 2], ["archive", "archive"])
    df["trades"] = df["trades"].astype("float64")
    with pytest.raises(DataValidationError) as info:
        apply_no_trade_policy(df, "1d", "fill_flat")
    assert "column trades has dtype float64" in info.value.defect


def test_archive_gap_fail_policy_raises_no_trade_gap() -> None:
    with pytest.raises(DataValidationError) as info:
        apply_no_trade_policy(rows([0, 2], ["archive", "archive"]), "1d", "fail")
    assert info.value.defect == "no-trade gap" and info.value.open_at == ts(1)


@pytest.mark.parametrize("policy", ["fill_flat", "fail"])
def test_api_gap_is_download_gap_under_both_policies(policy: str) -> None:
    out = apply_no_trade_policy(rows([0, 2], ["api", "api"]), "1d", policy)
    assert len(out) == 2  # never filled
    err = _defect(out, DATA if policy == "fill_flat" else FAIL)
    assert err.defect == "download gap" and err.open_at == ts(1)


@pytest.mark.parametrize("sources", [["archive", "api"], ["api", "archive"]])
def test_between_sources_is_download_gap(sources: list[str]) -> None:
    out = apply_no_trade_policy(rows([0, 2], sources), "1d", "fill_flat")
    assert len(out) == 2
    err = _defect(out)
    assert err.defect == "download gap" and err.open_at == ts(1)


def test_apply_policy_refuses_structural_defects() -> None:
    with pytest.raises(DataValidationError, match="duplicate"):
        apply_no_trade_policy(rows([0, 1, 1], ["archive"] * 3), "1d", "fill_flat")
    with pytest.raises(ValueError, match="unknown no_trade_policy"):
        apply_no_trade_policy(rows([0, 1], ["archive"] * 2), "1d", "interpolate")


def test_unfilled_no_trade_gap_in_stored_file_is_a_defect() -> None:
    df = rows([0, 1, 3], ["archive"] * 3)
    err = _defect(df)
    assert err.defect == "no-trade gap not filled" and err.open_at == ts(2)
    assert len(df) == 3  # validation never fills


# --- synthetic rows ---------------------------------------------------------------------


def _with_synthetic() -> pd.DataFrame:
    return apply_no_trade_policy(rows([0, 2], ["archive", "archive"]), "1d", "fill_flat")


@pytest.mark.parametrize(
    ("col", "value"),
    [
        ("volume", 0.1),
        ("open", 999.0),
        ("high", 999.0),
        ("low", 50.0),
        ("close", 101.0),
        ("trades", 3),
    ],
)
def test_bad_synthetic_row(col: str, value: float) -> None:
    df = _with_synthetic()
    df.loc[1, col] = value
    # Keep the OHLC bracket valid so the synthetic check (not check_ohlc) is reached.
    prices = df.loc[1, ["open", "high", "low", "close"]]
    df.loc[1, "high"], df.loc[1, "low"] = prices.max(), prices.min()
    err = _defect(df, DATA.model_copy(update={"max_synthetic_ratio": Decimal("0.9")}))
    assert err.defect == "inconsistent synthetic candle" and err.open_at == ts(1)


def _flat_synthetic(df: pd.DataFrame, idx: list[int]) -> pd.DataFrame:
    """Make rows ``idx`` flat synthetic candles at the close of the row before ``idx[0]``
    (100.0 at the start of the frame), so only the archive-range rule can fail."""
    df = df.copy()
    price = df.loc[idx[0] - 1, "close"] if idx[0] > 0 else 100.0
    for i in idx:
        df.loc[i, ["open", "high", "low", "close", "volume"]] = [price] * 4 + [0.0]
        df.loc[i, "trades"] = 0
        df.loc[i, "source"] = "synthetic"
    return df


@pytest.mark.parametrize(
    ("sources", "idx", "first_bad"),
    [
        (["api", "api", "api"], [1], 1),  # api t, synthetic t+1, api t+2: filled API gap
        (["archive", "api", "api", "api"], [1, 2], 1),  # archive before, api after
        (["api", "api", "api", "archive"], [1, 2], 1),  # api before, archive after
        (["archive"] * 3, [0], 0),  # start of frame
        (["archive"] * 3, [0, 1], 0),  # start-of-frame run
        (["archive"] * 3, [2], 2),  # end of frame
        (["archive"] * 4, [2, 3], 2),  # end-of-frame run
        (["archive", "archive", "archive", "api", "api"], [3], 3),  # touches api after
    ],
)
def test_synthetic_run_outside_archive_range(sources, idx, first_bad) -> None:
    df = _flat_synthetic(rows(list(range(len(sources))), sources), idx)
    err = _defect(df, DATA.model_copy(update={"max_synthetic_ratio": Decimal("0.9")}))
    assert err.defect == "synthetic candle outside archive range"
    assert err.open_at == ts(first_bad)


def test_synthetic_run_between_archive_rows_passes() -> None:
    df = _flat_synthetic(rows(list(range(5)), ["archive"] * 5), [1, 2, 3])
    loose = DATA.model_copy(update={"max_synthetic_ratio": Decimal("0.9")})
    assert validate_frame(df, "1d", loose).synthetic_rows == 3


def test_synthetic_rows_under_fail_policy() -> None:
    err = _defect(_with_synthetic(), FAIL)
    assert err.defect == "synthetic candle under no_trade_policy=fail" and err.open_at == ts(1)


def test_ratio_cap_names_ratio_and_cap() -> None:
    df = _with_synthetic()  # 1 synthetic out of 3 rows, all after history_start
    err = _defect(df)
    assert "synthetic ratio 0.333333" in err.defect
    assert "1/3" in err.defect and "max_synthetic_ratio 0.001" in err.defect
    capped = DATA.model_copy(update={"max_synthetic_ratio": Decimal("0.3")})
    assert "max_synthetic_ratio 0.3" in _defect(df, capped).defect
    at_cap = DATA.model_copy(update={"max_synthetic_ratio": Decimal(1) / Decimal(3)})
    assert validate_frame(df, "1d", at_cap).synthetic_rows == 1  # equal to the cap passes


def test_synthetic_before_history_start_passes_and_is_reported() -> None:
    days = [0, 10, 20, 30]
    archive = rows(days + list(range(31, 41)), ["archive"] * 14)
    out = apply_no_trade_policy(archive, "1d", "fill_flat")
    late = DATA.model_copy(update={"history_start": date(2024, 1, 31)})  # day 30
    report = validate_frame(out, "1d", late)
    assert report.synthetic_rows == 27
    assert report.synthetic_ratio_after_start == 0.0
    assert report.synthetic_by_year == {2024: 27}
    assert report.sources == {"archive": 14, "api": 0, "synthetic": 27, "trades": 0}
    # The same frame fails the cap when history_start covers the synthetic rows.
    assert "synthetic ratio" in _defect(out).defect


def test_report_defaults_without_synthetic_rows() -> None:
    report = validate_frame(frame(3), "1d", DATA)
    assert report.synthetic_rows == 0
    assert report.synthetic_ratio_after_start == 0.0
    assert report.synthetic_by_year == {}
