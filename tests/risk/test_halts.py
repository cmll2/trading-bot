"""Daily-loss and total-drawdown halt evaluation (FR-33, AD-11, GL-03). PROTECTED."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal
from pathlib import Path

import yaml

from bot.risk.halts import HaltContext, evaluate_halts
from bot.risk.limits import RiskLimits

REPO_ROOT = Path(__file__).resolve().parents[2]

with (REPO_ROOT / "config.yaml").open("r", encoding="utf-8") as _fh:
    LIMITS = RiskLimits.model_validate(yaml.safe_load(_fh)["risk"])

CTX = HaltContext(
    equity=Decimal("20"), day_open_equity=Decimal("20"), baseline_equity=Decimal("20")
)


def _rules(ctx: HaltContext) -> list[str]:
    return [t.rule for t in evaluate_halts(ctx, LIMITS)]


def test_no_halt_at_baseline() -> None:
    assert _rules(CTX) == []


def test_daily_loss_triggers_at_ten_percent_below_day_open() -> None:
    assert _rules(replace(CTX, equity=Decimal("18"))) == ["daily_loss"]  # exactly 90%
    assert _rules(replace(CTX, equity=Decimal("18.0001"))) == []


def test_total_drawdown_triggers_at_twenty_five_percent_below_baseline() -> None:
    ctx = HaltContext(
        equity=Decimal("15"), day_open_equity=Decimal("15.5"), baseline_equity=Decimal("20")
    )
    assert _rules(ctx) == ["total_drawdown"]
    assert _rules(replace(ctx, equity=Decimal("15.01"))) == []


def test_both_halts_can_trigger_together_with_reasons() -> None:
    triggers = evaluate_halts(replace(CTX, equity=Decimal("10")), LIMITS)
    assert [t.rule for t in triggers] == ["daily_loss", "total_drawdown"]
    assert all(t.reason for t in triggers)


def test_evaluation_is_stateless_recovery_returns_no_trigger() -> None:
    # A halt never auto-expires: the engine keeps it active in the store until a manual
    # reset; evaluate_halts itself only reports the current breach (see check_order's
    # ``halt`` rule for the persistence side).
    assert _rules(replace(CTX, equity=Decimal("10"))) != []
    assert _rules(CTX) == []
