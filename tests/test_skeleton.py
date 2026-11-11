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


# --- audit M0 F-2 / F-3: no code path writes the config or mutates frozen settings -----

_WRITE_ATTRS = {"write_text", "write_bytes", "unlink", "rename", "replace", "touch"}
_CONFIG_NAME_HINTS = ("config", "risk")


def _mentions_config(node: ast.AST | None) -> bool:
    if node is None:
        return False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Name) and any(h in sub.id.lower() for h in _CONFIG_NAME_HINTS):
            return True
        if isinstance(sub, ast.Attribute) and any(
            h in sub.attr.lower() for h in _CONFIG_NAME_HINTS
        ):
            return True
        if (
            isinstance(sub, ast.Constant)
            and isinstance(sub.value, str)
            and sub.value.endswith((".yaml", ".yml"))
        ):
            return True
    return False


def _open_mode(call: ast.Call) -> str:
    is_builtin = isinstance(call.func, ast.Name) and call.func.id == "open"
    args = list(call.args)
    mode_node = (args[1] if len(args) > 1 else None) if is_builtin else (args[0] if args else None)
    for kw in call.keywords:
        if kw.arg == "mode":
            mode_node = kw.value
    if mode_node is None:
        return "r"
    if isinstance(mode_node, ast.Constant) and isinstance(mode_node.value, str):
        return mode_node.value
    return "<dynamic>"


def _config_write_offence(call: ast.Call) -> str | None:
    func = call.func
    name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
    target = func.value if isinstance(func, ast.Attribute) else None
    if name in _WRITE_ATTRS and _mentions_config(target):
        return name
    if name == "open":
        mode = _open_mode(call)
        writes = mode == "<dynamic>" or any(c in mode for c in "wax+")
        subject = (call.args[0] if call.args else None) if isinstance(func, ast.Name) else target
        if writes and _mentions_config(subject):
            return f"open({mode!r})"
    return None


def test_no_code_writes_to_a_config_path() -> None:
    """AD-10: any write-capable call whose target mentions config/risk/yaml is refused."""
    offenders = []
    for path in _python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and (why := _config_write_offence(node)):
                offenders.append(f"{path.name}:{node.lineno} {why}")
    assert offenders == []


@pytest.mark.parametrize(
    "src",
    [
        "DEFAULT_CONFIG_PATH.write_text('x')",
        "open(config_path, 'w')",
        "open(DEFAULT_CONFIG_PATH, mode='a')",
        "Path('config.yaml').write_text('x')",
        "config_path.open('w')",
        "risk_file.open(mode)",
    ],
)
def test_write_detector_catches_known_bad_patterns(src: str) -> None:
    # Meta-test: the detector must flag the bypasses the M0 audit found.
    call = ast.parse(src).body[0].value  # type: ignore[attr-defined]
    assert _config_write_offence(call) is not None


@pytest.mark.parametrize(
    "src", ["open(config_path)", "config_path.open('r')", "log.write_text('x')"]
)
def test_write_detector_allows_reads_and_unrelated_writes(src: str) -> None:
    call = ast.parse(src).body[0].value  # type: ignore[attr-defined]
    assert _config_write_offence(call) is None


_FROZEN_BYPASSES = {"model_construct", "__setattr__", "__dict__"}


def test_no_code_bypasses_frozen_models() -> None:
    """Audit M0 F-3: object.__setattr__, setattr(), model_construct, __dict__ and
    model_copy(update=...) could mutate the frozen RiskLimits; none may appear in bot/."""
    offenders = []
    for path in _python_files():
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and node.attr in _FROZEN_BYPASSES:
                offenders.append(f"{path.name}:{node.lineno} {node.attr}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "model_copy"
                and any(kw.arg == "update" for kw in node.keywords)
            ):
                offenders.append(f"{path.name}:{node.lineno} model_copy(update=...)")
            if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "setattr":
                offenders.append(f"{path.name}:{node.lineno} setattr()")
    assert offenders == []
