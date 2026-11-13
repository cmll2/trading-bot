"""Provenance of a result: code version, config hash, limits hash (FR-18, NFR-02, AD-21)."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

from bot.config import REPO_ROOT, Settings


def _git(*args: str, cwd: Path = REPO_ROOT) -> str | None:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607
            cwd=cwd,
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout


def git_commit(cwd: Path = REPO_ROOT) -> str:
    out = _git("rev-parse", "HEAD", cwd=cwd)
    return out.strip() if out else "unknown"


def git_dirty(cwd: Path = REPO_ROOT) -> bool:
    """True when tracked or untracked (non-ignored) files differ from HEAD, or git fails."""
    out = _git("status", "--porcelain", cwd=cwd)
    return True if out is None else bool(out.strip())


def _canonical(settings: Settings) -> dict:
    data = settings.model_dump(mode="json")
    # Machine-specific absolute paths and the secrets path are not part of the experiment.
    data.pop("secrets_file", None)
    data.pop("paths", None)
    data.get("backtest", {}).pop("results_dir", None)
    data.get("risk", {}).pop("kill_switch_path", None)
    return data


def config_hash(settings: Settings) -> str:
    raw = json.dumps(_canonical(settings), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def limits_hash(settings: Settings) -> str:
    raw = json.dumps(_canonical(settings)["risk"], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
