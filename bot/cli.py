"""``bot`` entry point (SAF-08, SAF-09, FR-10, FR-45, AD-15).

Subcommands: ``backtest``, ``dry-run``, ``live``. In M0 all three were stubs that validated
the configuration and the strategy/mode combination, then exited with "not implemented".
M2: ``bot backtest`` is implemented (``bot.backtest.command``): one command, holdout excluded
by default, look-ahead guard (exit 5 on a leak), ``--holdout`` for the single registered
holdout run, ``--change N``. ``dry-run`` and ``live`` remain stubs.

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
import logging
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from bot import journal, logging_setup, ops, runtime
from bot.backtest import command as backtest_command
from bot.backtest.lookahead import LookAheadError
from bot.backtest.runner import InsufficientData
from bot.broker.errors import RateLimited, TransientReadError
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
from bot.risk.kill_switch import engage
from bot.store import StoreError
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
HALT_RULES = (
    "daily_loss",
    "total_drawdown",
    "reconcile_mismatch",
    "fatal_error",
    "clock_skew",
    "all",
)

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
            p.add_argument(
                "--change",
                type=int,
                default=0,
                help="strategy change number (0 = baseline; 1..5 need a changes.md entry)",
            )
            p.add_argument(
                "--holdout",
                action="store_true",
                help="the ONE-SHOT holdout run (recorded in results/holdout_runs.jsonl; clean "
                "tree required). Irreversible: decide before running.",
            )
            p.add_argument(
                "--rerun-holdout",
                action="store_true",
                help="allow a second holdout run (needs --reason; banners later reports)",
            )
            p.add_argument("--reason", default=None, help="reason for --rerun-holdout")
        if name == "live":
            p.add_argument("--live", action="store_true", help="required to run live")
        if name == "dry-run":
            p.add_argument(
                "--approval",
                choices=("manual", "autonomous"),
                default=None,
                help="override execution.approval for this dry-run session (logged)",
            )
            p.add_argument("--max-ticks", type=int, default=None, help=argparse.SUPPRESS)

    for name, help_ in (
        ("status", "print the state of a store: heartbeat, halts, kill switch, intent"),
        ("stop", "ask a running engine to stop gracefully after its current tick"),
    ):
        p = sub.add_parser(name, help=help_, allow_abbrev=False)
        _store_args(p)

    # Operator commands (AD-12, AD-16, AD-25): each inserts ONE operator_actions row; the
    # running engine applies it on its next tick. ``kill on`` also creates the file.
    p = sub.add_parser("kill", help="kill switch: on (engage now) / off (engine deletes)")
    p.add_argument("state", choices=("on", "off"))
    p.add_argument("--note", required=True)
    _store_args(p)
    p = sub.add_parser("reset-halt", help="reset an active halt (manual only, never timed)")
    p.add_argument("rule", choices=HALT_RULES)
    p.add_argument("--note", required=True)
    p.add_argument(
        "--rebase-baseline",
        "--rebase",
        dest="rebase_baseline",
        action="store_true",
        help="total_drawdown only: append a new drawdown baseline at current equity "
        "(asks for a typed confirmation)",
    )
    _store_args(p)
    p = sub.add_parser("flatten", help="sell the whole position (the only sell while stopped)")
    p.add_argument("--note", required=True)
    _store_args(p)
    for name in ("approve", "reject"):
        p = sub.add_parser(name, help=f"{name} an intent awaiting approval (manual mode)")
        p.add_argument("intent_id", type=int)
        p.add_argument("--note", required=(name == "reject"), default="approved via CLI")
        _store_args(p)
    p = sub.add_parser("journal", help="print the signal journal with would-have-returned")
    p.add_argument("--limit", type=int, default=30)
    _store_args(p)

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


def _store_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    p.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
    p.add_argument("--strategy", default=None, help="strategy id (default: config)")
    p.add_argument("--mode", choices=("dry-run",), default="dry-run", help="store mode")


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
    if args.rerun_holdout and not args.holdout:
        _err("REFUSED: --rerun-holdout only makes sense with --holdout")
        return EXIT_REFUSED
    if args.rerun_holdout and not (args.reason or "").strip():
        _err("REFUSED: --rerun-holdout needs --reason")
        return EXIT_REFUSED
    if args.reason is not None and not args.rerun_holdout:
        _err("REFUSED: --reason is only used with --rerun-holdout")
        return EXIT_REFUSED
    if args.holdout and (args.start or args.end):
        _err("REFUSED: the holdout run uses the fixed holdout window; no --start/--end")
        return EXIT_REFUSED
    req = replace(
        req,
        start=args.start or req.start,
        end=args.end or req.end,
        results_dir=args.results_dir or req.results_dir,
        change=args.change,
        holdout=args.holdout,
        rerun_reason=args.reason if args.rerun_holdout else None,
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


def _dry_run_command(args: argparse.Namespace, settings: Settings, strategy_id: str) -> int:
    """``bot dry-run`` (M3): the shared engine with the paper broker on live public data."""
    db = runtime.store_path(settings, "dry-run", strategy_id)
    context = logging_setup.configure(runtime.log_path(settings, "dry-run", strategy_id),
                                      "dry-run", strategy_id)  # fmt: skip
    clock = _clock_factory()
    # AD-8 step 1: the engine lock is taken before the store is opened or migrated.
    lock = runtime.EngineLock(runtime.lock_path(db))
    try:
        lock.acquire()
    except runtime.StartRefused as exc:
        _err(f"REFUSED: {exc}")
        return EXIT_REFUSED
    try:
        dry = runtime.build_dry_run(
            settings, strategy_id, _exchange_factory(), clock, approval=args.approval
        )
    except runtime.StartRefused as exc:
        lock.release()
        _err(f"REFUSED: {exc}")
        return EXIT_REFUSED
    except (TransientReadError, RateLimited) as exc:
        lock.release()
        _err(f"REFUSED: cannot read public market data: {exc}")
        return EXIT_REFUSED
    if args.approval is not None:
        logging.getLogger("bot.cli").warning(
            "execution.approval overridden for this dry-run session: %s (config: %s)",
            args.approval, settings.execution.approval,
        )  # fmt: skip
    stop = runtime.StopFlag(runtime.stop_path(db))
    stop.install_signal_handlers()
    try:
        result = runtime.run_loop(dry, stop, max_ticks=args.max_ticks, lock=lock, on_start=context)
    finally:
        dry.store.close()
    if result.exit_code == runtime.EXIT_REFUSED:
        _err(f"REFUSED: {result.stop_reason}")
    elif result.exit_code != runtime.EXIT_OK:
        _err(f"STOPPED: {result.stop_reason}")
    return result.exit_code


def _store_for(args: argparse.Namespace) -> tuple[Settings, str, Path] | int:
    try:
        settings = load_settings(args.config, args.env_file)
    except ConfigError as exc:
        _err(f"REFUSED: invalid configuration: {exc}")
        return EXIT_REFUSED
    strategy_id = args.strategy or settings.strategy.id
    return settings, strategy_id, runtime.store_path(settings, args.mode, strategy_id)


def _status_command(args: argparse.Namespace) -> int:
    found = _store_for(args)
    if isinstance(found, int):
        return found
    settings, _, db = found
    if not db.is_file():
        _err(f"no store at {db}")
        return 1
    st = ops.status(
        db,
        _clock_factory().now(),
        settings.execution.tick_seconds,
        settings.risk.kill_switch_path,
        pid_alive=runtime.pid_alive,
    )
    print("\n".join(st.lines))
    return EXIT_OK if st.healthy else 1


REBASE_CONFIRMATION = "REBASE"


def _operator_command(args: argparse.Namespace) -> int:
    """Insert one operator action (the only table the CLI writes, AD-17)."""
    found = _store_for(args)
    if isinstance(found, int):
        return found
    settings, _, db = found
    now = _clock_factory().now()
    if args.command == "kill":
        kind = f"kill_{args.state}"
        if args.state == "on":
            state = engage(settings.risk.kill_switch_path, "cli", now)
            print(
                f"KILL SWITCH ENGAGED (source={state.source}) at {settings.risk.kill_switch_path}"
            )
        target, rebase = None, False
    elif args.command == "reset-halt":
        kind, target, rebase = "reset_halt", args.rule, args.rebase_baseline
        if rebase and args.rule not in ("total_drawdown", "all"):
            _err("REFUSED: --rebase-baseline applies to a total_drawdown reset only")
            return EXIT_REFUSED
        if rebase:
            print(
                "This appends a NEW drawdown baseline at the current equity: the 25% total "
                f"drawdown is then measured from it. Type {REBASE_CONFIRMATION} to confirm:"
            )
            if input().strip() != REBASE_CONFIRMATION:
                _err("REFUSED: confirmation not given; nothing written")
                return EXIT_REFUSED
    elif args.command == "flatten":
        kind, target, rebase = "flatten", None, False
    else:  # approve / reject
        kind, target, rebase = args.command, str(args.intent_id), False
    try:
        action_id = ops.write_action(db, now, kind, args.note, target, rebase)
    except (ValueError, StoreError) as exc:
        _err(f"REFUSED: {exc}")
        return EXIT_REFUSED
    print(f"operator action {action_id} ({kind}) recorded; the engine applies it on its next tick")
    return EXIT_OK


def _journal_command(args: argparse.Namespace) -> int:
    found = _store_for(args)
    if isinstance(found, int):
        return found
    _, _, db = found
    if not db.is_file():
        _err(f"no store at {db}")
        return 1
    print("\n".join(journal.render(db, limit=args.limit)))
    return EXIT_OK


def _stop_command(args: argparse.Namespace) -> int:
    found = _store_for(args)
    if isinstance(found, int):
        return found
    _, _, db = found
    path = runtime.stop_path(db)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"stop requested at {_clock_factory().now().isoformat()}\n", encoding="utf-8")
    print(f"stop requested ({path}); the engine stops after its current tick (<= 30 s)")
    return EXIT_OK


def main(argv: Sequence[str] | None = None, env: Mapping[str, str] | None = None) -> int:
    args = _parser().parse_args(argv)
    env = dict(os.environ) if env is None else env
    if args.command == "data":
        return _data_command(args)
    if args.command == "status":
        return _status_command(args)
    if args.command == "stop":
        return _stop_command(args)
    if args.command in ("kill", "reset-halt", "flatten", "approve", "reject"):
        return _operator_command(args)
    if args.command == "journal":
        return _journal_command(args)
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
        if strategy_id == "plumbing":
            _err("backtest of the plumbing strategy is not implemented (dry-run exercise only)")
            return EXIT_NOT_IMPLEMENTED
        return _backtest_command(args, settings, strategy_id)
    return _dry_run_command(args, settings, strategy_id)


if __name__ == "__main__":
    sys.exit(main())
