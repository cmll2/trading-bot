"""M1 story 9: 15m candles rebuilt from public trades (``bot data backfill-trades``).

Every I/O matrix row of the plan, through ``FakeExchange.fetch_trades`` (no network).
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import ccxt
import pandas as pd
import pytest

from bot import cli
from bot.clock import FakeClock
from bot.data.cache import data_hash, normalize, read_cache, write_cache
from bot.data.fetch import FetchError
from bot.data.trades import (
    TRADE_COLUMNS,
    TRADE_DTYPES,
    candles_from_trades,
    check_window,
    checkpoint_path,
    fetch_trades_range,
    fetch_trades_range_with_counts,
    fill_interior_buckets,
)
from bot.data.validate import DataValidationError, apply_no_trade_policy, validate_frame
from tests.conftest import REPO_ROOT
from tests.data.fakes import DATA, TICK, FakeExchange, rows

M15 = 900_000
S = datetime(2026, 10, 1, tzinfo=UTC)
S_MS = int(S.timestamp() * 1000)
FIRST_API = S + timedelta(days=2)  # first open_at of the API cache
FIRST_API_MS = int(FIRST_API.timestamp() * 1000)
API_DAYS = 4
E = FIRST_API + timedelta(days=1)  # trades overlap the API rows for one day
NOW = FIRST_API + timedelta(days=API_DAYS, hours=1)
PAGE = 30  # small pages: more than 25 pages before E (checkpoint every 25 pages)
OFFSETS = (1_234, 400_123, 400_500)  # ms into the bucket; the last two share a second


# --- helpers ---------------------------------------------------------------------------------


def trade(tid: int, ts: int, price: float, amount: float = 0.5) -> dict[str, Any]:
    return {"id": str(tid), "timestamp": ts, "price": price, "amount": amount}


def book(n_buckets: int, skip: tuple[int, ...] = ()) -> list[dict[str, Any]]:
    """Three trades per 15m bucket from S (bucket indices in ``skip`` have none)."""
    out: list[dict[str, Any]] = []
    tid = 1000
    for k in range(n_buckets):
        if k in skip:
            continue
        base = 60_000.0 + (k % 37) * 1.5
        for j, off in enumerate(OFFSETS):
            price = base + (-0.7, 0.9, 0.7)[j]
            out.append(trade(tid, S_MS + k * M15 + off, price, 0.01 * (j + 1) + k * 1e-4))
            tid += 1
    return out


def trades_df(trades: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "ts_ms": pd.array([t["timestamp"] for t in trades], dtype="int64"),
            "id": pd.array([int(t["id"]) for t in trades], dtype="int64"),
            "price": pd.array([t["price"] for t in trades], dtype="float64"),
            "amount": pd.array([t["amount"] for t in trades], dtype="float64"),
        }
    )


def in_window(trades: list[dict[str, Any]], start_ms: int, end_ms: int) -> list[dict[str, Any]]:
    return [t for t in trades if start_ms <= t["timestamp"] < end_ms]


N_BUCKETS = (FIRST_API_MS - S_MS) // M15 + API_DAYS * 96
BOOK = book(N_BUCKETS)
E_MS = int(E.timestamp() * 1000)


def api_cache(trades: list[dict[str, Any]] = BOOK) -> pd.DataFrame:
    """15m API rows for [FIRST_API, FIRST_API + API_DAYS), consistent with ``trades``."""
    end_ms = FIRST_API_MS + API_DAYS * 86_400_000
    df = candles_from_trades(trades_df(in_window(trades, FIRST_API_MS, end_ms)), "15m")
    df["trades"] = pd.array([pd.NA] * len(df), dtype="Int64")
    df["source"] = "api"
    return normalize(df)


def make_repo(tmp_path: Path, name: str = "repo") -> Path:
    root = tmp_path / name
    root.mkdir()
    shutil.copy(REPO_ROOT / "config.yaml", root / "config.yaml")
    return root


def cache_file(repo: Path) -> Path:
    return repo / "var" / "data" / "BTC-EUR" / "15m.parquet"


def cp_file(repo: Path, start: datetime = S, end: datetime = E) -> Path:
    return checkpoint_path(repo / "var", "BTC/EUR", pd.Timestamp(start), pd.Timestamp(end))


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(
    repo: Path,
    monkeypatch: pytest.MonkeyPatch,
    exchange: FakeExchange,
    *extra: str,
    start: str = "2026-10-01",
    end: str = E.isoformat(),
    command: str = "backfill-trades",
) -> int:
    monkeypatch.setattr(cli, "_exchange_factory", lambda: exchange)
    monkeypatch.setattr(cli, "_clock_factory", lambda: FakeClock(NOW))
    args = ["data", command, "--timeframe", "15m"]
    if command == "backfill-trades":
        args += ["--start", start, "--end", end]
    args += [*extra, "--config", str(repo / "config.yaml"), "--env-file", str(repo / "none.env")]
    return cli.main(args, env={})


def seeded_repo(tmp_path: Path, name: str = "repo", api: pd.DataFrame | None = None) -> Path:
    repo = make_repo(tmp_path, name)
    write_cache(cache_file(repo), api_cache() if api is None else api)
    return repo


def served() -> FakeExchange:
    return FakeExchange(trades_book=BOOK, trades_page_size=PAGE)


# --- aggregation -----------------------------------------------------------------------------


def test_candles_from_trades_archive_convention() -> None:
    b0, b1 = S_MS, S_MS + 2 * M15  # bucket S+15m has no trade: omitted
    shuffled = [
        trade(7, b0 + 500, 101.0, 0.25),
        trade(5, b0 + 100, 100.0, 1.0),
        trade(6, b0 + 100, 99.0, 0.5),  # same time as id 5: id breaks the tie
        trade(8, b0 + 899_999, 103.0, 2.0),
        trade(9, b0 + 300, 104.0, 0.125),
        trade(10, b1, 200.0, 3.0),
    ]
    df = candles_from_trades(trades_df(shuffled), "15m")
    assert df["open_at"].tolist() == [
        pd.Timestamp(b0, unit="ms", tz="UTC"),
        pd.Timestamp(b1, unit="ms", tz="UTC"),
    ]
    first = df.iloc[0]
    assert (first["open"], first["high"], first["low"], first["close"]) == (
        100.0,
        104.0,
        99.0,
        103.0,
    )
    assert first["volume"] == 3.875 and first["trades"] == 5
    second = df.iloc[1]
    assert (second["open"], second["close"], second["volume"], second["trades"]) == (
        200.0,
        200.0,
        3.0,
        1,
    )
    assert df["source"].tolist() == ["trades", "trades"]
    assert str(df["trades"].dtype) == "Int64"


# --- fetch: pagination, dedupe, backoff ------------------------------------------------------


def _fetch(ex: FakeExchange, tmp_path: Path, clock: FakeClock | None = None, end_ms: int = E_MS):
    return fetch_trades_range(
        ex, "BTC/EUR", S_MS, end_ms, clock or FakeClock(NOW), 5, 2, tmp_path / "cp.parquet"
    )


def test_fetch_pages_dedupes_backs_off_and_stops_at_end(tmp_path: Path) -> None:
    """Happy path: repeated trades between pages, one RateLimitExceeded, one backoff wait."""
    t = [trade(i, S_MS + i * 1000 + 10, 100.0 + i) for i in range(1, 6)]
    before = trade(0, S_MS - 5, 99.0)
    late = trade(6, E_MS, 106.0)
    ex = FakeExchange(
        trades_script=[
            [before, t[0], t[1], t[2]],
            ccxt.RateLimitExceeded("slow"),
            [t[2], t[3], t[4]],
            [t[4], late],
        ]
    )
    clock = FakeClock(NOW)
    out = _fetch(ex, tmp_path, clock)
    assert out["id"].tolist() == [1, 2, 3, 4, 5]
    assert tuple(out.columns) == TRADE_COLUMNS
    assert {c: str(out[c].dtype) for c in TRADE_COLUMNS} == TRADE_DTYPES
    sinces = [c["since"] for c in ex.trade_calls]
    ts3, ts5 = t[2]["timestamp"], t[4]["timestamp"]
    assert sinces == [S_MS, ts3, ts3, ts5]
    assert clock.sleep_calls == [NOW + timedelta(seconds=2)]
    assert all(c["params"] is None for c in ex.trade_calls)  # no ccxt ``paginate``
    kept = pd.read_parquet(tmp_path / "cp.parquet")
    pd.testing.assert_frame_equal(kept, out)  # final checkpoint kept


def test_empty_page_stops_pagination(tmp_path: Path) -> None:
    ex = FakeExchange(trades_script=[[trade(1, S_MS + 10, 100.0)], []])
    assert _fetch(ex, tmp_path)["id"].tolist() == [1]
    assert len(ex.trade_calls) == 2


def test_full_page_of_seen_ids_fails_loudly(tmp_path: Path) -> None:
    """No progress: a full page (len == limit) that brings no new id raises."""
    page = [trade(1, S_MS + 10, 100.0), trade(2, S_MS + 10, 101.0)]  # same ms: cursor stuck
    ex = FakeExchange(trades_script=[page, [dict(t) for t in page]])
    with pytest.raises(FetchError, match="no progress"):
        fetch_trades_range_with_counts(
            ex, "BTC/EUR", S_MS, E_MS, FakeClock(NOW), 5, 2, tmp_path / "cp.parquet", page_limit=2
        )
    assert [c["limit"] for c in ex.trade_calls] == [2, 2]


def test_short_page_of_seen_ids_is_end_of_data(tmp_path: Path) -> None:
    """E == now and no trade after the last one: ccxt returns only the cursor trade again
    (time >= since); the run stops cleanly with every trade."""
    trades = BOOK[:50]
    now = datetime.fromtimestamp((trades[-1]["timestamp"] // M15 + 1) * M15 / 1000, UTC)
    ex = FakeExchange(trades_book=trades, trades_page_size=20)
    out = fetch_trades_range(
        ex, "BTC/EUR", S_MS, int(now.timestamp() * 1000), FakeClock(now), 5, 2, tmp_path / "c"
    )
    assert out["id"].tolist() == [int(t["id"]) for t in trades]
    assert ex.trade_calls[-1]["since"] == trades[-1]["timestamp"]
    assert all(c["limit"] == 1000 for c in ex.trade_calls)


def test_conflicting_id_raises(tmp_path: Path) -> None:
    t1 = trade(1, S_MS + 10, 100.0)
    ex = FakeExchange(trades_script=[[t1], [{**t1, "price": 100.5}, trade(2, S_MS + 20, 1.0)]])
    with pytest.raises(FetchError, match="conflicting fields for trade id 1"):
        _fetch(ex, tmp_path)


@pytest.mark.parametrize("bad_id", [None, "", "abc", "12a", True, 1.5])
def test_missing_or_malformed_id_raises(tmp_path: Path, bad_id: object) -> None:
    raw = {"timestamp": S_MS + 10, "price": 100.0, "amount": 1.0}
    if bad_id is not None:
        raw["id"] = bad_id
    with pytest.raises(FetchError, match="valid id"):
        _fetch(FakeExchange(trades_script=[[raw]]), tmp_path)


@pytest.mark.parametrize(
    "fields",
    [{"price": 0.0}, {"amount": -1.0}, {"price": float("nan")}, {"timestamp": 1.5}],
)
def test_malformed_trade_fields_raise(tmp_path: Path, fields: dict[str, object]) -> None:
    raw = {**trade(1, S_MS + 10, 100.0), **fields}
    with pytest.raises(FetchError):
        _fetch(FakeExchange(trades_script=[[raw]]), tmp_path)


def test_retries_exhausted_raise(tmp_path: Path) -> None:
    ex = FakeExchange(trades_script=[ccxt.RequestTimeout("t")] * 7)
    with pytest.raises(FetchError, match="after 5 retries"):
        _fetch(ex, tmp_path)


# --- checkpoint and resume -------------------------------------------------------------------


def test_resume_from_checkpoint_equals_uninterrupted(tmp_path: Path) -> None:
    trades = BOOK[:700]
    end_ms = trades[600]["timestamp"]  # a trade at end_ms stops pagination; ~32 pages
    whole = _fetch(
        FakeExchange(trades_book=trades, trades_page_size=20), tmp_path / "a", end_ms=end_ms
    )
    assert len(whole) == 600

    cp = tmp_path / "b" / "cp.parquet"
    ex = FakeExchange(trades_book=trades, trades_page_size=20, trades_script=[None] * 26)
    ex.trades_script.append(ccxt.ExchangeError("boom"))  # non-retryable
    with pytest.raises(FetchError, match="boom"):
        fetch_trades_range(ex, "BTC/EUR", S_MS, end_ms, FakeClock(NOW), 5, 2, cp)
    saved = pd.read_parquet(cp)
    assert 0 < len(saved) < 600  # written at page 25, not at the failure

    again = FakeExchange(trades_book=trades, trades_page_size=20)
    out = fetch_trades_range(again, "BTC/EUR", S_MS, end_ms, FakeClock(NOW), 5, 2, cp)
    assert again.trade_calls[0]["since"] == int(saved["ts_ms"].max())
    pd.testing.assert_frame_equal(out, whole)


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda df: pd.concat([df, df.iloc[:1]], ignore_index=True), "duplicate trade ids"),
        (lambda df: df.assign(ts_ms=df["ts_ms"] - 10_000), "outside the window"),
        (lambda df: df.assign(price=df["price"].astype("float32")), "dtype"),
        (lambda df: df.assign(amount=0.0), "non-positive"),
        (lambda df: df.drop(columns=["amount"]), "columns"),
    ],
)
def test_bad_checkpoint_is_refused(tmp_path: Path, mutate, match: str) -> None:
    good = trades_df([trade(1, S_MS + 10, 100.0), trade(2, S_MS + 20, 101.0)])
    cp = tmp_path / "cp.parquet"
    mutate(good).to_parquet(cp, index=False)
    ex = FakeExchange(trades_script=[[trade(3, E_MS, 1.0)]])
    with pytest.raises(FetchError, match=match):
        _fetch(ex, tmp_path)
    assert ex.trade_calls == []  # refused before any request


def test_unreadable_checkpoint_is_refused(tmp_path: Path) -> None:
    (tmp_path / "cp.parquet").write_bytes(b"not parquet")
    with pytest.raises(FetchError, match="unreadable"):
        _fetch(FakeExchange(), tmp_path)


# --- window ----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("start", "end", "match"),
    [
        (S + timedelta(minutes=5), E, "not aligned"),
        (S, E + timedelta(seconds=1), "not aligned"),
        (E, E, "not before"),
        (E, S, "not before"),
        (S, NOW + timedelta(hours=1), "in the future"),
        (S.replace(tzinfo=None), E, "timezone-aware UTC"),
        (S, E.astimezone(ZoneInfo("Europe/Paris")), "timezone-aware UTC"),
    ],
)
def test_bad_window_is_refused(start: datetime, end: datetime, match: str) -> None:
    with pytest.raises(FetchError, match=match):
        check_window(start, end, "15m", NOW)


def test_window_end_equal_to_now_is_accepted() -> None:
    s, e = check_window(S, NOW, "15m", NOW)
    assert (s, e) == (pd.Timestamp(S), pd.Timestamp(NOW))


def test_cli_dates_are_utc() -> None:
    assert cli._utc_instant("2026-10-01") == S
    assert cli._utc_instant("2026-10-01T02:00") == S + timedelta(hours=2)
    assert cli._utc_instant("2026-10-01T02:00+02:00") == S
    with pytest.raises(argparse.ArgumentTypeError):
        cli._utc_instant("yesterday")


# --- end to end through the CLI --------------------------------------------------------------


def test_backfill_fills_window_keeps_api_after_end_and_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, network_attempts
) -> None:
    """AC1 and the overlap-ok row: trades rows for [S, E), overlap checked and kept as
    trades, API rows after E, ``bot data validate`` exits 0."""
    repo = seeded_repo(tmp_path)
    ex = served()
    assert run(repo, monkeypatch, ex) == cli.EXIT_OK, capsys.readouterr().err
    out = capsys.readouterr().out

    df = read_cache(cache_file(repo))
    assert df is not None
    inside = df[df["open_at"] < pd.Timestamp(E)]
    after = df[df["open_at"] >= pd.Timestamp(E)]
    assert set(inside["source"]) == {"trades"} and len(inside) == (E_MS - S_MS) // M15
    assert set(after["source"]) == {"api"} and len(after) == (API_DAYS - 1) * 96
    expected = candles_from_trades(trades_df(in_window(BOOK, S_MS, E_MS)), "15m")
    pd.testing.assert_frame_equal(inside.reset_index(drop=True), expected)
    n_trades = len(in_window(BOOK, S_MS, E_MS))
    assert f"15m: trades fetched={n_trades} (new={n_trades} from_checkpoint=0)" in out
    assert f"candles_built={len(expected)}" in out
    assert "15m: overlap rows_compared=96 max_price_diff_ticks=0 " in out
    assert "'trades': 288" in out
    assert cp_file(repo).exists()  # kept after success
    assert ex.load_markets_calls == 1  # tick from public market metadata

    assert run(repo, monkeypatch, served(), command="validate") == cli.EXIT_OK
    assert network_attempts == []


def test_interrupted_backfill_resumes_and_equals_uninterrupted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """AC2: a non-retryable error after some pages; the rerun resumes from the checkpoint and
    the final cache equals an uninterrupted run."""
    whole = seeded_repo(tmp_path, "whole")
    assert run(whole, monkeypatch, served()) == cli.EXIT_OK
    reference = read_cache(cache_file(whole))
    assert reference is not None

    repo = seeded_repo(tmp_path, "resumed")
    before = sha(cache_file(repo))
    ex = served()
    ex.trades_script = [None] * 27 + [ccxt.ExchangeError("boom")]
    capsys.readouterr()
    assert run(repo, monkeypatch, ex) == cli.EXIT_DATA_ERROR
    assert "DATA ERROR [15m]: trades fetch since" in capsys.readouterr().err
    assert sha(cache_file(repo)) == before  # nothing written to the candle cache
    saved = pd.read_parquet(cp_file(repo))
    n_saved = len(saved)
    assert n_saved > 0

    again = served()
    assert run(repo, monkeypatch, again) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert again.trade_calls[0]["since"] == int(saved["ts_ms"].max())
    n_total = len(in_window(BOOK, S_MS, E_MS))
    assert f"(new={n_total - n_saved} from_checkpoint={n_saved})" in out
    resumed = read_cache(cache_file(repo))
    assert resumed is not None
    assert data_hash(resumed) == data_hash(reference)


def test_interior_empty_bucket_becomes_flat_synthetic_and_validates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    """Empty bucket: filled by the backfill itself (interior of its own window)."""
    trades = book(N_BUCKETS, skip=(10,))
    repo = seeded_repo(tmp_path, api=api_cache(trades))
    ex = FakeExchange(trades_book=trades, trades_page_size=PAGE)
    assert run(repo, monkeypatch, ex) == cli.EXIT_OK, capsys.readouterr().err
    assert "synthetic_filled=1 " in capsys.readouterr().out
    df = read_cache(cache_file(repo))
    assert df is not None
    row = df[df["open_at"] == pd.Timestamp(S_MS + 10 * M15, unit="ms", tz="UTC")].iloc[0]
    prev = df[df["open_at"] == pd.Timestamp(S_MS + 9 * M15, unit="ms", tz="UTC")].iloc[0]
    assert row["source"] == "synthetic" and row["volume"] == 0 and row["trades"] == 0
    assert row["open"] == row["high"] == row["low"] == row["close"] == prev["close"]
    assert run(repo, monkeypatch, served(), command="validate") == cli.EXIT_OK


def test_interior_empty_bucket_under_fail_policy_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    trades = book(N_BUCKETS, skip=(10,))
    repo = seeded_repo(tmp_path, api=api_cache(trades))
    config = repo / "config.yaml"
    text = config.read_text(encoding="utf-8")
    assert "no_trade_policy: fill_flat" in text
    config.write_text(text.replace("no_trade_policy: fill_flat", "no_trade_policy: fail"))
    before = sha(cache_file(repo))
    ex = FakeExchange(trades_book=trades, trades_page_size=PAGE)
    assert run(repo, monkeypatch, ex) == cli.EXIT_DATA_ERROR
    assert "DATA ERROR [15m]: no-trade gap at 2026-10-01 02:30:00+00:00" in capsys.readouterr().err
    assert sha(cache_file(repo)) == before


def _built(buckets: list[int]) -> pd.DataFrame:
    trades = [trade(i, S_MS + k * M15 + 5, 100.0 + k) for i, k in enumerate(buckets, start=1)]
    return candles_from_trades(trades_df(trades), "15m")


def test_fill_interior_buckets_only_between_first_and_last() -> None:
    out = fill_interior_buckets(_built([2, 3, 6]), "15m", "fill_flat")
    offsets = ((out["open_at"].astype("int64") - S_MS) // M15).tolist()
    assert offsets == [2, 3, 4, 5, 6]  # nothing before bucket 2 (window edge)
    assert out["source"].tolist() == ["trades", "trades", "synthetic", "synthetic", "trades"]
    synth = out.iloc[2:4]
    assert (synth[["open", "high", "low", "close"]] == 103.0).all().all()
    assert (synth["volume"] == 0).all() and (synth["trades"] == 0).all()
    assert fill_interior_buckets(_built([1, 2]), "15m", "fill_flat").equals(_built([1, 2]))


def test_fill_interior_buckets_under_fail_raises() -> None:
    with pytest.raises(DataValidationError, match="no-trade gap") as exc:
        fill_interior_buckets(_built([0, 2]), "15m", "fail")
    assert exc.value.open_at == pd.Timestamp(S_MS + M15, unit="ms", tz="UTC")


@pytest.mark.parametrize(
    "sources", [["archive", "trades"], ["trades", "archive"], ["trades", "trades"]]
)
def test_hole_touching_trades_rows_is_a_download_gap(sources: list[str]) -> None:
    """Between archive and trades rows, or two backfill windows: never filled flat."""
    df = rows([0, 2], sources)
    out = apply_no_trade_policy(df, "1d", "fill_flat")
    assert len(out) == 2
    with pytest.raises(DataValidationError, match="download gap"):
        validate_frame(out, "1d", DATA)


def test_synthetic_run_between_trades_and_archive_rows_is_valid() -> None:
    df = rows([0, 1, 2], ["trades", "trades", "archive"])
    df.loc[1, ["open", "high", "low", "close"]] = df.loc[0, "close"]
    df.loc[1, ["volume", "trades", "source"]] = [0.0, 0, "synthetic"]
    loose = DATA.model_copy(update={"max_synthetic_ratio": Decimal("0.9")})
    assert validate_frame(df, "1d", loose).synthetic_rows == 1


def test_backfill_without_cache_writes_trades_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = make_repo(tmp_path)
    assert run(repo, monkeypatch, served()) == cli.EXIT_OK
    df = read_cache(cache_file(repo))
    assert df is not None and set(df["source"]) == {"trades"}


def test_overlap_mismatch_exits_4_and_keeps_cache_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    api = api_cache()
    api.loc[0, "close"] = api.loc[0, "close"] - 2 * TICK  # still within [low, high]
    repo = seeded_repo(tmp_path, api=api)
    before = sha(cache_file(repo))
    assert run(repo, monkeypatch, served()) == cli.EXIT_DATA_ERROR
    err = capsys.readouterr().err
    assert "DATA ERROR [15m]: overlap mismatch on close" in err
    assert str(FIRST_API.date()) in err
    assert sha(cache_file(repo)) == before


def test_trades_ending_before_api_rows_is_a_download_gap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    repo = seeded_repo(tmp_path)
    before = sha(cache_file(repo))
    end = (FIRST_API - timedelta(hours=1)).isoformat()
    assert run(repo, monkeypatch, served(), end=end) == cli.EXIT_DATA_ERROR
    assert "DATA ERROR [15m]: download gap" in capsys.readouterr().err
    assert sha(cache_file(repo)) == before


@pytest.mark.parametrize(
    "error_page",
    [
        [trade(1, S_MS + 10, 100.0), trade(1, S_MS + 10, 100.5)],  # conflicting id
        [{"timestamp": S_MS + 10, "price": 100.0, "amount": 1.0}],  # missing id
    ],
)
def test_defective_trades_exit_4_and_write_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, error_page
) -> None:
    repo = seeded_repo(tmp_path)
    before = sha(cache_file(repo))
    ex = FakeExchange(trades_script=[error_page])
    assert run(repo, monkeypatch, ex) == cli.EXIT_DATA_ERROR
    assert "DATA ERROR [15m]: " in capsys.readouterr().err
    assert sha(cache_file(repo)) == before


def test_no_progress_exits_4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo = seeded_repo(tmp_path)
    page = [trade(i, S_MS + 10, 100.0) for i in range(1, 1001)]  # a full page, one ms
    ex = FakeExchange(trades_script=[page, [dict(t) for t in page]])
    assert run(repo, monkeypatch, ex) == cli.EXIT_DATA_ERROR
    assert "no progress" in capsys.readouterr().err


def test_bad_checkpoint_exits_4(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    repo = seeded_repo(tmp_path)
    cp = cp_file(repo)
    cp.parent.mkdir(parents=True)
    dup = trades_df([trade(1, S_MS + 10, 100.0), trade(1, S_MS + 20, 100.0)])
    dup.to_parquet(cp, index=False)
    assert run(repo, monkeypatch, served()) == cli.EXIT_DATA_ERROR
    assert "bad trades checkpoint" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("start", "end"),
    [
        ("2026-10-01T00:05", E.isoformat()),
        (E.isoformat(), "2026-10-01"),
        ("2026-10-01", (NOW + timedelta(days=1)).isoformat()),
    ],
)
def test_bad_window_exits_4(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys, start: str, end: str
) -> None:
    repo = make_repo(tmp_path)
    ex = served()
    assert run(repo, monkeypatch, ex, start=start, end=end) == cli.EXIT_DATA_ERROR
    assert "DATA ERROR [15m]: " in capsys.readouterr().err
    assert ex.trade_calls == [] and not cache_file(repo).exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["--start", "nope", "--end", "2026-10-02"],
        ["--start", "2026-10-01"],  # --end missing
        ["--start", "2026-10-01", "--end", "2026-10-02", "--timeframe", "1w"],  # bad choice
    ],
)
def test_backfill_argument_errors_exit_2(tmp_path: Path, argv: list[str]) -> None:
    repo = make_repo(tmp_path)
    base = ["data", "backfill-trades", "--timeframe", "15m", *argv]
    base += ["--config", str(repo / "config.yaml")]
    with pytest.raises(SystemExit) as exc:
        cli.main(base, env={})
    assert exc.value.code == 2
