"""``bot data update`` / ``bot data validate`` end to end, with a fake exchange and clock."""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path

import ccxt
import pandas as pd
import pytest
import yaml

from bot import cli
from bot.clock import FakeClock
from bot.data.cache import COLUMNS, DTYPES, read_cache, write_cache
from bot.data.validate import apply_no_trade_policy
from tests.conftest import REPO_ROOT
from tests.data.fakes import DAY_MS, START, START_MS, FakeExchange, candles, frame, rows


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Copy of the real config.yaml; its relative ``paths.var_dir`` lands in tmp_path."""
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(REPO_ROOT / "config.yaml", root / "config.yaml")
    return root


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Callable[[FakeExchange, FakeClock], None]:
    def _wire(exchange: FakeExchange, clock: FakeClock) -> None:
        monkeypatch.setattr(cli, "_exchange_factory", lambda: exchange)
        monkeypatch.setattr(cli, "_clock_factory", lambda: clock)

    return _wire


def _args(repo: Path, *extra: str) -> list[str]:
    return [*extra, "--config", str(repo / "config.yaml"), "--env-file", str(repo / "none.env")]


def _cache(repo: Path, tf: str = "1d") -> Path:
    return repo / "var" / "data" / "BTC-EUR" / f"{tf}.parquet"


def test_update_two_pages_with_rate_limit(repo, wire, capsys, network_attempts) -> None:
    """AC1: two 720-row pages, one RateLimitExceeded, one backoff wait."""
    page1 = candles(START_MS, 720)
    page2 = candles(START_MS + 720 * DAY_MS, 720)
    ex = FakeExchange([page1, ccxt.RateLimitExceeded("slow"), page2])
    # The clock sits inside the last candle of page 2: it is open and must be dropped.
    clock = FakeClock(START + timedelta(days=1439, hours=6))
    wire(ex, clock)

    code = cli.main(["data", *_args(repo, "update", "--timeframe", "1d")], env={})

    assert code == cli.EXIT_OK, capsys.readouterr().err
    df = read_cache(_cache(repo))
    assert df is not None
    assert tuple(df.columns) == COLUMNS
    assert {c: df[c].dtype for c in COLUMNS} == DTYPES
    assert len(df) == 1439 and df["open_at"].is_unique and df["open_at"].is_monotonic_increasing
    expected = pd.to_datetime([r[0] for r in (page1 + page2)[:1439]], unit="ms", utc=True)
    assert list(df["open_at"]) == list(expected)
    assert len(clock.sleep_calls) == 1
    assert "1d: rows=1439" in capsys.readouterr().out
    assert network_attempts == []


def test_update_again_requests_only_after_last(repo, wire) -> None:
    """AC2: the second run's first call uses since = last open_at + interval."""
    wire(FakeExchange([candles(START_MS, 10)]), FakeClock(START + timedelta(days=10, hours=1)))
    assert cli.main(["data", *_args(repo, "update", "--timeframe", "1d")], env={}) == 0

    ex = FakeExchange([candles(START_MS, 12)])  # overlapping window, as Kraken returns
    wire(ex, FakeClock(START + timedelta(days=12, hours=1)))
    assert cli.main(["data", *_args(repo, "update", "--timeframe", "1d")], env={}) == 0

    last_ms = START_MS + 9 * DAY_MS
    assert ex.calls[0]["since"] == last_ms + DAY_MS
    assert all(c["since"] > last_ms for c in ex.calls)
    df = read_cache(_cache(repo))
    assert df is not None and len(df) == 12 and df["open_at"].is_unique


def test_update_fetch_error_exits_4_and_writes_nothing(repo, wire, capsys) -> None:
    wire(FakeExchange([ccxt.RequestTimeout("t")] * 10), FakeClock(START + timedelta(days=5)))
    code = cli.main(["data", *_args(repo, "update", "--timeframe", "1d")], env={})
    assert code == cli.EXIT_DATA_ERROR == 4
    assert "DATA ERROR [1d]" in capsys.readouterr().err
    assert not _cache(repo).exists()


def test_update_defaults_to_config_timeframes(repo, wire) -> None:
    h4, m15 = 4 * 3600 * 1000, 15 * 60 * 1000
    script = [candles(START_MS, 5), [], candles(START_MS, 5, h4), [], candles(START_MS, 5, m15)]
    ex = FakeExchange(script)
    wire(ex, FakeClock(START + timedelta(days=5)))
    assert cli.main(["data", *_args(repo, "update")], env={}) == cli.EXIT_OK
    assert [c["timeframe"] for c in ex.calls] == ["1d", "1d", "4h", "4h", "15m", "15m"]


def test_update_corrupt_cache_exits_4_and_continues(repo, wire, capsys) -> None:
    path = _cache(repo, "1d")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not parquet")
    ex = FakeExchange([candles(START_MS, 5, 4 * 3600 * 1000)])
    wire(ex, FakeClock(START + timedelta(days=1)))
    args = _args(repo, "update", "--timeframe", "1d", "--timeframe", "4h")
    assert cli.main(["data", *args], env={}) == cli.EXIT_DATA_ERROR
    assert "DATA ERROR [1d]: unreadable cache file" in capsys.readouterr().err
    assert path.read_bytes() == b"not parquet"
    assert _cache(repo, "4h").exists()  # the next timeframe still ran


def test_update_oserror_on_write_is_a_data_error(repo, wire, capsys, monkeypatch) -> None:
    def _locked(*_a: object, **_k: object) -> None:
        raise PermissionError("file is locked")

    monkeypatch.setattr("bot.data.update.write_cache", _locked)
    wire(FakeExchange([candles(START_MS, 5)]), FakeClock(START + timedelta(days=5)))
    code = cli.main(["data", *_args(repo, "update", "--timeframe", "1d")], env={})
    assert code == cli.EXIT_DATA_ERROR
    assert "DATA ERROR [1d]: PermissionError: file is locked" in capsys.readouterr().err


def test_validate_ok_prints_range(repo, wire, capsys) -> None:
    write_cache(_cache(repo), frame(5))
    wire(FakeExchange(), FakeClock(START + timedelta(days=6)))
    assert cli.main(["data", *_args(repo, "validate", "--timeframe", "1d")], env={}) == 0
    out = capsys.readouterr().out
    assert "1d: rows=5" in out
    assert str(pd.Timestamp(START_MS, unit="ms", tz="UTC")) in out
    assert str(pd.Timestamp(START_MS + 4 * DAY_MS, unit="ms", tz="UTC")) in out
    assert "'api': 5" in out


def test_validate_missing_cache(repo, wire, capsys) -> None:
    wire(FakeExchange(), FakeClock(START))
    code = cli.main(["data", *_args(repo, "validate", "--timeframe", "4h")], env={})
    assert code == cli.EXIT_DATA_ERROR
    assert "no cache for 4h" in capsys.readouterr().err


def test_validate_defaults_to_config_timeframes(repo, wire, capsys) -> None:
    wire(FakeExchange(), FakeClock(START))
    assert cli.main(["data", *_args(repo, "validate")], env={}) == cli.EXIT_DATA_ERROR
    err = capsys.readouterr().err
    for tf in ("1d", "4h", "15m"):
        assert f"no cache for {tf}" in err


def test_validate_does_not_build_an_exchange(repo, monkeypatch) -> None:
    def _boom() -> None:
        raise AssertionError("validate must not create an exchange client")

    monkeypatch.setattr(cli, "_exchange_factory", _boom)
    monkeypatch.setattr(cli, "_clock_factory", lambda: FakeClock(START))
    assert cli.main(["data", *_args(repo, "validate")], env={}) == cli.EXIT_DATA_ERROR


def _ts(i: int) -> pd.Timestamp:
    return pd.Timestamp(START_MS + i * DAY_MS, unit="ms", tz="UTC")


def _set_open_at(df: pd.DataFrame, offsets: list[int]) -> pd.DataFrame:
    df = df.copy()
    df["open_at"] = pd.to_datetime([START_MS + o for o in offsets], unit="ms", utc=True)
    df["open_at"] = df["open_at"].dt.as_unit("ms")
    return df


D = DAY_MS
DEFECTS: dict[str, tuple[Callable[[], pd.DataFrame], str, pd.Timestamp | None]] = {
    "duplicate": (lambda: _set_open_at(frame(3), [0, D, D]), "duplicate", _ts(1)),
    "non_monotonic": (
        lambda: _set_open_at(frame(3), [0, 2 * D, D]),
        "not strictly increasing",
        _ts(1),
    ),
    "misaligned": (
        lambda: _set_open_at(frame(2), [3_600_000, D + 3_600_000]),
        "not aligned",
        pd.Timestamp(START_MS + 3_600_000, unit="ms", tz="UTC"),
    ),
    "missing_interval": (
        lambda: _set_open_at(frame(3), [0, D, 3 * D]),
        "download gap",
        _ts(2),
    ),
    "naive": (
        lambda: frame(3).assign(open_at=lambda d: d["open_at"].dt.tz_localize(None)),
        "timezone-aware UTC",
        None,
    ),
    "non_utc": (
        lambda: frame(3).assign(open_at=lambda d: d["open_at"].dt.tz_convert("Asia/Tokyo")),
        "open_at dtype",
        None,
    ),
    "wrong_columns": (lambda: frame(3).drop(columns=["trades"]), "wrong columns", None),
    "null_open_at": (
        lambda: frame(3).assign(open_at=lambda d: d["open_at"].where(d.index != 1)),
        "null open_at",
        None,
    ),
    "empty": (lambda: frame(0), "empty cache", None),
    "open_last_candle": (lambda: frame(30), "last candle is not closed", _ts(29)),
}


@pytest.mark.parametrize("name", list(DEFECTS))
def test_validate_defect_exits_4_names_defect_and_keeps_bytes(repo, wire, capsys, name) -> None:
    """AC3: any validator defect -> exit 4, stderr names defect (+ timestamp), file untouched."""
    build, defect, when = DEFECTS[name]
    path = _cache(repo)
    path.parent.mkdir(parents=True)
    build().to_parquet(path, index=False)  # raw write: the defect must reach the file
    before = path.read_bytes()
    wire(FakeExchange(), FakeClock(START + timedelta(days=29, hours=12)))

    code = cli.main(["data", *_args(repo, "validate", "--timeframe", "1d")], env={})

    err = capsys.readouterr().err
    assert code == cli.EXIT_DATA_ERROR == 4
    assert "DATA ERROR [1d]" in err and defect in err
    if when is not None:
        assert f"at {when}" in err
    assert "NaT" not in err and "at None" not in err
    assert path.read_bytes() == before


def test_validate_unreadable_file(repo, wire, capsys) -> None:
    path = _cache(repo)
    path.parent.mkdir(parents=True)
    path.write_bytes(b"not parquet")
    wire(FakeExchange(), FakeClock(START))
    assert cli.main(["data", *_args(repo, "validate", "--timeframe", "1d")], env={}) == 4
    assert "unreadable cache file" in capsys.readouterr().err
    assert path.read_bytes() == b"not parquet"


@pytest.mark.parametrize("bad", ["1h", "5m", "1D"])
def test_unknown_timeframe_is_rejected_by_argparse(repo, bad) -> None:
    with pytest.raises(SystemExit):
        cli.main(["data", *_args(repo, "update", "--timeframe", bad)], env={})


def test_data_subcommand_rejects_abbreviations(repo) -> None:
    with pytest.raises(SystemExit):
        cli.main(["data", *_args(repo, "update", "--time", "1d")], env={})


def test_data_invalid_config_is_refused(tmp_path: Path, wire) -> None:
    bad = tmp_path / "config.yaml"
    bad.write_text("pairs: []\n", encoding="utf-8")
    wire(FakeExchange(), FakeClock(START))
    args = ["data", "validate", "--config", str(bad), "--env-file", str(tmp_path / "x")]
    assert cli.main(args, env={}) == cli.EXIT_REFUSED


def test_default_factories_are_public_and_real_clock() -> None:
    from bot.clock import SystemClock
    from bot.data.fetch import make_public_exchange

    assert cli._exchange_factory is make_public_exchange
    assert cli._clock_factory is SystemClock


# --- story 2: OHLC, sources, gap classification, no-trade policy, synthetic cap ---------


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _synthetic_at(df: pd.DataFrame, i: int) -> pd.DataFrame:
    """Turn row ``i`` into a correct flat synthetic candle."""
    df = df.copy()
    prev = df.loc[i - 1, "close"]
    df.loc[i, ["open", "high", "low", "close", "volume"]] = [prev, prev, prev, prev, 0.0]
    df.loc[i, "trades"] = 0
    df.loc[i, "source"] = "synthetic"
    return df


def _mutate(df: pd.DataFrame, i: int, **values: object) -> pd.DataFrame:
    df = df.copy()
    for col, value in values.items():
        df.loc[i, col] = value
    return df


ARCH = ["archive"] * 4
STORY2_DEFECTS: dict[str, tuple[Callable[[], pd.DataFrame], str, pd.Timestamp | None]] = {
    "high_below_low": (
        lambda: _mutate(rows([0, 1, 2, 3], ARCH), 1, high=50.0),
        "inconsistent OHLC",
        _ts(1),
    ),
    "low_above_open": (
        lambda: _mutate(rows([0, 1, 2, 3], ARCH), 2, low=102.5),
        "inconsistent OHLC",
        _ts(2),
    ),
    "zero_price": (
        lambda: _mutate(rows([0, 1, 2, 3], ARCH), 1, open=0.0),
        "inconsistent OHLC",
        _ts(1),
    ),
    "nan_price_is_null": (
        lambda: _mutate(rows([0, 1, 2, 3], ARCH), 1, close=float("nan")),
        "null close",
        _ts(1),
    ),
    "inf_price": (
        lambda: _mutate(rows([0, 1, 2, 3], ARCH), 3, high=float("inf")),
        "inconsistent OHLC",
        _ts(3),
    ),
    "negative_volume": (
        lambda: _mutate(rows([0, 1, 2, 3], ARCH), 2, volume=-1.0),
        "negative volume",
        _ts(2),
    ),
    "unknown_source": (
        lambda: _mutate(rows([0, 1, 2, 3], ARCH), 1, source="foo"),
        "unknown source",
        _ts(1),
    ),
    "api_gap": (lambda: rows([0, 1, 3], ["api"] * 3), "download gap", _ts(2)),
    "archive_then_api_gap": (lambda: rows([0, 2], ["archive", "api"]), "download gap", _ts(1)),
    "api_then_archive_gap": (lambda: rows([0, 2], ["api", "archive"]), "download gap", _ts(1)),
    "unfilled_no_trade_gap": (
        lambda: rows([0, 1, 3], ["archive"] * 3),
        "no-trade gap not filled",
        _ts(2),
    ),
    "synthetic_with_volume": (
        lambda: _mutate(_synthetic_at(rows([0, 1, 2], ["archive"] * 3), 1), 1, volume=0.5),
        "inconsistent synthetic candle",
        _ts(1),
    ),
    "synthetic_not_previous_close": (
        lambda: _mutate(
            _synthetic_at(rows([0, 1, 2], ["archive"] * 3), 1),
            1,
            open=100.4,
            high=100.4,
            low=100.4,
            close=100.4,
        ),
        "inconsistent synthetic candle",
        _ts(1),
    ),
    "synthetic_ratio_cap": (
        lambda: _synthetic_at(rows([0, 1, 2], ["archive"] * 3), 1),
        "exceeds max_synthetic_ratio 0.001",
        None,
    ),
}


@pytest.mark.parametrize("name", list(STORY2_DEFECTS))
def test_story2_defect_exits_4_and_keeps_sha256(repo, wire, capsys, name) -> None:
    """Each defect -> exit 4, stderr names it (+ open_at), cache sha256 unchanged."""
    build, defect, when = STORY2_DEFECTS[name]
    path = _cache(repo)
    path.parent.mkdir(parents=True)
    build().to_parquet(path, index=False)  # raw write: the defect must reach the file
    before = _sha256(path)
    wire(FakeExchange(), FakeClock(START + timedelta(days=30)))

    code = cli.main(["data", *_args(repo, "validate", "--timeframe", "1d")], env={})

    err = capsys.readouterr().err
    assert code == cli.EXIT_DATA_ERROR == 4
    assert "DATA ERROR [1d]" in err and defect in err, err
    if when is not None:
        assert f"at {when}" in err
    assert _sha256(path) == before


def test_synthetic_rows_under_fail_policy_exit_4(repo, wire, capsys) -> None:
    cfg = repo / "config.yaml"
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    raw["data"]["no_trade_policy"] = "fail"
    raw["data"]["max_synthetic_ratio"] = "0.5"
    cfg.write_text(yaml.safe_dump(raw), encoding="utf-8")
    path = _cache(repo)
    write_cache(path, _synthetic_at(rows([0, 1, 2], ["archive"] * 3), 1))
    before = _sha256(path)
    wire(FakeExchange(), FakeClock(START + timedelta(days=30)))

    code = cli.main(["data", *_args(repo, "validate", "--timeframe", "1d")], env={})

    err = capsys.readouterr().err
    assert code == 4
    assert f"synthetic candle under no_trade_policy=fail at {_ts(1)}" in err
    assert _sha256(path) == before


def test_archive_gap_filled_by_writer_then_validates(repo, wire, capsys) -> None:
    """AC2: a writer applies fill_flat; the file holds a flat synthetic row; validate exits 0."""
    n = 1500  # one synthetic row in 1500 stays under max_synthetic_ratio 0.001
    days = [d for d in range(n + 1) if d != 700]
    archive = rows(days, ["archive"] * n)
    path = _cache(repo)
    write_cache(path, apply_no_trade_policy(archive, "1d", "fill_flat"))  # the writer's job
    before = _sha256(path)
    wire(FakeExchange(), FakeClock(START + timedelta(days=n + 1)))

    code = cli.main(["data", *_args(repo, "validate", "--timeframe", "1d")], env={})

    out = capsys.readouterr().out
    assert code == cli.EXIT_OK
    df = read_cache(path)
    assert df is not None and len(df) == n + 1
    row = df[df["source"] == "synthetic"]
    assert list(row["open_at"]) == [_ts(700)]
    prev_close = archive.loc[699, "close"]
    assert row[["open", "high", "low", "close"]].iloc[0].tolist() == [prev_close] * 4
    assert row["volume"].iloc[0] == 0 and row["trades"].iloc[0] == 0
    assert "synthetic=1" in out and "synthetic_ratio_from_2017-01-01=0.000666" in out
    assert "synthetic_by_year={2025: 1}" in out
    assert _sha256(path) == before  # validate never rewrites
