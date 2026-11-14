"""Structured JSON logs to var/logs/ with secrets redacted (FR-43, NFR-07, AD-22).

``configure(log_path, mode, strategy_id)`` installs, on the root logger:

- a daily-rotated JSON-lines file handler (30 files kept) and a stderr handler;
- a ``RedactionFilter`` on every handler, so no record reaches a sink unredacted;
- a context filter that adds ``run_id``, ``mode`` and ``strategy`` to every line.

``redact(text)`` is the one redaction function: the log filter uses it, and the engine
runs it on every ``errors`` row before insert. It masks values registered with
``register_secret`` (none in dry-run, which never loads secrets) and the usual
credential shapes: ``API-Key``/``API-Sign`` headers, ``apiKey``/``secret``/``password``/
``token`` assignments and HTTP ``Authorization`` values.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import sys
import time
from pathlib import Path

REDACTED = "***REDACTED***"
_SECRETS: set[str] = set()
_PATTERNS = (
    re.compile(
        r"(?i)(api[-_]?key|api[-_]?sign|authorization)(\s*[:=]\s*|['\"]\s*:\s*['\"])([^\s'\",}]+)"
    ),
    re.compile(
        r"(?i)\b(secret|password|passwd|token|private[-_]?key)(\s*[:=]\s*|['\"]\s*:\s*['\"])([^\s'\",}]+)"
    ),
)


def register_secret(value: str) -> None:
    """Mask this exact value wherever it appears (values shorter than 6 chars ignored)."""
    if value and len(value) >= 6:
        _SECRETS.add(value)


def redact(text: object) -> str:
    out = str(text)
    for secret in sorted(_SECRETS, key=len, reverse=True):
        out = out.replace(secret, REDACTED)
    for pattern in _PATTERNS:
        out = pattern.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    return out


class RedactionFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact(record.getMessage())
        record.args = ()
        if record.exc_info:
            record.exc_text = redact(logging.Formatter().formatException(record.exc_info))
            record.exc_info = None
        return True


class ContextFilter(logging.Filter):
    def __init__(self, mode: str, strategy: str) -> None:
        super().__init__()
        self.mode = mode
        self.strategy = strategy
        self.run_id: int | None = None

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        record.mode = self.mode
        record.strategy = self.strategy
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "at": self.formatTime(record, "%Y-%m-%dT%H:%M:%S") + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "logger": record.name,
            "run_id": getattr(record, "run_id", None),
            "mode": getattr(record, "mode", None),
            "strategy": getattr(record, "strategy", None),
            "msg": record.getMessage(),
        }
        if record.exc_text:
            payload["exc"] = record.exc_text
        return json.dumps(payload, ensure_ascii=False, default=str)


class _UtcJsonFormatter(JsonFormatter):
    converter = staticmethod(time.gmtime)


def configure(log_path: Path, mode: str, strategy: str, *, to_stderr: bool = True) -> ContextFilter:
    """Install JSON file logging with redaction on the root logger; returns the context
    filter so the caller can set ``run_id`` once the run row exists."""
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for h in list(root.handlers):
        root.removeHandler(h)
    context = ContextFilter(mode, strategy)
    file_handler = logging.handlers.TimedRotatingFileHandler(
        log_path, when="midnight", backupCount=30, encoding="utf-8", utc=True
    )
    handlers: list[logging.Handler] = [file_handler]
    if to_stderr:
        handlers.append(logging.StreamHandler(sys.stderr))
    for h in handlers:
        h.addFilter(context)
        h.addFilter(RedactionFilter())
        h.setFormatter(_UtcJsonFormatter())
        root.addHandler(h)
    return context
