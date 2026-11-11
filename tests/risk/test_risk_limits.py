"""Tests for the protected risk limits (SAF-04, SAF-05, AD-10). PROTECTED."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from bot.risk.limits import RiskLimits

REPO_ROOT = Path(__file__).resolve().parents[2]

# Values adopted in PROGRESS.md (decisions log, 2026-11-11; trade-count caps raised to
# runaway-bug backstops on the operator's explicit request the same day).
EXPECTED = {
    "max_position_fraction": Decimal("1.00"),
    "max_position_abs_quote": Decimal("25"),
    "max_order_intents_per_day": 20,
    "max_exchange_submissions_per_day": 120,
    "max_submissions_per_intent": 12,
    "max_daily_loss_fraction": Decimal("0.10"),
    "max_total_drawdown_fraction": Decimal("0.25"),
    "stale_candle_intervals": 2,
    "stale_ticker_seconds": 120,
    "price_sanity_fraction": Decimal("0.02"),
}


def _repo_risk_section() -> dict:
    with (REPO_ROOT / "config.yaml").open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)["risk"]


def _limits() -> RiskLimits:
    return RiskLimits.model_validate(_repo_risk_section())


def test_config_yaml_risk_values_match_progress_md() -> None:
    limits = _limits()
    for name, value in EXPECTED.items():
        assert getattr(limits, name) == value, name
    assert limits.kill_switch_path == Path("var/KILL")


def test_risk_section_has_exactly_the_expected_keys() -> None:
    assert set(_repo_risk_section()) == set(EXPECTED) | {"kill_switch_path"}


def test_risk_limits_are_frozen() -> None:
    limits = _limits()
    with pytest.raises(ValidationError):
        limits.max_position_abs_quote = Decimal("1000")  # type: ignore[misc]
    with pytest.raises(ValidationError):
        limits.max_order_intents_per_day = 100  # type: ignore[misc]
    assert limits.max_position_abs_quote == Decimal("25")


def test_unknown_risk_key_is_refused() -> None:
    section = _repo_risk_section() | {"max_leverage": 10}
    with pytest.raises(ValidationError):
        RiskLimits.model_validate(section)


def test_missing_risk_key_is_refused() -> None:
    section = _repo_risk_section()
    del section["max_daily_loss_fraction"]
    with pytest.raises(ValidationError):
        RiskLimits.model_validate(section)


@pytest.mark.parametrize(
    ("key", "bad"),
    [
        ("max_position_fraction", "1.5"),
        ("max_position_fraction", "0"),
        ("max_position_abs_quote", "-1"),
        ("max_order_intents_per_day", 0),
        ("max_exchange_submissions_per_day", -3),
        ("max_submissions_per_intent", 0),
        ("max_daily_loss_fraction", "1"),
        ("max_total_drawdown_fraction", "0"),
        ("stale_candle_intervals", 0),
        ("stale_ticker_seconds", 0),
        ("price_sanity_fraction", "1"),
    ],
)
def test_out_of_range_risk_values_are_refused(key: str, bad: object) -> None:
    section = _repo_risk_section() | {key: bad}
    with pytest.raises(ValidationError):
        RiskLimits.model_validate(section)


@pytest.mark.parametrize(
    "key",
    [
        "max_order_intents_per_day",
        "max_exchange_submissions_per_day",
        "max_submissions_per_intent",
        "stale_candle_intervals",
        "stale_ticker_seconds",
    ],
)
@pytest.mark.parametrize("bad", [True, 4.0, "4"])
def test_integer_limits_are_strict(key: str, bad: object) -> None:
    # Audit M0 F-11: a YAML typo such as `true` or `4.0` must not become a valid limit.
    section = _repo_risk_section() | {key: bad}
    with pytest.raises(ValidationError):
        RiskLimits.model_validate(section)


def test_per_intent_cap_cannot_exceed_daily_cap() -> None:
    section = _repo_risk_section()
    section["max_submissions_per_intent"] = section["max_exchange_submissions_per_day"] + 1
    with pytest.raises(ValidationError, match="max_submissions_per_intent"):
        RiskLimits.model_validate(section)
