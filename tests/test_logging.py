"""Structured logs with secret redaction (FR-43, NFR-07, AD-22)."""

from __future__ import annotations

import json
import logging
from datetime import timedelta

import ccxt
import pytest

from bot import logging_setup
from bot.broker.errors import TransientReadError
from bot.clock import FakeClock
from bot.logging_setup import REDACTED, redact, register_secret
from tests.engine.helpers import T0, dry_run

FAKE = "FAKE-SECRET-not-a-real-key-123456"


@pytest.fixture(autouse=True)
def _restore_logging():  # noqa: ANN202
    root = logging.getLogger()
    handlers, level = list(root.handlers), root.level
    yield
    for h in list(root.handlers):
        root.removeHandler(h)
        h.close()
    for h in handlers:
        root.addHandler(h)
    root.setLevel(level)
    logging_setup._SECRETS.discard(FAKE)  # noqa: SLF001


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("API-Key: Zm9vYmFy1234", "Zm9vYmFy1234"),
        ("API-Sign: c2lnbmF0dXJlLWhlcmU=", "c2lnbmF0dXJlLWhlcmU"),
        ("{'apiKey': 'abcdef123456'}", "abcdef123456"),
        ('secret="s3cr3tvalue"', "s3cr3tvalue"),
        ("Authorization: Bearer tok3n-value", "tok3n-value"),
        ("password=hunter2hunter2", "hunter2hunter2"),
    ],
)
def test_credential_shapes_are_redacted(text: str, value: str) -> None:
    out = redact(text)
    assert REDACTED in out
    assert value not in out


def test_planted_secret_never_reaches_the_log_file_or_the_store(tmp_path) -> None:
    register_secret(FAKE)
    log_file = tmp_path / "logs" / "dry-run-v0_trend.log"
    ctx = logging_setup.configure(log_file, "dry-run", "v0_trend", to_stderr=False)
    ctx.run_id = 7
    clock = FakeClock(T0 + timedelta(seconds=25))
    dry, ex = dry_run(tmp_path, clock)
    ex.fail("fetch_ticker", ccxt.AuthenticationError(f"EAPI:Invalid key {FAKE}"), times=1)
    with pytest.raises(TransientReadError) as info:
        dry.feed.ticker("BTC/EUR")
    dry.engine.start(pid=1)
    dry.engine.error(clock.now(), "ticker", info.value, tb=f"Traceback: {FAKE}")
    logging.getLogger("bot.test").error("about to fail with %s", FAKE)
    for h in logging.getLogger().handlers:
        h.flush()
    text = log_file.read_text(encoding="utf-8")
    assert FAKE not in text and REDACTED in text
    line = json.loads(text.splitlines()[-1])
    assert line["run_id"] == 7 and line["mode"] == "dry-run" and line["strategy"] == "v0_trend"
    row = dry.store.one("SELECT message, traceback FROM errors")
    assert FAKE not in row["message"] and FAKE not in row["traceback"]
