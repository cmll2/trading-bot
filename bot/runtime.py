"""Dry-run wiring and the engine loop (FR-11, FR-38, AD-1, AD-2, AD-8, AD-9, AD-17, AD-29).

``build_dry_run`` composes the SAME ``Engine`` as the backtest with the dry-run adapters:
``PaperBroker`` (live public bid/ask, public market rules, fills through the shared fill
model on live closed 15m candles), ``SystemClock``, ``CcxtMarketData`` and a file store
``var/state/dry-run-<strategy>.sqlite``. No API key, no ``load_secrets`` call: only public,
unauthenticated ccxt endpoints are used.

``run_loop`` is the process lifecycle:

1. take the engine lock ``<store>.lock`` (O_EXCL, holds the PID; a stale lock whose PID is
   gone is taken over, a live one refuses the start: one engine per store, AD-17);
2. check the clock against Kraken's public server time; refuse to start beyond
   ``MAX_CLOCK_SKEW`` (AD-2, audit M1 F-4);
3. ``engine.start`` (run row with PID), ``engine.recover`` (AD-8 startup sequence),
   ``engine.reconcile`` (AD-9: a mismatch halts and the process exits non-zero);
4. tick on the ``execution.tick_seconds`` grid: heartbeat, ``engine.tick``; every hour
   re-check the clock (a skew halts with rule ``clock_skew``) and reconcile; after more
   than ``SLEEP_GAP`` without a tick (sleep/hibernation) reconcile at once (AD-29);
5. a stop request (CTRL+C, CTRL_BREAK, or the stop file written by ``bot stop``) is
   honoured between ticks: the tick in progress finishes, state is committed, the run's
   ``stop_reason`` is written and the lock released (graceful stop, AD-29). A fatal error
   first cancels the bot's resting orders (best effort), then records ``stop_reason`` and
   exits non-zero.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from bot.backtest.provenance import config_hash, git_commit, git_dirty, limits_hash
from bot.broker.base import FeeRates
from bot.broker.errors import RateLimited, TransientReadError
from bot.broker.paper import PaperBroker
from bot.clock import Clock
from bot.config import TIMEFRAME_SECONDS, Settings
from bot.data.live import CcxtMarketData, LiveFeed
from bot.engine import Engine, EngineConfig, ReconcileMismatch
from bot.risk.kill_switch import kill_switch_engaged
from bot.store import Store, iso
from bot.strategy.base import Mode
from bot.strategy.registry import build

log = logging.getLogger("bot.runtime")

MAX_CLOCK_SKEW = timedelta(seconds=5)  # AD-2
CHECK_EVERY = timedelta(hours=1)  # AD-2 skew re-check and AD-9 reconciliation
SLEEP_GAP = timedelta(minutes=10)  # AD-29: a longer gap between ticks re-runs reconcile

EXIT_OK = 0
EXIT_FATAL = 1
EXIT_REFUSED = 2


class StartRefused(RuntimeError):
    """The engine must not start (lock held, clock skew, ...); the message says why."""


# --- paths -------------------------------------------------------------------------------


def store_path(settings: Settings, mode: Mode, strategy_id: str) -> Path:
    return Path(settings.paths.var_dir) / "state" / f"{mode}-{strategy_id}.sqlite"


def lock_path(db: Path) -> Path:
    return db.with_name(db.name + ".lock")


def stop_path(db: Path) -> Path:
    return db.with_name(db.name + ".stop")


def log_path(settings: Settings, mode: Mode, strategy_id: str) -> Path:
    return Path(settings.paths.var_dir) / "logs" / f"{mode}-{strategy_id}.log"


# --- engine lock (AD-17) -----------------------------------------------------------------


def pid_alive(pid: int) -> bool:
    """True if a process with ``pid`` exists. Never signals the process (on Windows
    ``os.kill(pid, 0)`` would terminate it), so Windows uses OpenProcess."""
    if pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        process_query_limited_information = 0x1000
        still_active = 259
        handle = kernel32.OpenProcess(process_query_limited_information, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # ERROR_ACCESS_DENIED: exists, not ours
        try:
            code = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
                return True
            return code.value == still_active
        finally:
            kernel32.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class EngineLock:
    """``<store>.lock`` created with O_EXCL, holding the owner's PID."""

    def __init__(
        self, path: Path, pid: int | None = None, alive: Callable[[int], bool] = pid_alive
    ):
        self.path = Path(path)
        self.pid = os.getpid() if pid is None else pid
        self._alive = alive
        self.held = False

    def holder(self) -> int | None:
        try:
            return int(self.path.read_text(encoding="utf-8").strip() or "0")
        except (OSError, ValueError):
            return None

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        for _ in range(2):
            try:
                fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
            except FileExistsError:
                holder = self.holder()
                if holder is not None and holder != self.pid and self._alive(holder):
                    raise StartRefused(
                        f"another engine (PID {holder}) holds {self.path}; one engine per store"
                    ) from None
                if not holder and self._young():
                    # Empty: another process created it and is writing its PID right now.
                    raise StartRefused(f"{self.path} is being taken by another engine") from None
                log.warning("taking over stale engine lock %s (PID %s gone)", self.path, holder)
                self.path.unlink(missing_ok=True)
                continue
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(str(self.pid))
            self.held = True
            return
        raise StartRefused(f"could not acquire {self.path}")

    def _young(self, seconds: float = 30.0) -> bool:
        try:
            age = self._clock_now() - self.path.stat().st_mtime
        except OSError:
            return False
        return age < seconds

    @staticmethod
    def _clock_now() -> float:
        from bot.clock import SystemClock

        return SystemClock().now().timestamp()

    def release(self) -> None:
        if self.held and self.holder() == self.pid:
            self.path.unlink(missing_ok=True)
        self.held = False


# --- recorders -----------------------------------------------------------------------------


class StoreRecorder:
    """Writes each public API call to ``api_calls`` (NFR-05), never raising into the
    caller: a health record must not break trading."""

    def __init__(self, clock: Clock) -> None:
        self.clock = clock
        self.store: Store | None = None

    def __call__(
        self, endpoint: str, latency_ms: int, ok: bool, limited: bool, detail: dict | None
    ) -> None:
        if self.store is None:
            return
        import json

        try:
            self.store.insert(
                "api_calls",
                at=iso(self.clock.now()),
                endpoint=endpoint,
                latency_ms=int(latency_ms),
                ok=int(ok),
                rate_limited=int(limited),
                detail_json=None if detail is None else json.dumps(detail, sort_keys=True),
            )
        except Exception:  # noqa: BLE001 - health record only
            log.exception("could not record api call %s", endpoint)
        if limited:
            log.warning("rate limited on %s", endpoint)


# --- wiring --------------------------------------------------------------------------------


@dataclass
class DryRun:
    settings: Settings
    strategy_id: str
    db_path: Path
    store: Store
    engine: Engine
    feed: LiveFeed
    clock: Clock
    approval: str
    tick: timedelta
    extra: dict[str, Any] = field(default_factory=dict)


def engine_config(
    settings: Settings,
    pair: str,
    strategy,  # noqa: ANN001 - Strategy
    quote: str,
    mode: Mode,
    approval: Literal["manual", "autonomous"],
) -> EngineConfig:
    ex = settings.execution
    window = timedelta(hours=ex.window_hours)
    reprice = timedelta(minutes=ex.reprice_interval_minutes)
    completion = timedelta(hours=ex.completion_window_hours)
    if strategy.id == "plumbing":  # AD-30: its own execution timings, window <= timeframe
        p = settings.plumbing
        window = timedelta(minutes=p.window_minutes)
        reprice = timedelta(minutes=p.reprice_interval_minutes)
        completion = timedelta(minutes=p.completion_window_minutes)
    if window > timedelta(seconds=TIMEFRAME_SECONDS[strategy.timeframe]):
        raise StartRefused("execution window longer than the strategy timeframe (AD-5)")
    return EngineConfig(
        mode=mode,
        pair=pair,
        timeframe=strategy.timeframe,
        window=window,
        reprice_interval=reprice,
        completion_window=completion,
        approval=approval,
        slippage_bps=settings.slippage_bps,
        quote_is_fiat=quote in settings.fiat_currencies,
        git_commit=git_commit(),
        git_dirty=git_dirty(),
        config_hash=config_hash(settings),
        limits_hash=limits_hash(settings),
        fill_settle_timeout=timedelta(seconds=ex.fill_settle_timeout_seconds),
        unknown_grace=timedelta(seconds=ex.unknown_grace_seconds),
        exec_timeframe=ex.sim_timeframe,
    )


def build_dry_run(
    settings: Settings,
    strategy_id: str,
    exchange: Any,
    clock: Clock,
    *,
    approval: Literal["manual", "autonomous"] | None = None,
    db_path: Path | None = None,
) -> DryRun:
    """Compose Engine(PaperBroker, clock, CcxtMarketData, file store) for dry-run."""
    strategy = build(strategy_id, _params(settings, strategy_id), "dry-run")
    pair = settings.pairs[0]
    db = db_path or store_path(settings, "dry-run", strategy_id)
    db.parent.mkdir(parents=True, exist_ok=True)
    recorder = StoreRecorder(clock)
    feed = LiveFeed(exchange, clock, recorder)
    md = CcxtMarketData(exchange, clock, (pair,), recorder)
    rules = feed.market_rules(pair)
    store = Store.open(db)
    recorder.store = store
    meta_strategy = store.get_meta("strategy_id")
    if meta_strategy is not None and meta_strategy != strategy_id:
        store.close()
        raise StartRefused(f"{db} belongs to strategy {meta_strategy}, not {strategy_id}")
    fees = FeeRates(settings.fees.maker, settings.fees.taker, source="config")
    broker = PaperBroker(
        store,
        md,
        clock,
        rules,
        fees,
        slippage_bps=settings.slippage_bps,
        half_spread_bps=settings.execution.sim_half_spread_bps,
        initial_quote=settings.paper.initial_quote,
        exec_timeframe=settings.execution.sim_timeframe,
        ticker_source=feed.ticker,
        rules_source=feed.market_rules,
    )
    mode_approval = approval or settings.execution.approval
    kill_path = settings.risk.kill_switch_path
    engine = Engine(
        broker,
        clock,
        md,
        store,
        strategy,
        settings.risk,
        engine_config(settings, pair, strategy, rules.quote, "dry-run", mode_approval),
        kill_switch=lambda: kill_switch_engaged(kill_path),
        kill_switch_path=kill_path,
    )
    return DryRun(
        settings=settings,
        strategy_id=strategy_id,
        db_path=db,
        store=store,
        engine=engine,
        feed=feed,
        clock=clock,
        approval=mode_approval,
        tick=timedelta(seconds=settings.execution.tick_seconds),
    )


def _params(settings: Settings, strategy_id: str) -> dict[str, int]:
    if strategy_id == "plumbing":
        p = settings.plumbing
        return {"flip_hours": p.flip_hours, "target_pct": p.target_pct}
    return dict(settings.strategy.params)


# --- clock skew (AD-2, audit M1 F-4) --------------------------------------------------------


def measure_skew(feed: LiveFeed) -> float:
    return feed.server_time().skew_seconds


# --- stop handling ---------------------------------------------------------------------------


class StopFlag:
    """Set by CTRL+C / CTRL_BREAK handlers or by the stop file; checked between ticks."""

    def __init__(self, stop_file: Path | None = None) -> None:
        self.reason: str | None = None
        self.stop_file = stop_file

    def set(self, reason: str) -> None:
        if self.reason is None:
            self.reason = reason

    def check(self) -> bool:
        if self.reason is None and self.stop_file is not None and self.stop_file.exists():
            self.set(f"stop file {self.stop_file.name}")
        return self.reason is not None

    def install_signal_handlers(self) -> None:
        def _handler(signum: int, _frame: object) -> None:
            self.set(f"signal {signal.Signals(signum).name}")

        signal.signal(signal.SIGINT, _handler)
        if hasattr(signal, "SIGBREAK"):  # Windows CTRL_BREAK
            signal.signal(signal.SIGBREAK, _handler)
        if hasattr(signal, "SIGTERM"):
            signal.signal(signal.SIGTERM, _handler)


def _next_tick(now: datetime, step: timedelta) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return epoch + ((now - epoch) // step + 1) * step


def _sleep_until(clock: Clock, t: datetime, stop: StopFlag) -> None:
    """Sleep in slices of at most 1 s so a stop request is honoured promptly."""
    while not stop.check():
        now = clock.now()
        if now >= t:
            return
        clock.sleep_until(min(t, now + timedelta(seconds=1)))


# --- the loop ---------------------------------------------------------------------------------


@dataclass
class LoopResult:
    exit_code: int
    stop_reason: str
    ticks: int


def run_loop(
    dry: DryRun,
    stop: StopFlag,
    *,
    max_ticks: int | None = None,
    lock: EngineLock | None = None,
    skew: Callable[[], float] | None = None,
    on_start=None,  # noqa: ANN001 - logging ContextFilter: receives run_id
) -> LoopResult:
    engine, clock = dry.engine, dry.clock
    lock = lock or EngineLock(lock_path(dry.db_path))
    skew = skew or (lambda: measure_skew(dry.feed))
    ticks = 0
    try:
        if not lock.held:
            lock.acquire()
        try:
            offset = _startup(dry, stop, lock, skew, on_start)
        except (TransientReadError, RateLimited) as exc:
            # The exchange cannot be reached at startup: refuse (a supervisor retries);
            # this is not a fault of the bot's state, so no halt is written.
            raise StartRefused(f"public market data unreachable at startup: {exc}") from exc
        log.info(
            "dry-run running: strategy=%s approval=%s store=%s run_id=%s clock_skew=%+.2fs "
            "(SIMULATED: paper broker, public data only)",
            dry.strategy_id, dry.approval, dry.db_path, engine.run_id, offset,
        )  # fmt: skip
        last_check = last_tick = clock.now()
        while not stop.check():
            if max_ticks is not None and ticks >= max_ticks:
                stop.set("max ticks reached")
                break
            _sleep_until(clock, _next_tick(clock.now(), dry.tick), stop)
            if stop.check():
                break
            now = clock.now()
            gap = now - last_tick
            engine.heartbeat(now, "tick")
            if (now - last_check >= CHECK_EVERY or gap > SLEEP_GAP) and _hourly_checks(
                engine, skew, now, gap
            ):
                # Before the tick: after a sleep, reconcile before anything can trade.
                last_check = now
            _tick_once(engine, now)
            ticks += 1
            last_tick = now
        reason = stop.reason or "stopped"
        engine.heartbeat(clock.now(), "stopped")
        engine.stop(f"graceful stop: {reason}")
        log.info("dry-run stopped gracefully: %s", reason)
        return LoopResult(EXIT_OK, reason, ticks)
    except StartRefused as exc:
        log.error("REFUSED: %s", exc)
        if engine.run_id is not None and lock.held:
            engine.stop(f"refused: {exc}")
        return LoopResult(EXIT_REFUSED, str(exc), ticks)
    except ReconcileMismatch as exc:
        log.error("RECONCILIATION MISMATCH, halted: %s", exc)
        engine.stop(f"reconcile mismatch: {exc}")
        return LoopResult(EXIT_FATAL, f"reconcile mismatch: {exc}", ticks)
    except Exception as exc:  # noqa: BLE001 - any unhandled error is fatal (AD-29)
        if not lock.held:
            log.error("FATAL before the engine lock was held: %s: %s", type(exc).__name__, exc)
            return LoopResult(EXIT_FATAL, f"fatal: {exc}", ticks)
        return _fatal(engine, clock, exc, ticks)
    finally:
        lock.release()


def _startup(dry: DryRun, stop: StopFlag, lock: EngineLock, skew, on_start) -> float:  # noqa: ANN001
    """Skew check, run row, AD-8 recovery and AD-9 reconciliation, in that order."""
    engine, clock = dry.engine, dry.clock
    offset = skew()
    if abs(offset) > MAX_CLOCK_SKEW.total_seconds():
        raise StartRefused(
            f"local clock differs from Kraken server time by {offset:+.1f} s "
            f"(> {MAX_CLOCK_SKEW.total_seconds():.0f} s): fix the system clock (AD-2)"
        )
    if stop.stop_file is not None:
        stop.stop_file.unlink(missing_ok=True)  # an old stop request never blocks a start
    engine.start(pid=lock.pid)
    if on_start is not None:
        on_start.run_id = engine.run_id
    engine.heartbeat(clock.now(), "starting")
    engine.recover(clock.now())
    engine.reconcile(clock.now())
    return offset


def _tick_once(engine: Engine, now: datetime) -> None:
    """One tick; transient read failures and rate limits are recorded and the loop goes on
    (Conventions: Errors). Anything else propagates and is fatal."""
    try:
        engine.tick()
    except RateLimited as exc:
        engine.error(now, "tick", exc)
        engine.clock.sleep_until(engine.clock.now() + timedelta(seconds=exc.retry_after_s))
    except TransientReadError as exc:
        engine.error(now, "tick", exc)


def _hourly_checks(
    engine: Engine, skew: Callable[[], float], now: datetime, gap: timedelta
) -> bool:
    """Hourly (and after-sleep) skew check and reconciliation. Returns False when the
    exchange could not be read: the error is recorded and the checks run again on the
    next tick (a network blip is never a fatal state)."""
    try:
        offset = skew()
    except (TransientReadError, RateLimited) as exc:
        engine.error(now, "clock_skew", exc)
        return False
    if abs(offset) > MAX_CLOCK_SKEW.total_seconds():
        engine.raise_halt(
            now,
            "clock_skew",
            f"local clock differs from Kraken server time by {offset:+.1f} s (AD-2)",
            kind="stale_data",
        )
    if gap > SLEEP_GAP:
        log.warning("%.0f s since the previous tick (sleep?): reconciling", gap.total_seconds())
    try:
        engine.reconcile(now)
    except (TransientReadError, RateLimited) as exc:
        engine.error(now, "reconcile", exc)
        return False
    return True


def _fatal(engine: Engine, clock: Clock, exc: BaseException, ticks: int) -> LoopResult:
    now = clock.now()
    log.error("FATAL: %s: %s", type(exc).__name__, exc)
    try:
        engine.error(now, "fatal", exc, tb="".join(traceback.format_exception(exc)))
        engine.fatal(now, f"{type(exc).__name__}: {exc}")
    except Exception:  # noqa: BLE001 - best effort on the way out
        log.exception("fatal-exit cleanup failed")
    if engine.run_id is not None:
        try:
            engine.stop(f"fatal: {type(exc).__name__}: {exc}"[:500])
        except Exception:  # noqa: BLE001
            log.exception("could not record stop_reason")
    return LoopResult(EXIT_FATAL, f"fatal: {exc}", ticks)


__all__ = [
    "DryRun",
    "EngineLock",
    "LoopResult",
    "StartRefused",
    "StopFlag",
    "build_dry_run",
    "run_loop",
    "store_path",
]
