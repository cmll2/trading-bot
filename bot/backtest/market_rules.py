"""Exchange minimums and precision for the backtest, from a recorded public snapshot.

Live and dry-run read ``MarketRules`` from the exchange (``load_markets``, CON-03). A
backtest must not call the network, so it reads ``kraken_market_snapshot.json``: Kraken's
public AssetPairs metadata as returned by ccxt ``load_markets`` on ``fetched_at``. Nothing
is hardcoded in code; the fetch date is reported with every result.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from bot.broker.base import MarketRules

SNAPSHOT_PATH = Path(__file__).resolve().parent / "kraken_market_snapshot.json"


@dataclass(frozen=True)
class RulesSnapshot:
    rules: MarketRules
    fetched_at: str
    source: str


def load_rules_snapshot(pair: str, path: Path = SNAPSHOT_PATH) -> RulesSnapshot:
    raw = json.loads(path.read_text(encoding="utf-8"))
    try:
        m = raw["markets"][pair]
    except KeyError as exc:
        raise ValueError(f"no market metadata for {pair} in {path.name}") from exc
    rules = MarketRules(
        pair=pair,
        base=m["base"],
        quote=m["quote"],
        amount_min=Decimal(m["limits"]["amount_min"]),
        cost_min=Decimal(m["limits"]["cost_min"]),
        tick_size=Decimal(m["precision"]["price"]),
        amount_step=Decimal(m["precision"]["amount"]),
        status=m["status"],
    )
    for name in ("amount_min", "cost_min", "tick_size", "amount_step"):
        if not getattr(rules, name) > 0:
            raise ValueError(f"{pair} {name} must be > 0 in {path.name}")
    return RulesSnapshot(rules=rules, fetched_at=raw["fetched_at"], source=raw["source"])
