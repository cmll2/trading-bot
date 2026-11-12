"""Read-only view of an archive split into parts, without reassembling it on disk.

Kraken publishes its full OHLCVT archive as ``Kraken_OHLCVT_Full.zip.part00`` ..
``part04``: plain byte slices of one ZIP file, plus a SUMS file with one SHA-256 per part.
Reassembling would need another ~10 GB of disk, so ``ConcatReader`` presents the ordered
parts as a single seekable, read-only file that ``zipfile.ZipFile`` can open directly.

Stdlib only. Nothing here writes, extracts or executes anything. The part sizes are fixed
when the parts are opened; a part that shrinks afterwards makes reads fail loudly. As with
a single file, a same-size rewrite of a part while an import runs is not detected: the
guarantee "bytes hashed are bytes parsed" assumes nobody modifies the parts mid-import.
"""

from __future__ import annotations

import bisect
import hashlib
import io
import os
import re
from collections.abc import Sequence
from pathlib import Path

_SUMS_LINE = re.compile(r"([0-9a-fA-F]{64}) [ *](\S+)")


class MultipartError(OSError):
    """The parts or their checksum list are refused; the message names the problem.

    An ``OSError`` so that every I/O guard around ``zipfile`` and the importer catches it."""


def parse_sums_file(path: Path) -> list[tuple[str, str]]:
    """``[(file name, lower-case sha256), ...]`` in file order, from ``sha256sum`` output.

    Every non-blank line must be ``<64 hex><space><space or *><name>``; a name may not hold
    a path separator and may not repeat.
    """
    try:
        text = path.read_text(encoding="ascii")
    except (OSError, UnicodeDecodeError) as exc:
        raise MultipartError(f"cannot read part checksum file {path}: {exc}") from exc
    entries: list[tuple[str, str]] = []
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        match = _SUMS_LINE.fullmatch(line.strip())
        if match is None:
            raise MultipartError(f"{path.name}:{lineno}: not a '<sha256>  <name>' line")
        digest, name = match.group(1).lower(), match.group(2)
        if "/" in name or "\\" in name:
            raise MultipartError(f"{path.name}:{lineno}: name {name!r} holds a path separator")
        if any(name == n for n, _ in entries):
            raise MultipartError(f"{path.name}:{lineno}: {name} listed twice")
        entries.append((name, digest))
    if not entries:
        raise MultipartError(f"{path.name}: no checksum lines")
    return entries


def check_part_order(parts: Sequence[Path], sums: Sequence[tuple[str, str]]) -> None:
    """The given parts must be exactly the files the checksum list names, in its order."""
    given = [p.name for p in parts]
    expected = [name for name, _ in sums]
    if len(set(given)) != len(given):
        raise MultipartError(f"a part is given twice: {given}")
    missing = [n for n in expected if n not in given]
    if missing:
        raise MultipartError(f"missing part(s) {missing}; expected {expected} in this order")
    extra = [n for n in given if n not in expected]
    if extra:
        raise MultipartError(f"part(s) {extra} are not in the checksum list {expected}")
    if given != expected:
        raise MultipartError(f"parts out of order: got {given}, expected {expected}")


class ConcatReader(io.RawIOBase):
    """The ordered ``parts`` as one read-only, seekable byte stream."""

    def __init__(self, parts: Sequence[Path]) -> None:
        super().__init__()
        if not parts:
            raise MultipartError("no parts given")
        self._files: list[io.BufferedReader] = []
        try:
            for p in parts:
                self._files.append(p.open("rb"))
        except OSError as exc:
            self.close()
            raise MultipartError(f"cannot open part: {exc}") from exc
        self.part_sizes: tuple[int, ...] = tuple(os.fstat(f.fileno()).st_size for f in self._files)
        self._starts: list[int] = []
        total = 0
        for size in self.part_sizes:
            self._starts.append(total)
            total += size
        self._size = total
        self._pos = 0

    @property
    def size(self) -> int:
        return self._size

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def writable(self) -> bool:
        return False

    def tell(self) -> int:
        self._check_open()
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        self._check_open()
        if whence == io.SEEK_SET:
            new = offset
        elif whence == io.SEEK_CUR:
            new = self._pos + offset
        elif whence == io.SEEK_END:
            new = self._size + offset
        else:
            raise ValueError(f"invalid whence {whence}")
        if new < 0:
            raise ValueError(f"negative seek position {new}")
        self._pos = new
        return new

    def readinto(self, buffer: memoryview) -> int:  # type: ignore[override]
        self._check_open()
        if self._pos >= self._size or len(buffer) == 0:
            return 0
        index = bisect.bisect_right(self._starts, self._pos) - 1
        while self.part_sizes[index] == 0:  # an empty part holds no bytes
            index += 1
        offset = self._pos - self._starts[index]
        n = min(len(buffer), self.part_sizes[index] - offset)
        handle = self._files[index]
        handle.seek(offset)
        data = handle.read(n)
        if len(data) != n:
            raise MultipartError(f"part {index} returned {len(data)} bytes, expected {n}")
        buffer[:n] = data
        self._pos += n
        return n

    def part_and_whole_sha256(self, chunk: int = 1024 * 1024) -> tuple[list[str], str]:
        """One sequential pass from offset 0: each part's SHA-256 and the whole stream's."""
        self.seek(0)
        whole = hashlib.sha256()
        per_part: list[str] = []
        for size in self.part_sizes:
            digest = hashlib.sha256()
            remaining = size
            while remaining:
                data = self.read(min(chunk, remaining))
                if not data:
                    raise MultipartError("unexpected end of a part while hashing")
                digest.update(data)
                whole.update(data)
                remaining -= len(data)
            per_part.append(digest.hexdigest())
        return per_part, whole.hexdigest()

    def close(self) -> None:
        for f in getattr(self, "_files", []):
            f.close()
        super().close()

    def _check_open(self) -> None:
        if self.closed:
            raise ValueError("I/O operation on closed ConcatReader")
