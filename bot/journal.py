"""Signal journal view with a would-have-returned estimate for untraded signals (FR-40).

Read-only over a store. Every signal is listed with its outcome. For a signal that asked
for a trade that did not happen (``not_filled``, ``rejected_by_risk``,
``skipped_by_operator``, ``below_minimum``, ``halted``) the view estimates what the
intended trade would have returned: entry at the signal's close (the next candle's open
in the model), exit at the close of the next signal whose target differs (or the latest
equity mark while no such signal exists yet, shown as ``open``), at the maker fee on both
legs. A buy that did not happen returns ``exit/entry`` net of fees; a sell that did not
happen returns what selling and buying back would have saved.

This is an estimate on the journal's own prices, labelled SIMULATED. The authoritative
counterfactual (from the t+1 open on the cached candles, AD-20) is written by ``bot
review`` (M4) into ``signal_counterfactuals``; this module writes nothing (AD-17).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from bot.store import Store

UNTRADED = frozenset(
    {"not_filled", "rejected_by_risk", "skipped_by_operator", "below_minimum", "halted"}
)


@dataclass(frozen=True)
class JournalRow:
    candle_open_at: str
    target: Decimal
    price: Decimal
    outcome: str
    reason: str | None
    would_have_returned: Decimal | None
    exit_kind: str | None  # "closed" | "open" | None


def would_have_returned(side: str, entry: Decimal, exit_price: Decimal, fee: Decimal) -> Decimal:
    """Return of the intended trade between ``entry`` and ``exit_price`` after the maker
    fee on both legs. ``side`` is the intended trade: buy (go long) or sell (go flat)."""
    if side == "buy":
        return exit_price * (1 - fee) / (entry * (1 + fee)) - 1
    return entry * (1 - fee) / (exit_price * (1 + fee)) - 1


def rows(store: Store, fee: Decimal = Decimal("0.004")) -> list[JournalRow]:
    signals = store.all(
        "SELECT s.*, i.side AS intent_side FROM signals s "
        "LEFT JOIN intents i ON i.signal_id = s.signal_id ORDER BY s.candle_open_at"
    )
    mark = store.one("SELECT mark_price FROM equity_snapshots ORDER BY at DESC")
    out: list[JournalRow] = []
    for n, s in enumerate(signals):
        target = Decimal(s["target_fraction"])
        price = Decimal(s["signal_price"])
        ret: Decimal | None = None
        kind: str | None = None
        if s["outcome"] in UNTRADED:
            side = s["intent_side"] or ("buy" if target > 0 else "sell")
            later = next(
                (x for x in signals[n + 1 :] if Decimal(x["target_fraction"]) != target), None
            )
            if later is not None:
                ret, kind = (
                    would_have_returned(side, price, Decimal(later["signal_price"]), fee),
                    "closed",
                )
            elif mark is not None:
                ret, kind = (
                    would_have_returned(side, price, Decimal(mark["mark_price"]), fee),
                    "open",
                )
        out.append(
            JournalRow(
                s["candle_open_at"], target, price, s["outcome"], s["outcome_reason"], ret, kind
            )
        )
    return out


def render(db: Path, limit: int = 30, fee: Decimal = Decimal("0.004")) -> list[str]:
    store = Store.open_readonly(db)
    try:
        mode = store.get_meta("mode") or "?"
        sid = store.get_meta("strategy_id") or "?"
        data = rows(store, fee)
    finally:
        store.close()
    label = "LIVE" if mode == "live" else "SIMULATED"
    if sid == "plumbing":
        label += ", plumbing — no edge"
    lines = [
        f"SIGNAL JOURNAL {sid} ({label}; would-have-returned is an estimate at the maker fee "
        f"{fee}, authoritative counterfactuals come from bot review)",
        f"{'candle_open_at':26} {'target':>6} {'price':>12} {'outcome':20} would-have-returned",
    ]
    for r in data[-limit:]:
        whr = (
            ""
            if r.would_have_returned is None
            else f"{r.would_have_returned * 100:+.2f}% ({r.exit_kind})"
        )
        lines.append(
            f"{r.candle_open_at:26} {r.target:>6} {r.price:>12} {r.outcome:20} {whr}"
            + (f"  [{r.reason}]" if r.reason else "")
        )
    return lines
