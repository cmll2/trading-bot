"""M0 skeleton checks: package layout (brief §5), no write path to config (SAF-05, AD-10),
repository hygiene (SAF-01, SAF-12)."""

from __future__ import annotations

import ast
import importlib
import pkgutil
import subprocess
from pathlib import Path

import pytest

import bot
from tests.conftest import REPO_ROOT

BRIEF_LAYOUT = [
    "bot/config.py",
    "bot/data/__init__.py",
    "bot/strategy/__init__.py",
    "bot/backtest/__init__.py",
    "bot/broker/__init__.py",
    "bot/risk/__init__.py",
    "bot/engine.py",
    "bot/store.py",
    "bot/ledger.py",
    "bot/cli.py",
    "dashboard/__init__.py",
    "tests/conftest.py",
    "config.yaml",
    ".env.example",
    ".gitignore",
    ".gitattributes",
    "uv.lock",
]


@pytest.mark.parametrize("relpath", BRIEF_LAYOUT)
def test_layout_matches_brief(relpath: str) -> None:
    assert (REPO_ROOT / relpath).is_file(), relpath


def test_every_bot_module_imports() -> None:
    names = [m.name for m in pkgutil.walk_packages(bot.__path__, prefix="bot.")]
    assert "bot.risk.limits" in names
    for name in names:
        importlib.import_module(name)


def _python_files() -> list[Path]:
    return [*(REPO_ROOT / "bot").rglob("*.py"), *(REPO_ROOT / "dashboard").rglob("*.py")]


def test_no_module_dumps_yaml_or_writes_config() -> None:
    """AD-10: no code path can write config.yaml (and so the risk limits)."""
    offenders = []
    for path in _python_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in {
                "dump",
                "safe_dump",
                "dump_all",
                "safe_dump_all",
            }:
                offenders.append(f"{path.name}:{node.lineno} {node.attr}")
            if (
                isinstance(node, ast.Constant)
                and node.value == "config.yaml"
                and path.name != "config.py"
            ):
                offenders.append(f"{path.name}:{node.lineno} names config.yaml")
    assert offenders == []


def test_config_module_opens_config_read_only() -> None:
    tree = ast.parse((REPO_ROOT / "bot" / "config.py").read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) in {
            "write_text",
            "write_bytes",
        }:
            pytest.fail(f"config.py writes a file at line {node.lineno}")
        if isinstance(node, ast.Call) and getattr(node.func, "attr", None) == "open":
            modes = [a.value for a in node.args if isinstance(a, ast.Constant)]
            assert modes == ["r"], f"config.py open() mode {modes} at line {node.lineno}"


def test_env_example_has_only_empty_values() -> None:
    for line in (REPO_ROOT / ".env.example").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        key, sep, value = line.partition("=")
        assert sep == "=", line
        assert value.strip() == "", f"{key} must be empty in .env.example"


def test_gitattributes_enforces_lf() -> None:
    text = (REPO_ROOT / ".gitattributes").read_text(encoding="utf-8")
    assert "* text=auto eol=lf" in text


def _git(*args: str) -> str:
    return subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


def test_dot_env_is_gitignored_and_not_tracked() -> None:
    assert _git("check-ignore", ".env").strip() == ".env"
    assert ".env" not in _git("ls-files").splitlines()


def test_package_dirs_are_not_gitignored() -> None:
    # Regression: an unanchored `data/` pattern used to ignore bot/data/.
    for rel in ("bot/data/__init__.py", "bot/risk/limits.py", "dashboard/__init__.py"):
        result = subprocess.run(  # noqa: S603
            ["git", "check-ignore", "-q", rel],  # noqa: S607
            cwd=REPO_ROOT,
        )
        assert result.returncode == 1, f"{rel} is gitignored"
