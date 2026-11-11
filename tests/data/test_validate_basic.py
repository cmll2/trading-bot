"""bot.data.validate: basic checks (FR-03, AD-18). Fail loudly, never repair."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import pytest

from bot.data.validate import CHECKS, DataValidationError, ValidationReport, validate_frame
from tests.data.fakes import DATA, DAY_MS, START, START_MS, frame


def ts(i: int, step: int = DAY_MS) -> pd.Timestamp:
    return pd.Timestamp(START_MS + i * step, unit="ms", tz="UTC")


def with_open_at(df: pd.DataFrame, values: list[int]) -> pd.DataFrame:
    df = df.copy()
    df["open_at"] = pd.to_datetime(values, unit="ms", utc=True).as_unit("ms")
    return df


def _defect(df: pd.DataFrame, tf: str = "1d", **kw) -> DataValidationError:
    with pytest.raises(DataValidationError) as info:
        validate_frame(df, tf, DATA, **kw)
    return info.value


def test_good_frame_reports_range() -> None:
    report = validate_frame(frame(5), "1d", DATA, now=START + timedelta(days=5))
    assert report == ValidationReport(
        tf="1d",
        rows=5,
        first=ts(0),
        last=ts(4),
        sources={"archive": 0, "api": 5, "synthetic": 0},
    )


def test_empty_frame_is_a_defect() -> None:
    err = _defect(frame(0))
    assert err.defect == "empty cache" and err.open_at is None


def test_checks_are_a_simple_ordered_list() -> None:
    names = [c.__name__ for c in CHECKS]
    assert names[0] == "check_columns"
    assert names.index("check_open_at_utc") < names.index("check_no_nulls")
    assert names.index("check_unique") < names.index("check_increasing")
    assert names.index("check_increasing") < names.index("check_aligned")
    assert names[-1] == "check_no_missing_interval"


def test_duplicate() -> None:
    d = START_MS
    err = _defect(with_open_at(frame(4), [d, d + DAY_MS, d + DAY_MS, d + 2 * DAY_MS]))
    assert err.defect == "duplicate open_at" and err.open_at == ts(1)


def test_non_monotonic() -> None:
    d = START_MS
    err = _defect(with_open_at(frame(3), [d, d + 2 * DAY_MS, d + DAY_MS]))
    assert "strictly increasing" in err.defect and err.open_at == ts(1)


def test_misaligned() -> None:
    d = START_MS + 3600 * 1000
    err = _defect(with_open_at(frame(2), [d, d + DAY_MS]))
    assert "aligned" in err.defect and err.open_at == pd.Timestamp(d, unit="ms", tz="UTC")


def test_aligned_4h_is_not_aligned_1d() -> None:
    step = 4 * 3600 * 1000
    good = with_open_at(frame(3), [START_MS + i * step for i in range(3)])
    assert validate_frame(good, "4h", DATA).rows == 3
    assert "aligned" in _defect(good, "1d").defect


def test_missing_interval_names_first_missing_candle() -> None:
    d = START_MS
    err = _defect(with_open_at(frame(4), [d, d + DAY_MS, d + 4 * DAY_MS, d + 5 * DAY_MS]))
    assert err.defect == "download gap" and err.open_at == ts(2)


def test_naive_open_at() -> None:
    df = frame()
    df["open_at"] = df["open_at"].dt.tz_localize(None)
    assert "timezone-aware UTC" in _defect(df).defect


def test_non_utc_timezone() -> None:
    df = frame()
    df["open_at"] = df["open_at"].dt.tz_convert("Europe/Paris")
    assert "open_at dtype" in _defect(df).defect


def test_nanosecond_unit_refused() -> None:
    df = frame()
    df["open_at"] = df["open_at"].dt.as_unit("ns")
    assert "open_at dtype" in _defect(df).defect


@pytest.mark.parametrize(
    "mutate",
    [
        lambda df: df.drop(columns=["trades"]),
        lambda df: df.assign(extra=1),
        lambda df: df[["open_at", "high", "open", "low", "close", "volume", "trades", "source"]],
    ],
    ids=["missing", "extra", "reordered"],
)
def test_wrong_columns(mutate) -> None:
    assert "wrong columns" in _defect(mutate(frame())).defect


def test_wrong_value_dtype() -> None:
    df = frame()
    df["volume"] = df["volume"].astype("float32")
    assert "volume" in _defect(df).defect


def test_null_price() -> None:
    df = frame()
    df.loc[1, "close"] = float("nan")
    err = _defect(df)
    assert err.defect == "null close" and err.open_at == ts(1)


def test_unknown_source() -> None:
    df = frame()
    df.loc[2, "source"] = "guess"
    err = _defect(df)
    assert "unknown source" in err.defect and err.open_at == ts(2)


def test_last_candle_must_be_closed_when_now_given() -> None:
    df = frame(3)
    assert validate_frame(df, "1d", DATA).rows == 3  # no now: not checked
    assert validate_frame(df, "1d", DATA, now=START + timedelta(days=3)).rows == 3
    err = _defect(df, now=START + timedelta(days=2, hours=23))
    assert err.defect == "last candle is not closed" and err.open_at == ts(2)


def test_validation_does_not_mutate_input() -> None:
    d = START_MS
    df = with_open_at(frame(3), [d, d + 2 * DAY_MS, d + DAY_MS])
    snapshot = df.copy()
    _defect(df)
    pd.testing.assert_frame_equal(df, snapshot)


def test_error_message_names_defect_and_timestamp() -> None:
    err = DataValidationError("download gap", ts(2))
    assert str(err) == f"download gap at {ts(2)}"
    assert str(DataValidationError("wrong columns")) == "wrong columns"
