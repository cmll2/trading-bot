"""Typed settings loaded from config.yaml + .env (brief §5, architecture Conventions: Config).

- ``config.yaml`` -> one frozen pydantic ``Settings``, loaded once by ``cli.py`` and passed down.
- The ``risk:`` section becomes the frozen ``bot.risk.limits.RiskLimits`` (SAF-04, SAF-05,
  AD-10). Nothing in this module (or anywhere in the bot) writes the config file.
- ``.env`` holds ONLY the path to a secrets file stored outside the repository (SAF-01,
  AD-22). Its values are read with ``dotenv_values`` and never injected into ``os.environ``.
  Unknown keys are refused, so an API key pasted into ``.env`` stops the bot instead of
  being picked up silently.
- The live gate variable (``TRADING_BOT_LIVE``) must come from the shell of a live session,
  never from ``.env`` (SAF-09, AD-15); a non-empty value in ``.env`` is refused.
- The secrets file itself is never opened here. ``load_secrets()`` is implemented at M6
  and is never called in backtest or dry-run (AD-22, SAF-02).
"""

from __future__ import annotations

import os
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from bot.risk.limits import RiskLimits

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config.yaml"
DEFAULT_ENV_PATH = REPO_ROOT / ".env"

SECRETS_FILE_ENV = "TRADING_BOT_SECRETS_FILE"
LIVE_GATE_ENV = "TRADING_BOT_LIVE"
LIVE_GATE_VALUE = "I_ACCEPT_REAL_ORDERS"
ALLOWED_ENV_KEYS = frozenset({SECRETS_FILE_ENV, LIVE_GATE_ENV})

TIMEFRAME_SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "1d": 86400}


class ConfigError(ValueError):
    """Configuration is invalid or unsafe; the bot must not start."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ExchangeSettings(_Frozen):
    name: Literal["kraken"]  # CON-01


class StrategySettings(_Frozen):
    id: str
    timeframe: Literal["15m", "1h", "4h", "1d"]


class CapitalSettings(_Frozen):
    allocated_quote: Decimal = Field(gt=0)


class PaperSettings(_Frozen):
    initial_quote: Decimal = Field(gt=0)


class ExecutionSettings(_Frozen):
    """AD-5 execution model: post-only limit, re-priced within a window, then skip."""

    approval: Literal["manual", "autonomous"]  # AD-16
    window_hours: int = Field(gt=0)
    reprice_interval_minutes: int = Field(gt=0)
    # Submission caps (per intent and per day) live in the protected risk: section.


class BacktestSettings(_Frozen):
    holdout_start: date  # FR-15: fixed window, UTC, inclusive
    holdout_end: date

    @model_validator(mode="after")
    def _ordered(self) -> BacktestSettings:
        if self.holdout_end <= self.holdout_start:
            raise ValueError("backtest.holdout_end must be after holdout_start")
        return self


class ReviewSettings(_Frozen):
    gl02_max_fill_price_diff_fraction: Decimal = Field(gt=0, lt=1)  # GL-02
    gl02_max_equity_diff_pp: Decimal = Field(gt=0)


class PathSettings(_Frozen):
    var_dir: Path


class Settings(_Frozen):
    """All configuration. Frozen; built only by ``load_settings``."""

    exchange: ExchangeSettings
    pairs: tuple[str, ...]
    fiat_currencies: tuple[str, ...]
    strategy: StrategySettings
    capital: CapitalSettings
    paper: PaperSettings
    execution: ExecutionSettings
    slippage_bps: Decimal = Field(ge=0)
    backtest: BacktestSettings
    review: ReviewSettings
    paths: PathSettings
    risk: RiskLimits
    secrets_file: Path | None = None  # path only; the file is never read here

    @field_validator("pairs")
    @classmethod
    def _one_pair(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if len(v) != 1:
            raise ValueError("v1 supports exactly one pair in `pairs:`")
        if "/" not in v[0]:
            raise ValueError("pairs must be ccxt unified symbols such as BTC/EUR")
        return v

    @model_validator(mode="after")
    def _cross_checks(self) -> Settings:
        window_s = self.execution.window_hours * 3600
        if window_s > TIMEFRAME_SECONDS[self.strategy.timeframe]:
            raise ValueError("execution.window_hours must not exceed the strategy timeframe (AD-5)")
        if self.execution.reprice_interval_minutes * 60 > window_s:
            raise ValueError("execution.reprice_interval_minutes must fit in the window")
        return self


def _normcase(p: Path) -> str:
    return os.path.normcase(str(p.resolve()))


def is_inside(child: Path, parent: Path) -> bool:
    """True if ``child`` is ``parent`` or below it (resolved, case-normalised on Windows)."""
    c, p = _normcase(child), _normcase(parent)
    return c == p or c.startswith(p.rstrip("\\/") + os.sep)


def _read_env_file(env_path: Path) -> dict[str, str]:
    if not env_path.exists():
        return {}
    values = {k: (v or "") for k, v in dotenv_values(env_path).items()}
    unknown = set(values) - ALLOWED_ENV_KEYS
    if unknown:
        # Never echo values: they could be secrets pasted by mistake.
        raise ConfigError(
            f".env contains unsupported keys {sorted(unknown)}; it may hold only "
            f"{SECRETS_FILE_ENV}. Keys belong in the secrets file outside the repo."
        )
    if values.get(LIVE_GATE_ENV, "").strip():
        raise ConfigError(
            f"{LIVE_GATE_ENV} must not be set in .env; set it in the shell for a live session only"
        )
    return values


def _secrets_path(raw: str, repo_root: Path) -> Path | None:
    raw = raw.strip()
    if not raw:
        return None
    path = Path(raw)
    if not path.is_absolute():
        raise ConfigError(f"{SECRETS_FILE_ENV} must be an absolute path outside the repository")
    if is_inside(path, repo_root):
        raise ConfigError(f"{SECRETS_FILE_ENV} points inside the repository; refusing (SAF-01)")
    return path


def load_settings(
    config_path: Path = DEFAULT_CONFIG_PATH,
    env_path: Path = DEFAULT_ENV_PATH,
    repo_root: Path = REPO_ROOT,
) -> Settings:
    """Load and validate settings. Opens config.yaml read-only; never reads secrets."""
    with config_path.open("r", encoding="utf-8") as fh:
        raw: Any = yaml.safe_load(fh)
    if not isinstance(raw, dict):
        raise ConfigError(f"{config_path} must contain a mapping")
    if "secrets_file" in raw:
        raise ConfigError("secrets_file may not be set in config.yaml; use .env")

    base_dir = config_path.resolve().parent
    data = dict(raw)
    risk = dict(data.get("risk") or {})
    if "kill_switch_path" in risk:
        risk["kill_switch_path"] = _absolute(Path(risk["kill_switch_path"]), base_dir)
    data["risk"] = risk
    paths = dict(data.get("paths") or {})
    if "var_dir" in paths:
        paths["var_dir"] = _absolute(Path(paths["var_dir"]), base_dir)
    data["paths"] = paths

    env = _read_env_file(env_path)
    data["secrets_file"] = _secrets_path(env.get(SECRETS_FILE_ENV, ""), repo_root)
    try:
        return Settings.model_validate(data)
    except ValueError as exc:  # pydantic ValidationError is a ValueError
        raise ConfigError(str(exc)) from exc


def _absolute(p: Path, base: Path) -> Path:
    return p if p.is_absolute() else (base / p).resolve()


def load_secrets(settings: Settings) -> object:
    """Read the API key from the secrets file into a SecretStr (AD-22). M6 only.

    Never called in backtest or dry-run. Not implemented in M0, so nothing reads the file.
    """
    raise NotImplementedError("load_secrets is implemented at M6 (AD-22)")
