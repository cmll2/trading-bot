"""Kraken OHLCVT archive import (AD-18, research B6). M1 story 3.

The public OHLC endpoint returns only the last 720 candles, so history comes from Kraken's
official OHLCVT ZIP archive, supplied by the operator (nothing is downloaded here). The ZIP
is untrusted input:

- its SHA-256 is checked (streamed, whole file) BEFORE it is opened as a ZIP;
- only the exact members ``XBTEUR_{1440,240,15}.csv`` are read (basename match, any
  directory prefix); ``AIXBTEUR_1440.csv``, ``XBTEURC_1440.csv`` etc. never match;
- members are streamed into ``pandas.read_csv`` with explicit dtypes and ``header=None``;
  nothing is extracted to disk, executed or imported; encrypted members and members larger
  than ``MAX_MEMBER_BYTES`` (declared or actually decompressed) are refused;
- timestamps must be integral Unix seconds within [2013-01-01, 2100-01-01) (unit guard).

Per timeframe (all-or-nothing): read -> ``apply_no_trade_policy`` -> ``validate_frame`` ->
``write_cache``. A timeframe that fails writes nothing; timeframes already written stay.
The Kraken pair code and interval mapping live only in this module.
"""

from __future__ import annotations

import hashlib
import io
import re
import zipfile
from collections.abc import Callable, Iterable
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd

from bot.config import Settings
from bot.data.cache import cache_path, normalize, write_cache
from bot.data.validate import (
    DataValidationError,
    apply_no_trade_policy,
    read_cache_checked,
    validate_frame,
)

ARCHIVE_PAIRS: dict[str, str] = {"BTC/EUR": "XBTEUR"}
ARCHIVE_INTERVALS: dict[str, int] = {"1d": 1440, "4h": 240, "15m": 15}  # minutes

MAX_MEMBER_BYTES = 512 * 1024 * 1024  # 512 MiB, declared and actually decompressed
HASH_CHUNK_BYTES = 1024 * 1024  # 1 MiB
MIN_TIMESTAMP_S = 1_356_998_400  # 2013-01-01T00:00Z
MAX_TIMESTAMP_S = 4_102_444_800  # 2100-01-01T00:00Z (exclusive)

CSV_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume", "trades")
_CSV_DTYPES = {0: "int64", **{i: "float64" for i in range(1, 6)}, 6: "int64"}
_SHA256_RE = re.compile(r"[0-9a-fA-F]{64}")


class ArchiveError(RuntimeError):
    """The archive (or the request to import it) is refused. ``timeframe`` is set when the
    failure belongs to one timeframe."""

    def __init__(self, message: str, timeframe: str | None = None) -> None:
        self.timeframe = timeframe
        super().__init__(message)


def sha256_stream(fh: BinaryIO) -> str:
    """Lower-case hex SHA-256 of ``fh`` from its current position to EOF, in 1 MiB chunks."""
    digest = hashlib.sha256()
    while chunk := fh.read(HASH_CHUNK_BYTES):
        digest.update(chunk)
    return digest.hexdigest()


def sha256_file(path: Path) -> str:
    """Lower-case hex SHA-256 of the whole file, streamed in 1 MiB chunks."""
    with path.open("rb") as fh:
        return sha256_stream(fh)


def _check_sha256_format(expected: str) -> None:
    if not isinstance(expected, str) or not _SHA256_RE.fullmatch(expected):
        raise ArchiveError("malformed --sha256: expected 64 hex characters")


def verify_checksum(source: Path | BinaryIO, expected: str) -> None:
    """Refuse a malformed ``expected`` (before hashing) or a mismatching file. ``source`` is a
    path or a binary handle positioned at the start of the file (hashed to EOF)."""
    _check_sha256_format(expected)
    try:
        actual = sha256_file(source) if isinstance(source, Path) else sha256_stream(source)
    except OSError as exc:
        raise ArchiveError(f"cannot read archive: {exc}") from exc
    if actual != expected.lower():
        raise ArchiveError(f"checksum mismatch: expected {expected.lower()}, got {actual}")


def member_name(pair: str, tf: str) -> str:
    """``("BTC/EUR", "1d")`` -> ``XBTEUR_1440.csv``. Unmapped pair or timeframe is refused."""
    if pair not in ARCHIVE_PAIRS:
        raise ArchiveError(f"pair {pair} has no Kraken archive code")
    if tf not in ARCHIVE_INTERVALS:
        raise ArchiveError(f"timeframe {tf} has no Kraken archive interval", timeframe=tf)
    return f"{ARCHIVE_PAIRS[pair]}_{ARCHIVE_INTERVALS[tf]}.csv"


def _basename(name: str) -> str:
    return re.split(r"[/\\]", name)[-1]


def find_member(zf: zipfile.ZipFile, name: str) -> zipfile.ZipInfo:
    """The single file member whose basename is exactly ``name``; refuses none or several."""
    matches = [i for i in zf.infolist() if not i.is_dir() and _basename(i.filename) == name]
    if not matches:
        raise ArchiveError(f"member {name} not found in archive")
    if len(matches) > 1:
        names = [i.filename for i in matches]
        raise ArchiveError(f"member {name} appears {len(matches)} times in archive: {names}")
    return matches[0]


class _CappedReader(io.RawIOBase):
    """Read-only stream that raises once more than ``cap`` bytes have been read."""

    def __init__(self, raw: io.BufferedIOBase, cap: int, name: str) -> None:
        self._raw, self._cap, self._name, self._total = raw, cap, name, 0

    def readable(self) -> bool:
        return True

    def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
        data = self._raw.read(len(buffer))
        self._total += len(data)
        if self._total > self._cap:
            raise ArchiveError(f"member {self._name} decompresses beyond {self._cap} bytes")
        buffer[: len(data)] = data
        return len(data)


def read_member(zf: zipfile.ZipFile, info: zipfile.ZipInfo, tf: str) -> pd.DataFrame:
    """Parse one Kraken OHLCVT CSV member into a normalized cache frame sorted by ``open_at``
    (``source="archive"``, ``trades`` Int64). Refuses anything unexpected, naming the member."""
    name = info.filename
    if info.flag_bits & 0x1:
        raise ArchiveError(f"member {name} is encrypted")
    if info.file_size > MAX_MEMBER_BYTES:
        raise ArchiveError(
            f"member {name} declares {info.file_size} bytes, above the {MAX_MEMBER_BYTES} cap"
        )
    try:
        with zf.open(info) as raw:
            stream = io.BufferedReader(_CappedReader(raw, MAX_MEMBER_BYTES, name))
            df = pd.read_csv(
                stream,
                header=None,
                dtype=_CSV_DTYPES,
                encoding="ascii",
                compression=None,
                engine="c",
            )
    except ArchiveError:
        raise
    except Exception as exc:  # parser, dtype, decode, zlib/CRC errors
        raise ArchiveError(f"member {name}: unreadable CSV ({type(exc).__name__}: {exc})") from exc
    if df.shape[1] != len(CSV_COLUMNS):
        raise ArchiveError(f"member {name}: {df.shape[1]} columns, expected {len(CSV_COLUMNS)}")
    if df.empty:
        raise ArchiveError(f"member {name}: no rows")
    df.columns = list(CSV_COLUMNS)
    if df.isna().any().any():
        raise ArchiveError(f"member {name}: missing values")
    ts = df["timestamp"].to_numpy(dtype="int64")
    out_of_range = (ts < MIN_TIMESTAMP_S) | (ts >= MAX_TIMESTAMP_S)
    if out_of_range.any():
        bad = int(ts[int(out_of_range.argmax())])
        raise ArchiveError(
            f"member {name}: timestamp {bad} outside [2013-01-01, 2100-01-01) "
            "(expected Unix seconds)"
        )
    prices = df[["open", "high", "low", "close", "volume"]].to_numpy(dtype="float64")
    if not np.isfinite(prices).all():
        raise ArchiveError(f"member {name}: non-finite price or volume")

    frame = pd.DataFrame(
        {
            "open_at": pd.to_datetime(ts * 1000, unit="ms", utc=True),
            "open": df["open"],
            "high": df["high"],
            "low": df["low"],
            "close": df["close"],
            "volume": df["volume"],
            "trades": df["trades"],
            "source": "archive",
        }
    )
    return normalize(frame.sort_values("open_at", kind="stable"))


def _refuse_existing_cache(path: Path, tf: str) -> None:
    cached = read_cache_checked(path)
    if cached is not None and not cached.empty:
        raise ArchiveError(f"cache exists; merge arrives in story 4 ({path})", timeframe=tf)


def import_archive(
    settings: Settings,
    zip_path: Path,
    expected_sha256: str,
    timeframes: Iterable[str],
    now: datetime | None = None,
    on_written: Callable[[str, pd.DataFrame], None] | None = None,
) -> dict[str, pd.DataFrame]:
    """Verify the checksum, then import each timeframe into its cache, in order.

    Stops at the first failing timeframe (raising ``ArchiveError`` with ``timeframe`` set);
    caches written for earlier timeframes stay. ``on_written`` is called after each write.
    """
    pair = settings.pairs[0]
    tfs = list(dict.fromkeys(timeframes))
    names = {tf: member_name(pair, tf) for tf in tfs}  # refuse unmapped pair/tf up front
    _check_sha256_format(expected_sha256)  # before opening or hashing anything

    written: dict[str, pd.DataFrame] = {}
    try:
        fh = zip_path.open("rb")
    except OSError as exc:
        raise ArchiveError(f"cannot read archive {zip_path}: {exc}") from exc
    # One handle: the bytes hashed are the bytes parsed (a file swapped after hashing is
    # never read). Checksum before any ZIP parsing.
    with fh:
        verify_checksum(fh, expected_sha256)
        fh.seek(0)
        try:
            zf = zipfile.ZipFile(fh)
        except (zipfile.BadZipFile, OSError) as exc:
            raise ArchiveError(f"not a readable ZIP archive: {exc}") from exc
        with zf:
            for tf in tfs:
                path = cache_path(settings.paths.var_dir, pair, tf)
                try:
                    _refuse_existing_cache(path, tf)
                    frame = read_member(zf, find_member(zf, names[tf]), tf)
                    frame = apply_no_trade_policy(frame, tf, settings.data.no_trade_policy)
                    validate_frame(frame, tf, settings.data, now=now)
                    write_cache(path, frame)
                except (ArchiveError, DataValidationError, OSError) as exc:
                    raise ArchiveError(str(exc), timeframe=tf) from exc
                written[tf] = frame
                if on_written is not None:
                    on_written(tf, frame)
    return written
