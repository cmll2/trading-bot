# trading-bot

A small, rules-based Kraken spot trading bot (BTC/EUR, daily candles, long or flat). You run it locally, watch it in dry-run on a read-only dashboard, then run it live with about €20 under strict limits. Version 1 is judged on correctness, observability and safety, not on profit.

The plan is in `first_brief.txt`, `docs/planning/` and `PROGRESS.md` (read that first). **Status: M0 scaffold.** The modules are stubs and `backtest` / `dry-run` / `live` exit with "not implemented".

## Safety rules (summary of brief §4)

- **Secrets:** API keys go in a secrets file **outside** this repository. `.env` (gitignored) holds only its absolute path in `TRADING_BOT_SECRETS_FILE`. The bot refuses a path inside the repo, and refuses any other key in `.env`. Never commit, print or paste a key.
- **Protected files:** the `risk:` section of `config.yaml`, `bot/risk/` and `tests/risk/` change only on the operator's explicit request, in a commit that touches nothing else. Limits load into a frozen model, and no code path writes them.
- **Live needs a double gate:** the `bot live --live` flag **and** `TRADING_BOT_LIVE=I_ACCEPT_REAL_ORDERS` set in the shell (never in `.env`). The plumbing strategy can never run live. In M0, live refuses to run even when both gates pass.
- **No network in tests:** an autouse fixture blocks every socket, so no test can reach an exchange. Tests use fakes.
- **Dependencies** are pinned in `uv.lock`. Ask before adding any dependency beyond brief §6.
- **Dashboard** (M4) binds to `127.0.0.1` only.

## Setup

```sh
uv sync
cp .env.example .env   # optional; leave empty until live (M6)
uv run bot --help
```

## Checks (CI-style)

One command runs lint, format check and tests:

```sh
uv run ruff check . && uv run ruff format --check . && uv run pytest
```

The same command as a script: `scripts/check.sh` (POSIX shell) or `powershell -File scripts/check.ps1` (Windows).
