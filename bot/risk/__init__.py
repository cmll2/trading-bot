"""Risk manager: pre-trade checks, halts and kill switch (FR-30 to FR-37, AD-10 to AD-12).

PROTECTED (SAF-04). Pure core: imports nothing from broker/, engine, store, data/ or any
network library (architecture dependency rule).

Modules:
    limits       RiskLimits, the frozen model of config.yaml ``risk:`` (M0)
    checks       check_order(...) -> RiskDecision (M3)
    halts        evaluate_halts(...) (M3)
    kill_switch  kill_switch_engaged / engage (M3)
"""

from bot.risk.limits import RiskLimits

__all__ = ["RiskLimits"]
