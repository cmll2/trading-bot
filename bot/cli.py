"""``bot`` entry point (SAF-08, SAF-09, FR-10, FR-45, AD-15).

Subcommands in M0: ``backtest``, ``dry-run``, ``live``. All are stubs that validate the
configuration and the strategy/mode combination, then exit with "not implemented".

M1 adds ``bot data update`` and ``bot data validate`` (AD-18): public, unauthenticated
candle download into the local Parquet cache, and its validation. Data errors exit with
``EXIT_DATA_ERROR``.

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
from pathlib import Path
from typing import Any

import pandas as pd

from bot.clock import Clock, SystemClock
from bot.config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_ENV_PATH,
    LIVE_GATE_ENV,
    LIVE_GATE_VALUE,
    ConfigError,
    Settings,
    load_settings,
)
from bot.data.cache import cache_path
from bot.data.fetch import FetchError, make_public_exchange
from bot.data.update import update_timeframe
from bot.data.validate import DataValidationError, read_cache_checked, validate_frame
from bot.strategy.base import Mode
from bot.strategy.registry import StrategyNotAllowed, strategy_class_for

EXIT_OK = 0
EXIT_REFUSED = 2
EXIT_NOT_IMPLEMENTED = 3
EXIT_DATA_ERROR = 4

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
        if name == "live":
            p.add_argument("--live", action="store_true", help="required to run live")

    data = sub.add_parser("data", help="market data cache (AD-18)", allow_abbrev=False)
    data_sub = data.add_subparsers(dest="data_command", required=True)
    for name, help_ in (
        ("update", "download recent closed candles into the cache (public API)"),
        ("validate", "validate the cached candles; never repairs"),
    ):
        p = data_sub.add_parser(name, help=help_, allow_abbrev=False)
        p.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
        p.add_argument("--env-file", type=Path, default=DEFAULT_ENV_PATH)
        p.add_argument(
            "--timeframe",
            action="append",
            choices=DATA_TIMEFRAMES,
            default=None,
            help="timeframe to process; repeatable (default: data.timeframes in config)",
        )
    return parser


def _err(msg: str) -> None:
    print(msg, file=sys.stderr)


def _data_error(tf: str, exc: FetchError | DataValidationError) -> None:
    # Schema-level defects (wrong columns, naive open_at) have no single timestamp.
    where = "" if exc.open_at is None or pd.isna(exc.open_at) else f" at {exc.open_at}"
    _err(f"DATA ERROR [{tf}]: {exc.defect}{where}")


def _data_command(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(args.config, args.env_file)
    except ConfigError as exc:
        _err(f"REFUSED: invalid configuration: {exc}")
        return EXIT_REFUSED
    timeframes = list(dict.fromkeys(args.timeframe or settings.data.timeframes))
    clock = _clock_factory()
    exchange = _exchange_factory() if args.data_command == "update" else None
    failed = False
    for tf in timeframes:
        try:
            if args.data_command == "update":
                frame = update_timeframe(settings, exchange, clock, tf)
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
        print(
            f"{tf}: rows={report.rows} first={report.first} last={report.last} "
            f"sources={report.sources} synthetic={report.synthetic_rows} "
            f"synthetic_ratio_from_{settings.data.history_start}="
            f"{report.synthetic_ratio_after_start:.6g}"
        )
        if report.synthetic_by_year:
            print(f"{tf}: synthetic_by_year={report.synthetic_by_year}")
    return EXIT_DATA_ERROR if failed else EXIT_OK


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
    _err(f"{mode} is not implemented yet (M0 scaffold)")
    return EXIT_NOT_IMPLEMENTED


if __name__ == "__main__":
    sys.exit(main())
