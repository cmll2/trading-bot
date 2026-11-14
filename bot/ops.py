"""Operator side of the store: ``bot status`` (read-only) and the commands that write
``operator_actions`` (AD-16, AD-17, AD-25, SAF-05).

The CLI never writes any other table and never touches a limit: it inserts one
``operator_actions`` row, and the running engine consumes it (sets ``consumed_at`` and
``result``) on its next tick. The only file the CLI creates is the kill switch (through
``risk.kill_switch.engage``) and the stop request file of a running engine.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

from bot.risk.kill_switch import read_kill_switch
from bot.store import Store, StoreError, iso, parse_iso

ACTION_KINDS = ("approve", "reject", "reset_halt", "flatten", "kill_on", "kill_off")


def write_action(
    db: Path,
    now: datetime,
    kind: str,
    note: str,
    target_id: str | None = None,
    rebase_baseline: bool = False,
) -> int:
    """Insert one operator action into an existing store; returns its id."""
    if kind not in ACTION_KINDS:
        raise ValueError(f"unknown operator action {kind!r}")
    if not note.strip():
        raise ValueError("a --note is required for every operator action")
    if not Path(db).is_file():
        raise StoreError(f"no store at {db}: start the engine once first")
    store = Store.open_existing(db)  # never creates or migrates (AD-17)
    try:
        with store.transaction():
            return store.insert(
                "operator_actions",
                at=iso(now),
                kind=kind,
                target_id=target_id,
                note=note.strip(),
                rebase_baseline=int(rebase_baseline),
            )
    finally:
        store.close()


@dataclass(frozen=True)
class Status:
    lines: list[str]
    healthy: bool


def status(db: Path, now: datetime, tick_seconds: int, kill_path: Path, pid_alive=None) -> Status:  # noqa: ANN001
    """Human-readable state of one store. Healthy = a heartbeat within 3 ticks."""
    store = Store.open_readonly(db)
    try:
        return _status(store, db, now, tick_seconds, kill_path, pid_alive)
    finally:
        store.close()


def _status(store, db, now, tick_seconds, kill_path, pid_alive):  # noqa: ANN001, ANN202
    mode = store.get_meta("mode") or "?"
    label = "LIVE" if mode == "live" else f"{mode.upper()} (SIMULATED)"
    sid = store.get_meta("strategy_id")
    tag = " (plumbing — no edge)" if sid == "plumbing" else ""
    out = [f"MODE: {label}   strategy={sid}{tag}   store={db}"]
    run = store.one("SELECT * FROM runs ORDER BY run_id DESC")
    healthy = False
    if run is None:
        out.append("no run recorded yet")
    else:
        alive = None if pid_alive is None else pid_alive(int(run["pid"]))
        state = "stopped" if run["stopped_at"] else "running" if alive is not False else "DEAD"
        out.append(
            f"run {run['run_id']}: pid={run['pid']} ({state}) started={run['started_at']} "
            f"commit={run['git_commit'][:12]}{' (dirty)' if run['git_dirty'] else ''}"
        )
        if run["stopped_at"]:
            out.append(f"  stopped={run['stopped_at']} reason={run['stop_reason']}")
        hb = store.one(
            "SELECT at, loop_state FROM heartbeats WHERE run_id = ? ORDER BY at DESC",
            (run["run_id"],),
        )
        if hb is None:
            out.append("  last heartbeat: none")
        else:
            age = (now - parse_iso(hb["at"])).total_seconds()
            healthy = run["stopped_at"] is None and age <= 3 * tick_seconds and alive is not False
            out.append(
                f"  last heartbeat: {hb['at']} ({age:.0f} s ago, state {hb['loop_state']}) -> "
                f"{'HEALTHY' if healthy else 'NOT HEALTHY'}"
            )
        n_hb = store.one("SELECT count(*) FROM heartbeats WHERE run_id = ?", (run["run_id"],))[0]
        out.append(f"  heartbeats this run: {n_hb}")
    ks = read_kill_switch(kill_path)
    out.append(f"kill switch: {'ENGAGED (source=' + str(ks.source) + ')' if ks.engaged else 'off'}")
    halts = store.all("SELECT rule, triggered_at, reason FROM halts WHERE reset_at IS NULL")
    out.append("halts: " + ("none" if not halts else ""))
    for h in halts:
        out.append(f"  ACTIVE {h['rule']} since {h['triggered_at']}: {h['reason']}")
    snap = store.one("SELECT * FROM equity_snapshots ORDER BY at DESC")
    if snap is not None:
        out.append(
            f"equity (SIMULATED) {Decimal(snap['equity']):.4f} {store.get_meta('quote_ccy')} "
            f"cash {Decimal(snap['cash']):.4f} base {snap['base_qty']} mark {snap['mark_price']} "
            f"at {snap['at']}"
        )
    intent = store.one(
        "SELECT * FROM intents WHERE state IN ('awaiting_approval','working','completing')"
    )
    if intent is not None:
        out.append(
            f"active intent {intent['intent_id']}: {intent['side']} {intent['target_qty']} "
            f"state={intent['state']} window_end={intent['window_end_at']}"
            + (" flatten" if intent["is_flatten"] else "")
        )
    counts = {
        t: store.one(f"SELECT count(*) FROM {t}")[0]  # noqa: S608
        for t in ("signals", "intents", "orders", "fills")
    }
    out.append("counts: " + " ".join(f"{k}={v}" for k, v in counts.items()))
    day_ago = iso(now - timedelta(hours=24))
    errs = store.one("SELECT count(*) FROM errors WHERE at >= ?", (day_ago,))[0]
    errs_all = store.one("SELECT count(*) FROM errors")[0]
    mism = store.one("SELECT count(*) FROM risk_events WHERE kind = 'reconcile_mismatch'")[0]
    rl = store.one("SELECT count(*) FROM api_calls WHERE rate_limited = 1 AND at >= ?", (day_ago,))[
        0
    ]
    lat = store.one(
        "SELECT avg(latency_ms), max(latency_ms), count(*) FROM api_calls WHERE at >= ?",
        (day_ago,),
    )
    out.append(f"errors: {errs} in 24 h ({errs_all} total)   reconcile mismatches: {mism}")
    if lat[2]:
        out.append(
            f"api (24 h): {lat[2]} calls, latency avg {lat[0]:.0f} ms max {lat[1]} ms, "
            f"rate-limited {rl}"
        )
    last_err = store.one("SELECT at, component, error_type, message FROM errors ORDER BY at DESC")
    if last_err is not None:
        out.append(
            f"last error: {last_err['at']} {last_err['component']} {last_err['error_type']}: "
            f"{last_err['message'][:160]}"
        )
    pending = store.all("SELECT action_id, kind FROM operator_actions WHERE consumed_at IS NULL")
    if pending:
        out.append("pending operator actions: " + json.dumps([dict(r) for r in pending]))
    return Status(out, healthy)
