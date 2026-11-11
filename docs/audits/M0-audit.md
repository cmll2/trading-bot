# M0 independent audit

- **Scope:** branch `m0-scaffold` (HEAD `3bfda0f`) against base `7d44e84` (main). Commits audited: `dd07d31`, `e451823`, `8c05165`, `0d6b399`, `3bfda0f`.
- **Auditor:** a fresh subagent that did not write the code. Every claim below was checked in this session. Claims in PROGRESS.md and in commit messages were not taken on trust.
- **Date:** 2026-11-11
- **Method:** I ran the checks myself, read the full diff `git log -p 7d44e84..m0-scaffold` and ran `git show --stat` on each commit. I ran the CLI live-gate variants with no keys, probed the network block on loopback only, and probed the frozen models at runtime. No project file was modified apart from this report. No secrets were created or read. The probe files live in the scratchpad.

## Overall verdict: PASS, with findings

M0 meets its acceptance criterion. No safety rule from brief §4 is violated. One item is INCONCLUSIVE because only the operator can confirm it. Several Low/Medium findings should be fixed or acknowledged before M1.

## 1. Checks run by the auditor: PASS

| Command | Result |
|---|---|
| `uv run ruff check .` | `All checks passed!` (exit 0) |
| `uv run ruff format --check .` | `42 files already formatted` (exit 0) |
| `uv run pytest -v` | `93 passed in 1.21s` (exit 0); 0 skipped, 0 xfailed, 0 warnings |
| `sh scripts/check.sh` / `powershell -File scripts/check.ps1` | both end with `93 passed` |
| `uv lock --check` | `Resolved 65 packages`, lockfile consistent (exit 0) |

The risk tests also pass on the protected commit taken alone. I extracted `e451823` with `git archive` and ran `pytest tests/risk` against that snapshot: 15 passed.

## 2. Git history

### 2a. Deleted, skipped or weakened tests: PASS
- `git diff --diff-filter=DMR 7d44e84 m0-scaffold` shows no deleted or renamed files. The modified files are only `.gitignore`, `PROGRESS.md`, `docs/planning/architecture.md` and `pyproject.toml`. The base commit had no tests, so none could be weakened.
- Grep for `skip|xfail|importorskip|filterwarnings|undo(` over `tests/` finds nothing. `pyproject` addopts is `-ra --strict-markers`.
- The ruff config adds rules (`TID`) and excludes only vendored agent tooling (`.agents`, `.claude`, `_bmad`). It does not exclude project code. The `noqa` comments appear only in tests (S310 on the deliberate blocked urlopen, and S603/S607 on `git` subprocess calls), all justified.

### 2b. Extra holdout runs: PASS (not applicable)
There is no backtest code, so no holdout could have been run. The holdout window is fixed in `config.yaml` (2025-11-11 to 2026-11-10).

### 2c. Protected-file rule (per-commit `git show --stat`): PASS (mechanics)

| Commit | Touches protected files? | Touches anything else? |
|---|---|---|
| `dd07d31` | no | `.gitignore` only |
| `e451823` | `config.yaml`, `bot/risk/*` (5 files), `tests/risk/test_risk_limits.py` | **nothing else** |
| `8c05165` | no (`config.yaml`, `bot/risk/` and `tests/risk/` are untouched) | scaffold |
| `0d6b399` | no | docs |
| `3bfda0f` | no | PROGRESS.md |

Caveat (Low, F-8): `e451823` also created the **non-risk** sections of `config.yaml` (exchange, execution, backtest, review, paths). That is within the file, so I accept it. But the protected unit is a section of a shared file. From now on, any commit that edits `config.yaml` must be checked hunk by hunk.

### 2d. Operator authorization of the protected commit: INCONCLUSIVE
The brief requires the operator's explicit request in the chat. Git history cannot prove that. The operator must confirm it. This applies in particular to two choices:
- moving the per-intent submission cap out of `risk:` (see F-1);
- interpreting "4 orders/day" as 4 intents per day plus a 24-submission daily cap.

## 3. Safety review (brief §4)

### 3a. Secrets handling: PASS
- No code reads secrets: `load_secrets()` raises `NotImplementedError`, and grep finds no `open`, `getenv` or logging of secrets in `bot/`.
- `.env` is read with `dotenv_values` and is not injected into `os.environ`; a test covers this.
- Any key other than `TRADING_BOT_SECRETS_FILE` and `TRADING_BOT_LIVE` is refused, and the error does not echo the value; a test covers this.
- The secrets path must be absolute and outside the repo. The check resolves the path and normalizes case. Tests cover `..`, a path equal to the repo root, and a sibling directory whose name starts with the repo name.
- `.env.example` holds only `TRADING_BOT_SECRETS_FILE=` (empty).
- No `.env`, `*.key` or `*secret*` file has ever been added in git history (`git log --all --diff-filter=A`).

### 3b. .gitignore coverage: PASS (with F-5)
I checked each path with `git check-ignore -v`:
- **ignored:** `.env`, `.env.local`, `data/x.parquet`, `var/KILL`, `var/bot.sqlite`, `logs/a.log`, `kraken.key`, `x.db`;
- **not ignored:** `.env.example`, `bot/data/__init__.py`, `bot/data/cache.py`, `bot/data/`, `dashboard/app.py`.

`dd07d31` correctly root-anchors `/data/`, and a regression test covers it. However, `*secret*` also ignores `bot/secrets.py` and `bot/secret_store.py` (see F-5).

### 3c. Live double gate: PASS
I ran each variant with no keys, `TRADING_BOT_LIVE` unset in my shell, and no `.env` present:

| Invocation | Exit | Message |
|---|---|---|
| `bot live` | 2 | REFUSED: requires --live |
| `bot live --live` | 2 | REFUSED: requires TRADING_BOT_LIVE |
| `TRADING_BOT_LIVE=I_ACCEPT_REAL_ORDERS bot live` | 2 | REFUSED: requires --live |
| `TRADING_BOT_LIVE=yes bot live --live` | 2 | REFUSED |
| `TRADING_BOT_LIVE="I_ACCEPT_REAL_ORDERS "` (trailing space) `bot live --live` | 2 | REFUSED |
| both gates | 3 | REFUSED: live not implemented (M6) |
| both gates + `--strategy plumbing` | 2 | REFUSED: plumbing not allowed in live |
| both gates + `--liv` (abbreviation) | 3 | accepted as `--live` (F-6) |
| `python -m bot.cli live --live` | 2 | REFUSED |

- A gate value placed in `.env` is refused as a config error, and a test covers this.
- Code that bypasses the CLI still cannot place an order, because no broker exists in M0.
- A `LiveGate` can only be built with the module-private `_GATE_KEY`. That is a convention, not a security boundary (F-9).

### 3d. Plumbing strategy refused in live: PASS
Two independent checks refuse it:
- it is absent from `LIVE_STRATEGIES`, which is a `MappingProxyType` and cannot be mutated (a test covers this);
- `"live"` is not in `Plumbing.allowed_modes`.

On top of that, its 15m timeframe is not in `LIVE_TIMEFRAMES`. I confirmed the refusal through the real CLI (table above).

### 3e. No code path can write the risk limits: PASS (with F-2, F-3)
- `RiskLimits` and every `Settings` sub-model use `ConfigDict(frozen=True, extra="forbid")`. Assignment raises, and tests cover it.
- Grep over `bot/` and `dashboard/` finds no `setattr`, `object.__setattr__`, `model_copy`, `model_construct`, `__dict__`, yaml dump or file write.
- `config.yaml` is opened only in `"r"` mode, in `bot/config.py`.
- Probe: `object.__setattr__(settings.risk, "max_position_abs_quote", 1000)` **succeeds** at runtime. Python cannot prevent this; no code does it today, and no test would catch it (F-3).

### 3f. Network block in tests: PASS (with F-4)
`tests/conftest.py` has an autouse fixture that patches the following, and the 5 self-tests pass:
- `socket.socket.connect`, `connect_ex` and `sendto`;
- `socket.create_connection` and `socket.getaddrinfo`.

I ran loopback-only probes from the scratchpad, loading the conftest as a plugin with `-p tests.conftest`. Nothing reached an external host:
- `socket.create_connection` to a local listener: blocked.
- `asyncio.open_connection("127.0.0.1", ...)`: blocked, as a side effect: the Proactor loop's own socketpair fails.
- **`_socket.socket(...).connect(...)`: CONNECTED (bypass).**
- **`monkeypatch.undo()` inside a test, then `socket.create_connection`: CONNECTED (bypass).**

Tests can also start subprocesses, which are not covered: the suite already runs `git`. No current test uses any of these bypasses.

### 3g. No hardcoded exchange minimums or fees: PASS
- `config.yaml` has no minimums or fees, and a test checks that.
- Grep for fee and minimum literals in `bot/` finds nothing.
- `MarketRules` and `FeeRates` are value types whose values are meant to come from the exchange.
- Fees are deliberately absent until M2, as PROGRESS.md logs.

### 3h. Dependencies limited to brief §6: PASS
- **Runtime** (`pyproject.toml` and `uv.lock`, package `trading-bot`): ccxt, pandas, plotly, pyarrow, pydantic, python-dotenv, pyyaml, streamlit.
- **Dev:** pytest, ruff.
- All of these are named in brief §6. `[project]` dependencies and `uv.lock` did not change on this branch (only ruff and pytest config changed in `pyproject.toml`). Lock: 65 packages, consistent.

## 4. M0 acceptance criterion: PASS
The criterion reads: "repo, lockfile, config, .env.example, .gitignore, CI-style test command. Done when tests and lint pass on an empty skeleton."

Every listed item is present. The CI-style command is in the README, `scripts/check.sh` and `scripts/check.ps1`. The auditor ran all three steps and they pass (section 1). The skeleton matches the brief §5 layout, and every `bot.*` module imports.

## 5. Test quality: PASS (with F-2, F-7, F-10)
Most tests assert real behaviour, such as exit codes, error messages, ValidationErrors, git check-ignore results and NetworkBlocked. I found no tautological asserts. Weak spots:
- **F-2:** the "no write path to config" AST tests promise more than they check (details below).
- **F-7:** the `no_broker` fixture in `tests/test_cli.py` is a no-op. It patches `bot.config.load_secrets`, but `cli.py` never imports or calls that function. If a later `from bot.config import load_secrets` is added to `cli.py`, it will not be intercepted.
- **F-10:** `test_secrets_file_is_not_read_at_load` uses a path that does not exist. Code that checks `exists()` before reading would still pass it. A spy on `open` would be stronger.
- `test_config_has_no_hardcoded_minimums_or_fees` scans only `config.yaml`, not the Python code.

## Findings by severity

### High
None.

### Medium
- **F-1: Protected limit moved out of the protected section (operator decision needed).**
  - The original AD-10 put the re-price cap (`max_reprices`) in protected `risk:`. M0 puts `max_submissions_per_intent: 12` in unprotected `execution:`.
  - It is bounded by validation against the protected daily cap of 24, so a single edit cannot exceed 24 submissions per day. It can still be raised from 12 to 24 without a protected commit.
  - The same goes for "4 orders/day = 4 intents" (re-prices not counted). That is an interpretation of a protected limit.
  - Both are logged and flagged in PROGRESS.md as "agreed", but the operator must confirm them (item 2d).
- **F-2: The no-write-path tests promise more than they check.**
  - `test_no_module_dumps_yaml_or_writes_config` looks only for `.dump*` attributes and the literal string `"config.yaml"` outside `config.py`. A write such as `DEFAULT_CONFIG_PATH.write_text(...)` or `open(DEFAULT_CONFIG_PATH, "w")` in `cli.py` (which imports `DEFAULT_CONFIG_PATH`) would pass.
  - `test_config_module_opens_config_read_only` checks only `.open` method calls in `config.py`. A builtin `open(config_path, "w")` (an `ast.Name` call) is not detected.
  - architecture.md AD-10 says the AST test "fails if any module opens the config path for write or append", which overstates it. No such write exists in the code today.

### Low
- **F-3:** Frozen models can be bypassed with `object.__setattr__` (shown at runtime). Add an AST ban on `object.__setattr__`, `model_copy(update=...)` and `model_construct` in `bot/`, or hash the limits at startup and re-check the hash (AD-10 already plans `limits_hash`).
- **F-4:** The network block can be bypassed with `_socket.socket`, `monkeypatch.undo()` or subprocesses. Consider also patching `_socket.socket.connect`, plus a meta-test or grep that forbids `undo(` and network-capable subprocesses in `tests/`. The conftest itself is not a protected file.
- **F-5:** The `.gitignore` pattern `*secret*` silently ignores any future source file such as `bot/secrets.py`. Only `test_*secret*.py` is excepted. Similarly, `*.parquet` and `*.db` will ignore recorded test fixtures (brief §8 consistency test). Narrow these patterns or add exceptions before M1/M2.
- **F-6:** argparse `allow_abbrev` is on, so `--liv` or `--l` open the flag gate. This is not a bypass, because the env var is still required. Set `allow_abbrev=False` so the gate needs the exact `--live`.
- **F-7:** The `no_broker` fixture is a no-op (see section 5).
- **F-8:** The protected commit also created the non-risk sections of `config.yaml`. Future `config.yaml` edits need hunk-level review. Consider moving `risk:` to its own file to make the rule mechanical.
- **F-9:** The `LiveGate` key is private by convention only: `cli.LiveGate(cli._GATE_KEY, ...)` works. This is acceptable for M0. At M6, the real protection must be in `KrakenBroker` and `main`.
- **F-10:** The secrets-not-read test is weak (see section 5).
- **F-11:** `RiskLimits` uses `strict=False`, so YAML `true` is accepted as `1` for an int limit and `4.0` as `4` (checked at runtime). This is harmless today, but strict integer fields would reject typos in protected values.

### Info
- `requires-python >=3.12` (the brief says 3.11 or later): compliant.
- The holdout window is in unprotected `config.yaml`. Any change shows in git, but nothing enforces the "never moves" rule.
- `_bmad/` is untracked and not ignored, so it should not be committed by accident.
