"""``bot data audit-gaps``: read-only listing of no-trade (synthetic) runs (M1 story 6).

All candles here are synthetic test data built in tmp_path; no network.
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import pytest

from bot import cli
from bot.clock import FakeClock
from bot.data.cache import write_cache
from bot.data.validate import apply_no_trade_policy, audit_gaps
from tests.conftest import REPO_ROOT
from tests.data.fakes import rows

# Day offsets from 2024-01-01 (tests.data.fakes.START): -3652 is 2014-01-01, before the
# configured data.history_start, so the synthetic-ratio cap does not apply to these rows.
D2014 = -3652
NOW = datetime(2024, 6, 1, tzinfo=UTC)


def _gappy() -> pd.DataFrame:
    """Archive days 2014-01-01, 01-03 (one-day hole) and 01-07 (three-day hole), filled."""
    df = rows([D2014, D2014 + 2, D2014 + 6], ["archive"] * 3, base=5000.0)
    return apply_no_trade_policy(df, "1d", "fill_flat")


def _day(offset: int) -> pd.Timestamp:
    return pd.Timestamp("2014-01-01", tz="UTC") + pd.Timedelta(days=offset)


def test_audit_lists_each_synthetic_run() -> None:
    df = _gappy()
    snapshot = df.copy()
    audit = audit_gaps(df, "1d", _day(0), _day(30))
    pd.testing.assert_frame_equal(df, snapshot)  # read-only
    assert audit.rows == 7
    assert audit.first == _day(0) and audit.last == _day(6)
    assert audit.runs == ((_day(1), _day(1), 1), (_day(3), _day(5), 3))
    assert audit.synthetic_rows == 4


def test_audit_window_is_half_open_and_runs_keep_full_extent() -> None:
    audit = audit_gaps(_gappy(), "1d", _day(2), _day(4))
    assert audit.rows == 2 and audit.first == _day(2) and audit.last == _day(3)
    # The 3-day run 01-04..01-06 crosses the window end: reported whole, not clipped.
    assert audit.runs == ((_day(3), _day(5), 3),)


def test_audit_refuses_reversed_window() -> None:
    with pytest.raises(ValueError, match="not before end"):
        audit_gaps(_gappy(), "1d", _day(4), _day(2))


def test_audit_of_window_without_candles_is_not_a_clean_result() -> None:
    audit = audit_gaps(rows([0, 1], ["api", "api"]), "1d", _day(0), _day(30))
    assert audit.rows == 0 and audit.first is None and audit.runs == ()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(REPO_ROOT / "config.yaml", root / "config.yaml")
    monkeypatch.setattr(cli, "_clock_factory", lambda: FakeClock(NOW))

    def _no_exchange() -> None:
        raise AssertionError("audit-gaps must not touch the exchange")

    monkeypatch.setattr(cli, "_exchange_factory", _no_exchange)
    return root


def _run(repo: Path, *extra: str) -> int:
    args = ["--config", str(repo / "config.yaml"), "--env-file", str(repo / "none.env")]
    return cli.main(["data", "audit-gaps", *args, *extra], env={})


def _cache(repo: Path) -> Path:
    return repo / "var" / "data" / "BTC-EUR" / "1d.parquet"


def test_cli_prints_runs_and_leaves_file_untouched(repo, capsys, network_attempts) -> None:
    write_cache(_cache(repo), _gappy())
    before = hashlib.sha256(_cache(repo).read_bytes()).hexdigest()

    assert _run(repo) == cli.EXIT_OK, capsys.readouterr().err

    out = capsys.readouterr().out
    assert "1d: 2013-01-01..2016-12-31: rows=7" in out
    assert "synthetic_runs=2 synthetic_rows=4" in out
    assert "no-trade run 2014-01-04 00:00:00+00:00 .. 2014-01-06 00:00:00+00:00 (3 candles)" in out
    assert hashlib.sha256(_cache(repo).read_bytes()).hexdigest() == before
    assert network_attempts == []


def test_cli_says_not_auditable_when_cache_misses_the_window(repo, capsys) -> None:
    write_cache(_cache(repo), rows([0, 1, 2], ["api"] * 3))
    assert _run(repo) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "NOT AUDITABLE - no cached candles in this window" in out
    assert "cache covers 2024-01-01" in out


def test_cli_custom_window_is_inclusive_of_end(repo, capsys) -> None:
    write_cache(_cache(repo), _gappy())
    assert _run(repo, "--start", "2014-01-02", "--end", "2014-01-04") == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "rows=3" in out and "synthetic_runs=2 synthetic_rows=4" in out
    assert "2014-01-06 00:00:00+00:00 (3 candles) (crosses the window edge)" in out
    assert "PARTIAL COVERAGE" not in out


def test_cli_flags_partial_coverage_at_both_ends(repo, capsys) -> None:
    write_cache(_cache(repo), _gappy())  # covers 2014-01-01 .. 2014-01-07
    assert _run(repo, "--start", "2013-12-30", "--end", "2014-01-09") == cli.EXIT_OK
    out = capsys.readouterr().out
    assert (
        "PARTIAL COVERAGE - not examined 2013-12-30 00:00:00+00:00 .. 2013-12-31 00:00:00+00:00"
        in out
    )
    assert (
        "PARTIAL COVERAGE - not examined 2014-01-08 00:00:00+00:00 .. 2014-01-09 00:00:00+00:00"
        in out
    )


def test_cli_refuses_start_after_end(repo, capsys) -> None:
    write_cache(_cache(repo), _gappy())
    assert _run(repo, "--start", "2014-02-01", "--end", "2014-01-01") == cli.EXIT_REFUSED
    assert "--start 2014-02-01 is after --end 2014-01-01" in capsys.readouterr().err


def test_cli_missing_cache_exits_4(repo, capsys) -> None:
    assert _run(repo) == cli.EXIT_DATA_ERROR
    assert "no cache for 1d" in capsys.readouterr().err


def test_cli_invalid_cache_exits_4_before_auditing(repo, capsys) -> None:
    df = rows([D2014, D2014 + 2], ["archive"] * 2, base=5000.0)  # unfilled no-trade hole
    write_cache(_cache(repo), df)
    assert _run(repo) == cli.EXIT_DATA_ERROR
    captured = capsys.readouterr()
    assert "no-trade gap not filled" in captured.err
    assert "synthetic_runs" not in captured.out
