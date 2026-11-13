"""``bot`` entry point (SAF-08, SAF-09, FR-10, FR-45, AD-15).

Subcommands in M0: ``backtest``, ``dry-run``, ``live``. All are stubs that validate the
configuration and the strategy/mode combination, then exit with "not implemented".

M1 adds ``bot data update`` and ``bot data validate`` (AD-18): public, unauthenticated
candle download into the local Parquet cache, and its validation. M1 story 3 adds
``bot data import-archive --zip PATH --sha256 HEX`` (Kraken OHLCVT archive, checksum first);
for a split archive repeat ``--zip`` once per part, in order, and add ``--part-sums FILE``.
M1 story 4: both writers merge through the overlap-checked ``merge_candles`` (tick from the
public exchange's market metadata) and print the overlap statistics. Data errors exit with
``EXIT_DATA_ERROR``. M1 story 5: ``bot data validate`` also prints each file's ``data_hash``
(NFR-02, AD-21). M1 story 9: ``bot data backfill-trades --timeframe TF --start ISO --end ISO``
rebuilds candles from public trades over ``[start, end)`` (UTC; a date means 00:00 UTC),
resumable through a trades checkpoint, and merges them like the other writers.

``live`` requires BOTH the ``--live`` flag AND ``TRADING_BOT_LIVE=I_ACCEPT_REAL_ORDERS`` in
the process environment (never from .env), plus a strategy allowed in live. Only
``open_live_gate`` can create a ``LiveGate``; KrakenBroker (M6) will require one. In M0,
``live`` still refuses after the gates pass: no broker is ever constructed.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from bot.backtest import command as backtest_command
from bot.backtest.lookahead import LookAheadError
from bot.backtest.runner import InsufficientData
from bot.clock import Clock, SystemClock
from bot.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_ENV_PATH,
    LIVE_GATE_ENV,
    LIVE_GATE_VALUE,
    TIMEFRAME_SECONDS,
    ConfigError,
    Settings,
    load_settings,
)
from bot.data.archive import ArchiveError, import_archive
from bot.data.cache import SOURCES, cache_path, data_hash
from bot.data.fetch import FetchError, make_public_exchange, price_tick
from bot.data.merge import OverlapStats
from bot.data.trades import backfill_trades
from bot.data.update import update_timeframe_with_stats
from bot.data.validate import (
    DataValidationError,
    ValidationReport,
    audit_gaps,
    read_cache_checked,
    validate_frame,
)
from bot.strategy.base import Mode
from bot.strategy.registry import StrategyNotAllowed, strategy_class_for

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_NOT_IMPLEMENTED = 3
EXIT_DATA_ERROR = 4
EXIT_LOOKAHEAD = 5

DATA_TIMEFRAMES = ("15m", "4h", "1d")

# Injectable adapters for ``bot data``; tests monkeypatch these module-level factories.
_exchange_factory: Callable[[], Any] = make_public_exchange
_clock_factory: Callable[[], Clock] = SystemClock

LIVE_TIMEFRAMES = frozenset({"4h", "1d"})  # CON-08

_GATE_KEY = object()


class LiveGateRefused(Exception):
    """A live-gate condition is missing; the message names it."""


class LiveGate:
    """Proof that every live condition was checked. Only ``open_live_gate`` creates one."""

    def __init__(self, key: object, strategy_id: str) -> None:
        if key is not _GATE_KEY:
            raise LiveGateRefused("LiveGate can only be created by cli.open_live_gate")
        self.strategy_id = strategy_id


def open_live_gate(
    live_flag: bool, env: Mapping[str, str], strategy_id: str, settings: Settings
) -> LiveGate:
    """Check the live conditions available in M0 (AD-15) and return a LiveGate.

    Remaining AD-15 conditions (fee check, key permissions) are added at M6.
    """
    if not live_flag:
        raise LiveGateRefused("missing CLI flag --live")
    if env.get(LIVE_GATE_ENV) != LIVE_GATE_VALUE:
        raise LiveGateRefused(f"environment variable {LIVE_GATE_ENV} is not set to the gate value")
    try:
        cls = strategy_class_for(strategy_id, "live")
    except StrategyNotAllowed as exc:
        raise LiveGateRefused(str(exc)) from exc
    if cls.timeframe not in LIVE_TIMEFRAMES:
        raise LiveGateRefused(f"timeframe {cls.timeframe} not allowed in live (4h or 1d only)")
    return LiveGate(_GATE_KEY, strategy_id)


def _parser() -> argparse.ArgumentParser:
    # allow_abbrev=False: the live gate must require the exact ``--live`` flag (audit M0 F-6).
    parser = argparse.ArgumentParser(
        prog="bot", description="Kraken spot trading bot", allow_abbrev=False
    )
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_ in (
        ("backtest", "run a backtest (M2)"),
        ("dry-run", "run the engine with the paper broker (M3)"),
        ("live", "run the engine with real orders (M6; refuses in M0)"),
    ):
        p = sub.add_parser(name, help=help_, allow_abbrev=False)
        p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
        p.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
        p.add_argument("--strategy", default=None, help="strategy id (default: config)")
        if name == "backtest":
            p.add_argument(
                "--start",
                type=date.fromisoformat,
                default=None,
                help="first day, UTC (default: data.history_start)",
            )
            p.add_argument(
                "--end",
                type=date.fromisoformat,
                default=None,
                help="end day, exclusive, UTC (default: backtest.holdout_start; never later)",
            )
            p.add_argument(
                "--results-dir", type=Path, default=None, help="default: backtest.results_dir"
            )
        if name == "live":
            p.add_argument("--live", action="store_true", help="required to run live")

    data = sub.add_parser("data", help="market data cache (AD-18)", allow_abbrev=False)
    data_sub = data.add_subparsers(dest="data_command", required=True)
    for name, help_ in (
        ("update", "download recent closed candles into the cache (public API)"),
        ("validate", "validate the cached candles; never repairs"),
        ("import-archive", "import candles from a Kraken OHLCVT ZIP archive (checksum first)"),
        ("audit-gaps", "list no-trade (synthetic) runs in a date window; read-only"),
    ):
        p = data_sub.add_parser(name, help=help_, allow_abbrev=False)
        p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
        p.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
        default_tf = "1d" if name == "audit-gaps" else "data.timeframes in config"
        p.add_argument(
            "--timeframe",
            action="append",
            choices=DATA_TIMEFRAMES,
            default=None,
            help=f"timeframe to process; repeatable (default: {default_tf})",
        )
        if name == "import-archive":
            p.add_argument(
                "--zip",
                type=Path,
                action="append",
                required=True,
                help="Kraken OHLCVT ZIP archive; repeat once per part, in order, for a split "
                "archive (Kraken_OHLCVT_Full.zip.part00 ... part04; no reassembly needed)",
            )
            p.add_argument(
                "--part-sums",
                type=Path,
                default=None,
                help="published part checksum file (OHLCVT_Full_PARTS_SHA256SUMS.txt); "
                "required with several --zip parts",
            )
            p.add_argument(
                "--sha256",
                required=True,
                help="expected SHA-256 of the whole ZIP (of the parts concatenated), 64 hex",
            )
        if name == "audit-gaps":
            p.add_argument("--start", type=date.fromisoformat, default=date(2013, 1, 1))
            p.add_argument(
                "--end", type=date.fromisoformat, default=date(2016, 12, 31), help="inclusive"
            )

    p = data_sub.add_parser(
        "backfill-trades",
        help="rebuild candles from public trades over [start, end) and merge them (resumable)",
        allow_abbrev=False,
    )
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    p.add_argument("--timeframe", choices=DATA_TIMEFRAMES, required=True)
    for flag, what in (("--start", "first candle (inclusive)"), ("--end", "exclusive")):
        p.add_argument(
            flag,
            type=_utc_instant,
            required=True,
            help=f"{what}; ISO date or datetime, UTC (a date means 00:00 UTC)",
        )
    return parser


def _utc_instant(text: str) -> datetime:
    """ISO date (00:00 UTC) or datetime; naive values are UTC, offsets converted to UTC."""
    try:
        if len(text) == 10:
            d = date.fromisoformat(text)
            return datetime(d.year, d.month, d.day, tzinfo=UTC)
        t = datetime.fromisoformat(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"not an ISO date or datetime: {text!r}") from exc
    return t.replace(tzinfo=UTC) if t.tzinfo is None else t.astimezone(UTC)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _data_error(tf: str, exc: FetchError | DataValidationError) -> None:
    # Schema-level defects (wrong columns, naive open_at) have no single timestamp.
    where = "" if exc.open_at is None or pd.isna(exc.open_at) else f" at {exc.open_at}"
    _err(f"DATA ERROR [{tf}]: {exc.defect}{where}")


def _print_overlap(tf: str, stats: OverlapStats) -> None:
    print(
        f"{tf}: overlap rows_compared={stats.rows_compared} "
        f"max_price_diff_ticks={stats.max_price_diff_ticks:.6g} "
        f"max_volume_diff_fraction={stats.max_volume_diff_fraction:.6g}"
    )


def _print_report(tf: str, report: ValidationReport, settings: Settings) -> None:
    print(
        f"{tf}: rows={report.rows} first={report.first} last={report.last} "
        f"sources={report.sources} synthetic={report.synthetic_rows} "
        f"synthetic_ratio_from_{settings.data.history_start}="
        f"{report.synthetic_ratio_after_start:.6g}"
    )
    if report.synthetic_by_year:
        print(f"{tf}: synthetic_by_year={report.synthetic_by_year}")


def _data_command(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(args.config, args.env_file)
    except ConfigError as exc:
        _err(f"REFUSED: invalid configuration: {exc}")
        return EXIT_REFUSED
    timeframes = list(dict.fromkeys(args.timeframe or settings.data.timeframes))
    clock = _clock_factory()
    if args.data_command == "import-archive":
        return _import_archive_command(args, settings, timeframes, clock)
    if args.data_command == "backfill-trades":
        return _backfill_trades_command(args, settings, clock)
    if args.data_command == "audit-gaps":
        return _audit_gaps_command(
            args, settings, list(dict.fromkeys(args.timeframe or ["1d"])), clock
        )
    exchange = _exchange_factory() if args.data_command == "update" else None
    failed = False
    for tf in timeframes:
        stats: OverlapStats | None = None
        try:
            if args.data_command == "update":
                frame, stats = update_timeframe_with_stats(settings, exchange, clock, tf)
                report = validate_frame(frame, tf, settings.data)
            else:
                path = cache_path(settings.paths.var_dir, settings.pairs[0], tf)
                frame = read_cache_checked(path)
                if frame is None:
                    _err(f"DATA ERROR [{tf}]: no cache for {tf} ({path})")
                    failed = True
                    continue
                report = validate_frame(frame, tf, settings.data, now=clock.now())
        except (FetchError, DataValidationError) as exc:
            _data_error(tf, exc)
            failed = True
            continue
        except OSError as exc:  # e.g. cache file locked on Windows
            _err(f"DATA ERROR [{tf}]: {type(exc).__name__}: {exc}")
            failed = True
            continue
        _print_report(tf, report, settings)
        if stats is not None:
            _print_overlap(tf, stats)
        if args.data_command == "validate":
            print(f"{tf}: data_hash={data_hash(frame)}")
    return EXIT_DATA_ERROR if failed else EXIT_OK


def _backfill_trades_command(args: argparse.Namespace, settings: Settings, clock: Clock) -> int:
    """Rebuild candles from public trades (M1 story 9); exit 4 on any data error."""
    tf = args.timeframe
    try:
        result = backfill_trades(settings, _exchange_factory(), clock, tf, args.start, args.end)
        report = validate_frame(result.frame, tf, settings.data)
    except (FetchError, DataValidationError) as exc:
        _data_error(tf, exc)
        return EXIT_DATA_ERROR
    except OSError as exc:  # e.g. cache file locked on Windows
        _err(f"DATA ERROR [{tf}]: {type(exc).__name__}: {exc}")
        return EXIT_DATA_ERROR
    print(
        f"{tf}: trades fetched={result.trades_new + result.trades_from_checkpoint} "
        f"(new={result.trades_new} from_checkpoint={result.trades_from_checkpoint}) "
        f"candles_built={result.candles_built} synthetic_filled={result.synthetic_filled} "
        f"checkpoint={result.checkpoint}"
    )
    _print_overlap(tf, result.stats)
    _print_report(tf, report, settings)
    return EXIT_OK


def _audit_gaps_command(
    args: argparse.Namespace, settings: Settings, timeframes: list[str], clock: Clock
) -> int:
    """Read-only gap audit (M1 story 6): validates each cache first, then lists runs."""
    if args.start > args.end:
        _err(f"REFUSED: --start {args.start} is after --end {args.end}")
        return EXIT_REFUSED
    start = pd.Timestamp(args.start, tz="UTC")
    end = pd.Timestamp(args.end, tz="UTC") + pd.Timedelta(days=1)  # --end is inclusive
    failed = False
    for tf in timeframes:
        path = cache_path(settings.paths.var_dir, settings.pairs[0], tf)
        try:
            frame = read_cache_checked(path)
            if frame is None:
                _err(f"DATA ERROR [{tf}]: no cache for {tf} ({path})")
                failed = True
                continue
            validate_frame(frame, tf, settings.data, now=clock.now())
        except DataValidationError as exc:
            _data_error(tf, exc)
            failed = True
            continue
        except OSError as exc:  # e.g. cache file locked on Windows
            _err(f"DATA ERROR [{tf}]: {type(exc).__name__}: {exc}")
            failed = True
            continue
        audit = audit_gaps(frame, tf, start, end)
        window = f"{args.start}..{args.end}"
        if audit.first is None or audit.last is None:
            print(
                f"{tf}: {window}: NOT AUDITABLE - no cached candles in this window "
                f"(cache covers {frame['open_at'].iloc[0]} .. {frame['open_at'].iloc[-1]})"
            )
            continue
        print(
            f"{tf}: {window}: rows={audit.rows} first={audit.first} last={audit.last} "
            f"synthetic_runs={len(audit.runs)} synthetic_rows={audit.synthetic_rows}"
        )
        step = pd.Timedelta(seconds=TIMEFRAME_SECONDS[tf])
        if audit.first > start:
            print(f"{tf}:   PARTIAL COVERAGE - not examined {start} .. {audit.first - step}")
        if audit.last + step < end:
            print(f"{tf}:   PARTIAL COVERAGE - not examined {audit.last + step} .. {end - step}")
        for run_start, run_end, length in audit.runs:
            clipped = " (crosses the window edge)" if run_start < start or run_end >= end else ""
            print(f"{tf}:   no-trade run {run_start} .. {run_end} ({length} candles){clipped}")
    return EXIT_DATA_ERROR if failed else EXIT_OK


def _import_archive_command(
    args: argparse.Namespace, settings: Settings, timeframes: list[str], clock: Clock
) -> int:
    def _written(tf: str, frame: pd.DataFrame, stats: OverlapStats) -> None:
        counts = frame["source"].value_counts()
        sources = {s: int(counts.get(s, 0)) for s in SOURCES}
        print(
            f"{tf}: rows={len(frame)} first={frame['open_at'].iloc[0]} "
            f"last={frame['open_at'].iloc[-1]} sources={sources} "
            f"synthetic={sources['synthetic']}"
        )
        _print_overlap(tf, stats)

    pair = settings.pairs[0]
    try:
        import_archive(
            settings,
            args.zip[0] if len(args.zip) == 1 else args.zip,
            args.sha256,
            timeframes,
            # Tick from public market metadata (CON-03), fetched only to merge into a cache.
            tick_provider=lambda: price_tick(_exchange_factory(), pair),
            part_sums=args.part_sums,
            now=clock.now(),
            on_written=_written,
        )
    except ArchiveError as exc:
        where = f" [{exc.timeframe}]" if exc.timeframe else ""
        _err(f"DATA ERROR{where}: {exc}")
        return EXIT_DATA_ERROR
    return EXIT_OK


def _backtest_command(args: argparse.Namespace, settings: Settings, strategy_id: str) -> int:
    """``bot backtest`` (M2): results file + report; the holdout is excluded by default."""
    req = backtest_command.default_request(settings, strategy_id, _clock_factory().now().date())
    req = replace(
        req,
        start=args.start or req.start,
        end=args.end or req.end,
        results_dir=args.results_dir or req.results_dir,
    )
    try:
        json_path, md_path, _ = backtest_command.execute(settings, req)
    except backtest_command.BacktestRefused as exc:
        _err(f"REFUSED: {exc}")
        return EXIT_REFUSED
    except LookAheadError as exc:
        _err(f"LOOK-AHEAD GUARD FAILED, no report written: {exc}")
        return EXIT_LOOKAHEAD
    except NotImplementedError as exc:
        _err(f"{exc}")
        return EXIT_NOT_IMPLEMENTED
    except (DataValidationError, OSError, InsufficientData) as exc:
        _err(f"DATA ERROR: {type(exc).__name__}: {exc}")
        return EXIT_DATA_ERROR
    print(md_path.read_text(encoding="utf-8").splitlines()[0])
    print(f"results: {json_path}")
    print(f"report:  {md_path}")
    return EXIT_OK


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = _parser().parse_args(argv)
    env = dict(os.environ) if env is None else env
    if args.command == "data":
        return _data_command(args)
    mode: Mode = args.command

    if mode == "live":
        # Cheap gates first: nothing is loaded unless both the flag and the env var are set.
        if not args.live:
            _err("REFUSED: live requires the --live flag")
            return EXIT_REFUSED
        if env.get(LIVE_GATE_ENV) != LIVE_GATE_VALUE:
            _err(f"REFUSED: live requires {LIVE_GATE_ENV} to be set in the environment")
            return EXIT_REFUSED

    try:
        settings = load_settings(args.config, args.env_file)
    except ConfigError as exc:
        _err(f"REFUSED: invalid configuration: {exc}")
        return EXIT_REFUSED
    strategy_id = args.strategy or settings.strategy.id

    if mode == "live":
        try:
            open_live_gate(args.live, env, strategy_id, settings)
        except LiveGateRefused as exc:
            _err(f"REFUSED: {exc}")
            return EXIT_REFUSED
        _err("REFUSED: live mode is not implemented yet (M6); no order can be placed")
        return EXIT_NOT_IMPLEMENTED

    try:
        strategy_class_for(strategy_id, mode)
    except StrategyNotAllowed as exc:
        _err(f"REFUSED: {exc}")
        return EXIT_REFUSED
    if mode == "backtest":
        return _backtest_command(args, settings, strategy_id)
    _err(f"{mode} is not implemented yet (M0 scaffold)")
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":
    sys.exit(main())
