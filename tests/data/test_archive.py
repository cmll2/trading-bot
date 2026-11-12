"""``bot data import-archive``: checksum first, exact members, strict CSV, per-tf writes.

Every archive used here is SYNTHETIC (see tests/data/archive_fixtures.py).
"""

from __future__ import annotations

import ast
import hashlib
import io
import re
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import ccxt
import pandas as pd
import pytest
import yaml

from bot import cli
from bot.clock import FakeClock
from bot.config import Settings, load_settings
from bot.data import archive
from bot.data.archive import ArchiveError, find_member, import_archive, member_name
from bot.data.cache import COLUMNS, DTYPES, normalize, read_cache, write_cache
from tests.conftest import REPO_ROOT
from tests.data.archive_fixtures import (
    INTERVAL_S,
    PRE_HISTORY_START_S,
    START_S,
    build_zip,
    decoys,
    kraken_csv,
    sha256_hex,
    standard_members,
    standard_zip,
)
from tests.data.fakes import START_MS, TICK, FakeExchange, candles, rows

NOW = datetime(2026, 11, 11, tzinfo=UTC)
ALL_TFS = ("1d", "4h", "15m")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """Copy of the real config.yaml; its relative ``paths.var_dir`` lands in tmp_path."""
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(REPO_ROOT / "config.yaml", root / "config.yaml")
    return root


@pytest.fixture(autouse=True)
def exchange(monkeypatch: pytest.MonkeyPatch) -> FakeExchange:
    """Story 4: the CLI reads the price tick from (fake) public market metadata."""
    ex = FakeExchange()
    monkeypatch.setattr(cli, "_exchange_factory", lambda: ex)
    return ex


def _tick() -> float:
    return TICK


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    c = FakeClock(NOW)
    monkeypatch.setattr(cli, "_clock_factory", lambda: c)
    return c


def _settings(repo: Path) -> Settings:
    return load_settings(repo / "config.yaml", repo / "none.env")


def _set_data(repo: Path, **values: object) -> None:
    cfg = repo / "config.yaml"
    raw = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    raw["data"].update(values)
    cfg.write_text(yaml.safe_dump(raw), encoding="utf-8")


def _cache(repo: Path, tf: str) -> Path:
    return repo / "var" / "data" / "BTC-EUR" / f"{tf}.parquet"


def _run(repo: Path, cmd: str, *extra: str) -> int:
    return cli.main(
        [
            "data",
            cmd,
            *extra,
            "--config",
            str(repo / "config.yaml"),
            "--env-file",
            str(repo / "none.env"),
        ],
        env={},
    )


def _import(repo: Path, zip_path: Path, sha: str | None = None, *tfs: str) -> int:
    extra = [arg for tf in tfs for arg in ("--timeframe", tf)]
    return _run(repo, "import-archive", "--zip", str(zip_path), "--sha256", sha or "", *extra)


def _no_caches(repo: Path) -> bool:
    return not any(_cache(repo, tf).exists() for tf in ALL_TFS)


# --- checksum ------------------------------------------------------------------------------


def test_wrong_checksum_refused_before_zip_parsing(repo, clock, capsys, monkeypatch) -> None:
    zip_path = standard_zip(repo)

    def _never(*a: object, **k: object) -> None:
        raise AssertionError("zipfile.ZipFile constructed despite checksum mismatch")

    monkeypatch.setattr(zipfile, "ZipFile", _never)
    code = _import(repo, zip_path, "0" * 64)

    assert code == cli.EXIT_DATA_ERROR == 4
    assert "checksum mismatch" in capsys.readouterr().err
    assert _no_caches(repo)


@pytest.mark.parametrize("bad", ["", "abc", "g" * 64, "0" * 63, "0" * 65, " " + "0" * 64])
def test_malformed_sha256_refused_before_hashing(repo, clock, capsys, monkeypatch, bad) -> None:
    zip_path = standard_zip(repo)

    def _never(*a: object) -> str:
        raise AssertionError("archive hashed despite malformed --sha256")

    monkeypatch.setattr(archive, "sha256_file", _never)
    monkeypatch.setattr(archive, "sha256_stream", _never)
    code = cli.main(
        [
            "data",
            "import-archive",
            "--zip",
            str(zip_path),
            f"--sha256={bad}",
            "--config",
            str(repo / "config.yaml"),
            "--env-file",
            str(repo / "none.env"),
        ],
        env={},
    )

    assert code == 4
    assert "malformed --sha256" in capsys.readouterr().err
    assert _no_caches(repo)


def test_sha256_file_streams_whole_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(archive, "HASH_CHUNK_BYTES", 7)
    path = tmp_path / "f.bin"
    path.write_bytes(bytes(range(256)) * 3)
    assert archive.sha256_file(path) == hashlib.sha256(path.read_bytes()).hexdigest()


# --- happy path ----------------------------------------------------------------------------


def test_happy_path_writes_three_caches_and_validates(repo, clock, capsys, monkeypatch) -> None:
    """AC1: 1d/4h/15m written with source=archive from XBTEUR only; validate exits 0."""
    zip_path = standard_zip(repo, n=10)

    def _no_extract(*a: object, **k: object) -> None:
        raise AssertionError("archive members must never be extracted to disk")

    monkeypatch.setattr(zipfile.ZipFile, "extract", _no_extract)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", _no_extract)
    read: list[str] = []
    real_open = zipfile.ZipFile.open

    def _spy_open(self: zipfile.ZipFile, name: object, *a: object, **k: object) -> object:
        read.append(name.filename if isinstance(name, zipfile.ZipInfo) else str(name))
        return real_open(self, name, *a, **k)

    monkeypatch.setattr(zipfile.ZipFile, "open", _spy_open)

    code = _import(repo, zip_path, sha256_hex(zip_path).upper())  # case-insensitive

    out, err = capsys.readouterr()
    assert code == cli.EXIT_OK, err
    assert sorted(read) == ["XBTEUR_1440.csv", "XBTEUR_15.csv", "XBTEUR_240.csv"]
    for tf, minutes in (("1d", 1440), ("4h", 240), ("15m", 15)):
        df = read_cache(_cache(repo, tf))
        assert df is not None and len(df) == 10
        assert tuple(df.columns) == COLUMNS
        assert {c: df[c].dtype for c in COLUMNS} == DTYPES  # UTC ms, Int64 trades
        assert set(df["source"]) == {"archive"}
        step = INTERVAL_S[minutes]
        expected_ts = [(START_S + i * step) * 1000 for i in range(10)]
        assert df["open_at"].astype("int64").tolist() == expected_ts
        assert df["open"].tolist() == [100.0 + minutes + i for i in range(10)]  # not a decoy
        assert df["trades"].tolist() == [10 + i for i in range(10)]
        assert f"{tf}: rows=10 first=" in out

    assert _run(repo, "validate") == cli.EXIT_OK


def test_member_in_subfolder_matched(repo) -> None:
    zip_path = build_zip(
        repo / "a.zip",
        [
            ("Kraken_OHLCVT/XBTEUR_240.csv", kraken_csv(START_S, 4, 14_400)),
            ("Kraken_OHLCVT/AIXBTEUR_240.csv", kraken_csv(START_S, 4, 14_400, base=9000.0)),
        ],
    )
    out = import_archive(
        _settings(repo), zip_path, sha256_hex(zip_path), ["4h"], tick_provider=_tick, now=NOW
    )
    assert len(out["4h"]) == 4
    assert read_cache(_cache(repo, "4h")) is not None


def test_unsorted_member_is_sorted_before_policy(repo) -> None:
    csv = kraken_csv(START_S, 5, 86_400)
    lines = csv.strip().split("\n")
    zip_path = build_zip(repo / "a.zip", [("XBTEUR_1440.csv", "\n".join(lines[::-1]) + "\n")])
    out = import_archive(
        _settings(repo), zip_path, sha256_hex(zip_path), ["1d"], tick_provider=_tick, now=NOW
    )
    assert out["1d"]["open_at"].is_monotonic_increasing


# --- member selection ----------------------------------------------------------------------


def test_member_name_mapping() -> None:
    assert member_name("BTC/EUR", "1d") == "XBTEUR_1440.csv"
    assert member_name("BTC/EUR", "4h") == "XBTEUR_240.csv"
    assert member_name("BTC/EUR", "15m") == "XBTEUR_15.csv"
    with pytest.raises(ArchiveError, match="pair ETH/EUR"):
        member_name("ETH/EUR", "1d")
    with pytest.raises(ArchiveError, match="timeframe 1h"):
        member_name("BTC/EUR", "1h")


def test_decoys_never_match(tmp_path) -> None:
    zip_path = build_zip(tmp_path / "d.zip", decoys())
    with zipfile.ZipFile(zip_path) as zf, pytest.raises(ArchiveError, match="not found"):
        find_member(zf, "XBTEUR_1440.csv")


def test_missing_member_refused_naming_it_earlier_tf_stays(repo, clock, capsys) -> None:
    members = [m for m in standard_members() if m[0] != "XBTEUR_15.csv"]
    zip_path = build_zip(repo / "a.zip", members)

    code = _import(repo, zip_path, sha256_hex(zip_path), "1d", "15m")

    err = capsys.readouterr().err
    assert code == 4
    assert "DATA ERROR [15m]: member XBTEUR_15.csv not found" in err
    assert _cache(repo, "1d").exists()  # all-or-nothing per tf; earlier tfs stay
    assert not _cache(repo, "15m").exists()


@pytest.mark.parametrize(
    "names",
    [
        ["XBTEUR_1440.csv", "XBTEUR_1440.csv"],
        ["XBTEUR_1440.csv", "Kraken_OHLCVT/XBTEUR_1440.csv"],
    ],
)
def test_duplicate_member_refused(repo, names) -> None:
    zip_path = build_zip(repo / "a.zip", [(n, kraken_csv(START_S, 3, 86_400)) for n in names])
    with pytest.raises(ArchiveError, match="appears 2 times") as exc:
        import_archive(
            _settings(repo), zip_path, sha256_hex(zip_path), ["1d"], tick_provider=_tick, now=NOW
        )
    assert exc.value.timeframe == "1d"
    assert not _cache(repo, "1d").exists()


def test_oversize_declared_member_refused(repo, monkeypatch) -> None:
    monkeypatch.setattr(archive, "MAX_MEMBER_BYTES", 50)
    zip_path = build_zip(repo / "a.zip", [("XBTEUR_1440.csv", kraken_csv(START_S, 5, 86_400))])
    with pytest.raises(ArchiveError, match="declares .* above the 50 cap"):
        import_archive(
            _settings(repo), zip_path, sha256_hex(zip_path), ["1d"], tick_provider=_tick, now=NOW
        )
    assert not _cache(repo, "1d").exists()


def test_capped_reader_stops_beyond_cap() -> None:
    reader = io.BufferedReader(archive._CappedReader(io.BytesIO(b"x" * 100), 64, "m.csv"))
    with pytest.raises(ArchiveError, match="decompresses beyond 64 bytes"):
        reader.read()
    ok = io.BufferedReader(archive._CappedReader(io.BytesIO(b"x" * 64), 64, "m.csv"))
    assert ok.read() == b"x" * 64


def test_encrypted_member_refused(repo) -> None:
    zip_path = build_zip(repo / "a.zip", [("XBTEUR_1440.csv", kraken_csv(START_S, 3, 86_400))])
    # stdlib cannot encrypt: set the "encrypted" flag bit in the local and central headers.
    raw = bytearray(zip_path.read_bytes())
    for sig, flag_offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        pos = raw.index(sig)
        raw[pos + flag_offset] |= 0x1
    zip_path.write_bytes(bytes(raw))
    with pytest.raises(ArchiveError, match=r"^member XBTEUR_1440\.csv is encrypted$"):
        import_archive(
            _settings(repo), zip_path, sha256_hex(zip_path), ["1d"], tick_provider=_tick, now=NOW
        )


def test_not_a_zip_refused(repo, clock, capsys) -> None:
    path = repo / "a.zip"
    path.write_bytes(b"not a zip")
    assert _import(repo, path, sha256_hex(path), "1d") == 4
    assert "not a readable ZIP" in capsys.readouterr().err


# --- CSV strictness ------------------------------------------------------------------------

GOOD = f"{START_S},100.0,102.0,99.0,100.5,1.25,10\n"
NEXT = f"{START_S + 86_400},101.0,103.0,100.0,101.5,1.25,11\n"


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("timestamp,open,high,low,close,volume,trades\n" + GOOD + NEXT, id="header"),
        pytest.param(f"{START_S},100.0,102.0,99.0,100.5,1.25\n" * 2, id="six-columns"),
        pytest.param(f"{START_S},100.0,102.0,99.0,100.5,1.25,10,7\n" * 2, id="eight-columns"),
        pytest.param(GOOD + f"{START_S + 86_400},abc,103.0,100.0,101.5,1.25,11\n", id="non-num"),
        pytest.param(f"{START_S * 1000},100.0,102.0,99.0,100.5,1.25,10\n", id="ms-timestamps"),
        pytest.param("1325376000,100.0,102.0,99.0,100.5,1.25,10\n", id="before-2013"),
        pytest.param(f"{START_S}.5,100.0,102.0,99.0,100.5,1.25,10\n", id="fractional-ts"),
        pytest.param(GOOD + f"{START_S + 86_400},,103.0,100.0,101.5,1.25,11\n", id="empty-field"),
        pytest.param(GOOD + f"{START_S + 86_400},inf,inf,100.0,101.5,1.25,11\n", id="inf"),
        pytest.param(GOOD + f"{START_S + 86_400},101.0,103.0,100.0,101.5,1.25,\n", id="no-trades"),
        pytest.param("", id="empty-member"),
        pytest.param(GOOD + NEXT[:-1] + "\xe9\n", id="non-ascii"),
    ],
)
def test_bad_csv_refused_naming_member(repo, clock, capsys, content) -> None:
    zip_path = build_zip(repo / "a.zip", [("XBTEUR_1440.csv", content)])

    code = _import(repo, zip_path, sha256_hex(zip_path), "1d")

    err = capsys.readouterr().err
    assert code == 4
    assert "DATA ERROR [1d]: member XBTEUR_1440.csv" in err, err
    assert not _cache(repo, "1d").exists()


def test_inconsistent_row_refused_by_validation(repo, clock, capsys) -> None:
    bad = f"{START_S + 86_400},101.0,99.0,100.0,101.5,1.25,11\n"  # high < low
    zip_path = build_zip(repo / "a.zip", [("XBTEUR_1440.csv", GOOD + bad)])

    assert _import(repo, zip_path, sha256_hex(zip_path), "1d") == 4
    assert "DATA ERROR [1d]: inconsistent OHLC at 2024-01-02" in capsys.readouterr().err
    assert not _cache(repo, "1d").exists()


def test_duplicate_timestamps_refused(repo) -> None:
    zip_path = build_zip(repo / "a.zip", [("XBTEUR_1440.csv", GOOD + GOOD)])
    with pytest.raises(ArchiveError, match="duplicate open_at"):
        import_archive(
            _settings(repo), zip_path, sha256_hex(zip_path), ["1d"], tick_provider=_tick, now=NOW
        )


# --- no-trade policy -----------------------------------------------------------------------


def _gap_zip(repo: Path) -> Path:
    # 2015 dates: before data.history_start, so one synthetic row stays under the ratio cap.
    csv = kraken_csv(PRE_HISTORY_START_S, 6, 86_400, skip=(3,))
    return build_zip(repo / "gap.zip", [("XBTEUR_1440.csv", csv)])


def test_no_trade_gap_filled_flat_then_validates(repo, clock, capsys) -> None:
    """AC3 (closes story 2's deferred item): the production writer fills, validates, writes."""
    zip_path = _gap_zip(repo)

    assert _import(repo, zip_path, sha256_hex(zip_path), "1d") == cli.EXIT_OK

    df = read_cache(_cache(repo, "1d"))
    assert df is not None and len(df) == 6
    synth = df[df["source"] == "synthetic"]
    gap_ms = (PRE_HISTORY_START_S + 3 * 86_400) * 1000
    assert synth["open_at"].astype("int64").tolist() == [gap_ms]
    prev_close = df.loc[2, "close"]
    assert synth[["open", "high", "low", "close"]].iloc[0].tolist() == [prev_close] * 4
    assert synth["volume"].iloc[0] == 0 and synth["trades"].iloc[0] == 0
    assert "synthetic=1" in capsys.readouterr().out
    assert _run(repo, "validate", "--timeframe", "1d") == cli.EXIT_OK


def test_no_trade_gap_under_fail_policy_exit_4_writes_nothing(repo, clock, capsys) -> None:
    _set_data(repo, no_trade_policy="fail")
    zip_path = _gap_zip(repo)

    code = _import(repo, zip_path, sha256_hex(zip_path), "1d")

    assert code == 4
    assert "DATA ERROR [1d]: no-trade gap at 2015-01-04" in capsys.readouterr().err
    assert not _cache(repo, "1d").exists()


# --- existing cache ------------------------------------------------------------------------


def test_existing_cache_reimport_merges_identically(repo, clock, capsys) -> None:
    """Story 3 refused an existing cache ("merge arrives in story 4"); story 4 replaces the
    refusal by the overlap-checked merge: re-importing the same archive agrees row for row
    and leaves the cached rows unchanged."""
    zip_path = standard_zip(repo)
    path = _cache(repo, "1d")
    existing = import_archive(
        _settings(repo), zip_path, sha256_hex(zip_path), ["1d"], tick_provider=_tick, now=NOW
    )
    before = read_cache(path)

    code = _import(repo, zip_path, sha256_hex(zip_path), "1d")

    out, err = capsys.readouterr()
    assert code == cli.EXIT_OK, err
    pd.testing.assert_frame_equal(read_cache(path), before)
    assert "1d: overlap rows_compared=10 max_price_diff_ticks=0 max_volume_diff_fraction=0" in out
    assert len(existing["1d"]) == 10


def test_existing_empty_cache_is_replaced(repo) -> None:
    zip_path = standard_zip(repo)
    path = _cache(repo, "1d")
    write_cache(path, normalize(pd.DataFrame({c: [] for c in COLUMNS})))
    out = import_archive(
        _settings(repo), zip_path, sha256_hex(zip_path), ["1d"], tick_provider=_tick, now=NOW
    )
    assert len(out["1d"]) == 10
    df = read_cache(path)
    assert df is not None and len(df) == 10


# --- boundaries ----------------------------------------------------------------------------


def test_kraken_pair_code_only_in_archive_module() -> None:
    """The Kraken pair code ``XBTEUR`` and the interval map live only in bot/data/archive.py."""
    hits = [
        p.relative_to(REPO_ROOT).as_posix()
        for p in (REPO_ROOT / "bot").rglob("*.py")
        if "XBTEUR" in p.read_text(encoding="utf-8")
    ]
    assert hits == ["bot/data/archive.py"]

    def _interval_maps(path: Path) -> list[int]:
        """Line numbers of dict literals mapping "1d"/"4h"/"15m" to 1440/240/15."""
        found = []
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Dict):
                continue
            pairs = [
                (k.value, v.value)
                for k, v in zip(node.keys, node.values, strict=True)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            ]
            if any(k in ("1d", "4h", "15m") and v in (1440, 240, 15) for k, v in pairs):
                found.append(node.lineno)
        return found

    maps = {
        p.relative_to(REPO_ROOT).as_posix(): lines
        for p in (REPO_ROOT / "bot").rglob("*.py")
        if (lines := _interval_maps(p))
    }
    assert list(maps) == ["bot/data/archive.py"]


def test_archive_module_never_extracts() -> None:
    src = (REPO_ROOT / "bot" / "data" / "archive.py").read_text(encoding="utf-8")
    code_lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith(("#", "-"))]
    assert not re.search(r"\.extract(all)?\(", "\n".join(code_lines))


def test_cli_requires_zip_and_sha256(repo, capsys) -> None:
    with pytest.raises(SystemExit) as exc:
        _run(repo, "import-archive")
    assert exc.value.code == 2


# --- story 4: merge with an overlap check --------------------------------------------------


def _api_cache_via_update(repo: Path, exchange: FakeExchange, n: int = 10) -> pd.DataFrame:
    """``bot data update`` writes an api cache of ``n`` daily candles from START (2024)."""
    exchange.script.append(candles(START_MS, n))
    assert _run(repo, "update", "--timeframe", "1d") == cli.EXIT_OK
    df = read_cache(_cache(repo, "1d"))
    assert df is not None and set(df["source"]) == {"api"}
    return df


def _csv_from(
    df: pd.DataFrame,
    close_delta: dict[int, float] | None = None,
    volume_factor: dict[int, float] | None = None,
) -> str:
    """SYNTHETIC archive CSV restating ``df``'s rows, with optional per-row changes."""
    close_delta, volume_factor = close_delta or {}, volume_factor or {}
    lines = []
    for i, r in df.reset_index(drop=True).iterrows():
        ts = int(r["open_at"].value // 1_000_000_000)
        close = r["close"] + close_delta.get(i, 0.0)
        volume = r["volume"] * volume_factor.get(i, 1.0)
        lines.append(f"{ts},{r['open']!r},{r['high']!r},{r['low']!r},{close!r},{volume!r},42")
    return "\n".join(lines) + "\n"


def _pre_rows(n: int) -> pd.DataFrame:
    """``n`` SYNTHETIC archive-only days just before START (days -n..-1)."""
    return rows(list(range(-n, 0)), ["archive"] * n)


def test_archive_two_ticks_off_on_close_exits_4_cache_byte_identical(
    repo, clock, capsys, exchange
) -> None:
    """AC1: 2-tick close difference on the overlap -> exit 4 naming close; bytes unchanged."""
    api = _api_cache_via_update(repo, exchange)
    path = _cache(repo, "1d")
    before = path.read_bytes()
    overlap = api.iloc[:5]
    csv = _csv_from(_pre_rows(3)) + _csv_from(overlap, close_delta={2: 2 * TICK})
    zip_path = build_zip(repo / "a.zip", [("XBTEUR_1440.csv", csv)])
    capsys.readouterr()

    code = _import(repo, zip_path, sha256_hex(zip_path), "1d")

    err = capsys.readouterr().err
    assert code == 4
    assert "DATA ERROR [1d]: overlap mismatch on close" in err, err
    assert repr(float(overlap["close"].iloc[2])) in err
    assert repr(float(overlap["close"].iloc[2] + 2 * TICK)) in err
    assert "2024-01-03" in err
    assert path.read_bytes() == before


def test_archive_volume_off_exits_4_naming_volume(repo, clock, capsys, exchange) -> None:
    api = _api_cache_via_update(repo, exchange)
    path = _cache(repo, "1d")
    before = path.read_bytes()
    zip_path = build_zip(
        repo / "a.zip", [("XBTEUR_1440.csv", _csv_from(api.iloc[:3], volume_factor={1: 1.015}))]
    )

    assert _import(repo, zip_path, sha256_hex(zip_path), "1d") == 4
    assert "overlap mismatch on volume" in capsys.readouterr().err
    assert path.read_bytes() == before


def test_archive_agreeing_overlap_becomes_archive_api_rows_stay(
    repo, clock, capsys, exchange
) -> None:
    """AC2: within 1 tick and 1% volume -> overlap rows become archive, api-only rows stay
    api, and ``bot data validate`` exits 0."""
    api = _api_cache_via_update(repo, exchange)
    overlap = api.iloc[:5]
    csv = _csv_from(_pre_rows(3)) + _csv_from(
        overlap, close_delta={0: TICK, 3: -TICK}, volume_factor={1: 1.009, 4: 0.991}
    )
    zip_path = build_zip(repo / "a.zip", [("XBTEUR_1440.csv", csv)])
    capsys.readouterr()

    code = _import(repo, zip_path, sha256_hex(zip_path), "1d")

    out, err = capsys.readouterr()
    assert code == cli.EXIT_OK, err
    df = read_cache(_cache(repo, "1d"))
    assert df is not None and len(df) == 13
    assert df["source"].tolist() == ["archive"] * 8 + ["api"] * 5
    assert df["open_at"].iloc[3:].tolist() == api["open_at"].tolist()
    assert df["trades"].iloc[3:8].tolist() == [42] * 5  # archive rows kept, not patched
    assert df["close"].iloc[3] == pytest.approx(api["close"].iloc[0] + TICK)
    pd.testing.assert_frame_equal(
        df.iloc[8:].reset_index(drop=True), api.iloc[5:].reset_index(drop=True)
    )
    assert "1d: overlap rows_compared=5 max_price_diff_ticks=1 " in out
    assert "sources={'archive': 8, 'api': 5, 'synthetic': 0, 'trades': 0}" in out
    assert _run(repo, "validate", "--timeframe", "1d") == cli.EXIT_OK


def test_archive_then_update_keeps_archive_and_appends_api(repo, clock, exchange) -> None:
    """Archive cache first, then ``bot data update``: only later candles requested, merged."""
    zip_path = build_zip(repo / "a.zip", [("XBTEUR_1440.csv", kraken_csv(START_S, 5, 86_400))])
    assert _import(repo, zip_path, sha256_hex(zip_path), "1d") == cli.EXIT_OK
    exchange.script.append(candles(START_MS + 5 * 86_400_000, 3))

    assert _run(repo, "update", "--timeframe", "1d") == cli.EXIT_OK

    assert exchange.calls[0]["since"] == START_MS + 5 * 86_400_000
    df = read_cache(_cache(repo, "1d"))
    assert df is not None and df["source"].tolist() == ["archive"] * 5 + ["api"] * 3


def test_gap_between_archive_and_api_is_a_download_gap(repo, clock, capsys, exchange) -> None:
    api = _api_cache_via_update(repo, exchange)
    path = _cache(repo, "1d")
    before = path.read_bytes()
    pre = _pre_rows(5).iloc[:4]  # days -5..-2: day -1 missing between archive and api
    zip_path = build_zip(repo / "a.zip", [("XBTEUR_1440.csv", _csv_from(pre))])

    assert _import(repo, zip_path, sha256_hex(zip_path), "1d") == 4
    assert "DATA ERROR [1d]: download gap at 2023-12-31" in capsys.readouterr().err
    assert path.read_bytes() == before
    assert len(api) == 10


@pytest.mark.parametrize(
    "markets",
    [
        {"BTC/EUR": {"precision": {"price": 0}}},
        {"BTC/EUR": {"precision": {"price": float("nan")}}},
        {"BTC/EUR": {"precision": {}}},
    ],
)
def test_merge_with_bad_tick_refused(repo, clock, capsys, exchange, markets) -> None:
    zip_path = standard_zip(repo)
    assert _import(repo, zip_path, sha256_hex(zip_path), "1d") == cli.EXIT_OK
    path = _cache(repo, "1d")
    before = path.read_bytes()
    exchange.markets = markets

    assert _import(repo, zip_path, sha256_hex(zip_path), "1d") == 4
    assert "DATA ERROR [1d]:" in capsys.readouterr().err
    assert path.read_bytes() == before


@pytest.mark.parametrize("tick", [0, -1.0, float("nan"), None])
def test_import_archive_refuses_bad_tick_when_merging(repo, tick) -> None:
    zip_path = standard_zip(repo)
    sha = sha256_hex(zip_path)
    import_archive(_settings(repo), zip_path, sha, ["1d"], tick_provider=_tick, now=NOW)
    before = _cache(repo, "1d").read_bytes()
    with pytest.raises(ArchiveError, match="invalid price tick"):
        import_archive(_settings(repo), zip_path, sha, ["1d"], tick_provider=lambda: tick, now=NOW)
    assert _cache(repo, "1d").read_bytes() == before


def test_tick_provider_called_once_across_timeframes(repo) -> None:
    zip_path = standard_zip(repo)
    sha = sha256_hex(zip_path)
    import_archive(_settings(repo), zip_path, sha, ALL_TFS, tick_provider=_tick, now=NOW)
    calls: list[int] = []

    def _counting() -> float:
        calls.append(1)
        return TICK

    import_archive(_settings(repo), zip_path, sha, ALL_TFS, tick_provider=_counting, now=NOW)
    assert calls == [1]


@pytest.mark.parametrize(
    ("sha", "expected"), [("abc", "malformed --sha256"), ("0" * 64, "checksum mismatch")]
)
def test_checksum_errors_reported_even_offline(repo, clock, capsys, exchange, sha, expected):
    """The tick is lazy: an offline load_markets never masks the real cause."""
    exchange.markets = ccxt.NetworkError("offline")
    zip_path = standard_zip(repo)
    assert _import(repo, zip_path, sha, "1d") == 4
    err = capsys.readouterr().err
    assert expected in err and "load_markets" not in err
    assert exchange.load_markets_calls == 0


def test_first_import_never_calls_load_markets(repo, clock, exchange) -> None:
    exchange.markets = ccxt.NetworkError("offline")
    zip_path = standard_zip(repo)
    assert _import(repo, zip_path, sha256_hex(zip_path)) == cli.EXIT_OK
    assert exchange.load_markets_calls == 0
    assert not _no_caches(repo)


def test_merge_into_defective_cache_refused(repo, clock, capsys) -> None:
    path = _cache(repo, "1d")
    write_cache(path, rows([0, 1, 3], ["api"] * 3))  # download gap in the cache
    before = path.read_bytes()
    zip_path = standard_zip(repo)

    assert _import(repo, zip_path, sha256_hex(zip_path), "1d") == 4
    assert "DATA ERROR [1d]: download gap" in capsys.readouterr().err
    assert path.read_bytes() == before
