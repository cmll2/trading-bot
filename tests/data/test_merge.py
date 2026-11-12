"""bot.data.merge: overlap-checked merge of archive, synthetic and API rows (story 4, A-3)."""

from __future__ import annotations

from decimal import Decimal

import numpy as np
import pandas as pd
import pytest

from bot.data.cache import COLUMNS, DTYPES, empty_frame
from bot.data.merge import (
    SOURCE_PRECEDENCE,
    MergeError,
    OverlapStats,
    check_tick,
    merge_candles,
)
from bot.data.validate import DataValidationError, apply_no_trade_policy, validate_frame
from tests.data.fakes import DATA, DAY_MS, START_MS, TICK, rows

TOL_TICKS = 1
TOL_VOL = Decimal("0.01")


def _merge(existing: pd.DataFrame | None, incoming: pd.DataFrame | None, **kw: object):
    return merge_candles(existing, incoming, TICK, TOL_TICKS, TOL_VOL, tf="1d", **kw)


def _days(df: pd.DataFrame) -> list[int]:
    return ((df["open_at"].astype("int64") - START_MS) // DAY_MS).tolist()


def _with(df: pd.DataFrame, day: int, **values: float) -> pd.DataFrame:
    out = df.copy()
    idx = _days(out).index(day)
    for col, v in values.items():
        out.loc[idx, col] = v
    return out


def test_merge_error_is_a_data_validation_error() -> None:
    assert issubclass(MergeError, DataValidationError)
    assert SOURCE_PRECEDENCE == {"archive": 4, "trades": 3, "synthetic": 2, "api": 1}


# --- tolerance -------------------------------------------------------------------------------


def test_within_tolerance_one_tick_and_point_nine_percent_volume_keeps_archive() -> None:
    api = rows([0, 1, 2], ["api"] * 3)
    archive = rows([1, 2, 3], ["archive"] * 3)
    archive = _with(archive, 1, close=api.loc[1, "close"] + TICK, volume=1.25 * 1.009)

    merged, stats = _merge(api, archive)

    assert _days(merged) == [0, 1, 2, 3]
    assert merged["source"].tolist() == ["api", "archive", "archive", "archive"]
    assert merged.loc[1, "close"] == archive.loc[0, "close"]  # archive values, not averaged
    assert merged.loc[1, "trades"] == 7
    assert stats.rows_compared == 2
    assert stats.max_price_diff_ticks == pytest.approx(1.0)
    assert stats.max_volume_diff_fraction == pytest.approx(0.009 / 1.009)


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
@pytest.mark.parametrize("sign", [1, -1])
def test_exactly_one_tick_passes_two_ticks_fail(field: str, sign: int) -> None:
    api = rows([0, 1], ["api"] * 2, base=50_000.0)
    # Widen high/low so a +-2 tick change of any field keeps the candle internally valid.
    api["high"] += 1.0
    api["low"] -= 1.0
    archive = api.copy()
    archive["source"] = "archive"
    archive["trades"] = pd.array([7, 7], dtype="Int64")

    one = _with(archive, 1, **{field: api.loc[1, field] + sign * TICK})
    merged, stats = _merge(api, one)
    assert merged["source"].tolist() == ["archive", "archive"]
    assert stats.max_price_diff_ticks == pytest.approx(1.0)

    two = _with(archive, 1, **{field: api.loc[1, field] + sign * 2 * TICK})
    with pytest.raises(MergeError) as exc:
        _merge(api, two)
    err = exc.value
    assert err.field == field and err.tf == "1d"
    assert err.open_at == pd.Timestamp(START_MS + DAY_MS, unit="ms", tz="UTC")
    msg = str(err)
    assert msg.startswith(f"overlap mismatch on {field}")
    assert repr(float(api.loc[1, field])) in msg and repr(float(two.loc[1, field])) in msg
    assert "1 tick(s) x 0.1" in msg and "2024-01-02" in msg


@pytest.mark.parametrize("field", ["open", "high", "low", "close"])
def test_tick_epsilon_does_not_grow_with_price(field: str) -> None:
    """At 1e8 a price-relative epsilon (1e-9 x price = 0.1) would let 2 ticks pass."""
    api = rows([0], ["api"], base=1e8)
    api["high"] += 1.0
    api["low"] -= 1.0
    archive = api.copy()
    archive["source"] = "archive"
    _, stats = _merge(api, _with(archive, 0, **{field: api.loc[0, field] + TICK}))
    assert stats.max_price_diff_ticks == pytest.approx(1.0, rel=1e-6)
    with pytest.raises(MergeError) as exc:
        _merge(api, _with(archive, 0, **{field: api.loc[0, field] + 2 * TICK}))
    assert exc.value.field == field


def test_merge_errors_carry_tf_without_repeating_it_in_the_message() -> None:
    with pytest.raises(MergeError) as exc:
        _merge(rows([0], ["api"]).drop(columns=["volume"]), None)
    assert exc.value.tf == "1d" and not str(exc.value).startswith("1d")


def test_price_two_ticks_off_on_close_names_close_and_both_values() -> None:
    api = rows([0, 1], ["api"] * 2)
    archive = _with(rows([0, 1], ["archive"] * 2), 1, close=101.5 + 2 * TICK)
    with pytest.raises(MergeError, match=r"on close: existing 101\.5 \(api\) vs incoming 101\.7"):
        _merge(api, archive)


def test_volume_one_and_a_half_percent_off_fails_naming_volume() -> None:
    api = rows([0, 1], ["api"] * 2)
    archive = _with(rows([0, 1], ["archive"] * 2), 0, volume=1.25 * 1.015)
    with pytest.raises(MergeError, match="on volume") as exc:
        _merge(api, archive)
    assert exc.value.field == "volume"
    assert "0.01 of the larger volume" in str(exc.value)


def test_volume_tolerance_is_relative_to_the_larger_volume() -> None:
    # 1.0 vs 1.0101...: diff / larger = 0.01 exactly -> passes; diff / smaller would fail.
    api = _with(rows([0], ["api"]), 0, volume=1.0)
    archive = _with(rows([0], ["archive"]), 0, volume=1.0 / 0.99)
    _merge(api, archive)


def test_zero_volume_both_sides_agree() -> None:
    api = _with(rows([0], ["api"]), 0, volume=0.0)
    archive = _with(rows([0], ["archive"]), 0, volume=0.0)
    _, stats = _merge(api, archive)
    assert stats.max_volume_diff_fraction == 0.0


def test_trades_are_never_compared() -> None:
    api = rows([0], ["api"])  # trades <NA>
    archive = rows([0], ["archive"])  # trades 7
    archive["trades"] = pd.array([123_456], dtype="Int64")
    merged, _ = _merge(api, archive)
    assert merged["trades"].tolist() == [123_456]


def test_first_mismatch_in_open_at_order_is_reported() -> None:
    api = rows([0, 1, 2], ["api"] * 3)
    archive = rows([0, 1, 2], ["archive"] * 3)
    archive = _with(archive, 2, open=api.loc[2, "open"] + 1.0)
    archive = _with(archive, 1, volume=5.0)
    with pytest.raises(MergeError) as exc:
        _merge(api, archive)
    assert exc.value.field == "volume"
    assert exc.value.open_at == pd.Timestamp(START_MS + DAY_MS, unit="ms", tz="UTC")


# --- precedence ------------------------------------------------------------------------------


def test_existing_api_incoming_archive_keeps_archive() -> None:
    merged, _ = _merge(rows([0, 1], ["api"] * 2), rows([0, 1], ["archive"] * 2))
    assert merged["source"].tolist() == ["archive", "archive"]


def test_existing_archive_incoming_api_keeps_archive() -> None:
    merged, _ = _merge(rows([0, 1], ["archive"] * 2), rows([1, 2], ["api"] * 2))
    assert merged["source"].tolist() == ["archive", "archive", "api"]
    assert merged["trades"].tolist()[:2] == [7, 7]


def _synthetic_between_archive() -> pd.DataFrame:
    """Archive days 0 and 2, day 1 filled flat (synthetic) by the writer's policy."""
    return apply_no_trade_policy(rows([0, 2], ["archive"] * 2), "1d", "fill_flat")


def test_existing_synthetic_incoming_agreeing_api_keeps_synthetic() -> None:
    cached = _synthetic_between_archive()
    synth = cached.iloc[1]
    flat = float(synth["close"])
    api = rows([1, 2, 3], ["api"] * 3)
    api = _with(api, 1, open=flat, high=flat, low=flat, close=flat, volume=0.0)
    api = _with(api, 2, **{c: float(cached.iloc[2][c]) for c in ("open", "high", "low", "close")})

    merged, stats = _merge(cached, api)

    assert merged["source"].tolist() == ["archive", "synthetic", "archive", "api"]
    assert stats.rows_compared == 2
    validate_frame(merged, "1d", DATA.model_copy(update={"max_synthetic_ratio": Decimal("0.5")}))


def test_existing_synthetic_incoming_disagreeing_api_fails() -> None:
    cached = _synthetic_between_archive()
    api = rows([1], ["api"])  # not flat: open differs from the synthetic flat price
    with pytest.raises(MergeError, match=r"\(synthetic\) vs incoming .* \(api\)"):
        _merge(cached, api)


def test_same_source_tie_keeps_existing_row() -> None:
    old = rows([0], ["api"])
    new = _with(rows([0], ["api"]), 0, close=old.loc[0, "close"] + TICK)
    merged, _ = _merge(old, new)
    assert merged.loc[0, "close"] == old.loc[0, "close"]


# --- shape -----------------------------------------------------------------------------------


def test_no_overlap_is_union_sorted_unique_normalized() -> None:
    later = rows([5, 6], ["api"] * 2)
    earlier = rows([0, 1, 2, 3, 4], ["archive"] * 5)
    merged, stats = _merge(later, earlier)
    assert _days(merged) == list(range(7))
    assert merged["open_at"].is_unique and merged["open_at"].is_monotonic_increasing
    assert tuple(merged.columns) == COLUMNS
    assert {c: merged[c].dtype for c in COLUMNS} == DTYPES
    assert list(merged.index) == list(range(7))
    assert stats == OverlapStats(0, 0.0, 0.0)


def test_empty_or_missing_sides() -> None:
    a = rows([0, 1], ["archive"] * 2)
    for existing in (None, empty_frame()):
        merged, stats = _merge(existing, a)
        pd.testing.assert_frame_equal(merged, a)
        assert stats.rows_compared == 0
    merged, _ = _merge(a, None)
    pd.testing.assert_frame_equal(merged, a)
    merged, _ = _merge(None, None)
    assert merged.empty and tuple(merged.columns) == COLUMNS


def test_inputs_are_not_modified() -> None:
    api = rows([0, 1], ["api"] * 2)
    archive = rows([1, 0], ["archive"] * 2)  # unsorted on purpose
    api_copy, archive_copy = api.copy(), archive.copy()
    _merge(api, archive)
    pd.testing.assert_frame_equal(api, api_copy)
    pd.testing.assert_frame_equal(archive, archive_copy)


def test_gap_between_sources_merges_then_validation_reports_download_gap() -> None:
    archive = rows([0, 1, 2], ["archive"] * 3)
    api = rows([4, 5], ["api"] * 2)  # day 3 missing: archive ends t, api starts t + 2i
    merged, _ = _merge(archive, api)
    filled = apply_no_trade_policy(merged, "1d", "fill_flat")  # never fills a download gap
    assert len(filled) == 5
    with pytest.raises(DataValidationError, match="download gap"):
        validate_frame(filled, "1d", DATA)


def test_duplicate_open_at_in_an_input_is_refused() -> None:
    dup = pd.concat([rows([0], ["api"]), rows([0], ["api"])], ignore_index=True)
    with pytest.raises(MergeError, match="duplicate open_at in incoming"):
        _merge(None, dup)
    with pytest.raises(MergeError, match="duplicate open_at in existing"):
        _merge(dup, None)


def test_unknown_source_is_refused() -> None:
    df = rows([0], ["api"])
    df["source"] = pd.array(["csv"], dtype="string")
    with pytest.raises(MergeError, match="unknown source 'csv'"):
        _merge(None, df)


# --- tick and tolerances ---------------------------------------------------------------------


@pytest.mark.parametrize("tick", [0, 0.0, -0.1, float("nan"), float("inf"), None, "0.1", True])
def test_bad_tick_is_refused(tick: object) -> None:
    with pytest.raises(MergeError, match="invalid price tick"):
        check_tick(tick)
    with pytest.raises(MergeError, match="invalid price tick"):
        merge_candles(rows([0], ["api"]), None, tick, TOL_TICKS, TOL_VOL)  # type: ignore[arg-type]


def test_tick_scales_the_tolerance() -> None:
    api = rows([0], ["api"])
    archive = _with(rows([0], ["archive"]), 0, close=api.loc[0, "close"] + 0.4)
    with pytest.raises(MergeError):
        merge_candles(api, archive, 0.1, 1, TOL_VOL)
    _, stats = merge_candles(api, archive, 0.5, 1, TOL_VOL)
    assert stats.max_price_diff_ticks == pytest.approx(0.8)


@pytest.mark.parametrize(("ticks", "vol"), [(-1, "0.01"), (1.5, "0.01"), (1, "-0.1"), (1, "1")])
def test_bad_tolerances_are_refused(ticks: object, vol: str) -> None:
    with pytest.raises(MergeError, match="tolerance"):
        merge_candles(rows([0], ["api"]), None, TICK, ticks, Decimal(vol))  # type: ignore[arg-type]


def test_zero_tolerance_requires_exact_agreement() -> None:
    api = rows([0], ["api"])
    merge_candles(api, rows([0], ["archive"]), TICK, 0, Decimal(0))
    off = _with(rows([0], ["archive"]), 0, close=float(np.nextafter(api.loc[0, "close"], 1e9)))
    merge_candles(api, off, TICK, 0, Decimal(0))  # 1 ulp: within the 1e-9 x price epsilon
    off = _with(rows([0], ["archive"]), 0, close=api.loc[0, "close"] + TICK)
    with pytest.raises(MergeError):
        merge_candles(api, off, TICK, 0, Decimal(0))
