"""Split-archive import without reassembly (``bot.data.multipart``, ``import-archive``).

Every archive here is SYNTHETIC (tests/data/archive_fixtures.py), split into parts at
awkward byte offsets: inside a member's compressed data, inside the central directory and
inside the end-of-central-directory record. No network.
"""

from __future__ import annotations

import hashlib
import io
import shutil
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from bot import cli
from bot.config import Settings, load_settings
from bot.data import archive as archive_mod
from bot.data.archive import ArchiveError, import_archive
from bot.data.cache import read_cache
from bot.data.multipart import (
    ConcatReader,
    MultipartError,
    check_part_order,
    parse_sums_file,
)
from tests.conftest import REPO_ROOT
from tests.data.archive_fixtures import decoys, sha256_hex, standard_members
from tests.data.fakes import TICK, FakeExchange

ALL_TFS = ("1d", "4h", "15m")
PART = "Kraken_OHLCVT_Full.zip.part{:02d}"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    shutil.copy(REPO_ROOT / "config.yaml", root / "config.yaml")
    return root


@pytest.fixture(autouse=True)
def exchange(monkeypatch: pytest.MonkeyPatch) -> FakeExchange:
    ex = FakeExchange()
    monkeypatch.setattr(cli, "_exchange_factory", lambda: ex)
    return ex


def _settings(repo: Path) -> Settings:
    return load_settings(repo / "config.yaml", repo / "none.env")


def _zip_bytes() -> bytes:
    """A SYNTHETIC archive with decoys and 200 rows per XBTEUR member (deflated)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for name, content in [*decoys(), *standard_members(n=200)]:
            zf.writestr(name, content)
    return buf.getvalue()


def _awkward_offsets(data: bytes) -> list[int]:
    """Cut points: inside XBTEUR_1440.csv's data, inside the central directory, inside EOCD."""
    zf = zipfile.ZipFile(io.BytesIO(data))
    member = zf.getinfo("XBTEUR_1440.csv")
    inside_member = member.header_offset + 30 + len(member.filename) + member.compress_size // 2
    inside_central_dir = zf.start_dir + 7
    inside_eocd = len(data) - 9
    return sorted({17, inside_member, inside_central_dir, inside_eocd})


def _split(data: bytes, offsets: list[int], folder: Path) -> tuple[list[Path], Path]:
    """Write the parts and a sha256sum-style checksum file; return (parts, sums path)."""
    folder.mkdir(parents=True, exist_ok=True)
    bounds = [0, *offsets, len(data)]
    parts = []
    for i, (a, b) in enumerate(zip(bounds, bounds[1:], strict=False)):
        p = folder / PART.format(i)
        p.write_bytes(data[a:b])
        parts.append(p)
    sums = folder / "SUMS.txt"
    sums.write_text(
        "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n" for p in parts),
        encoding="ascii",
    )
    return parts, sums


@pytest.fixture
def split(tmp_path: Path) -> tuple[bytes, list[Path], Path]:
    data = _zip_bytes()
    parts, sums = _split(data, _awkward_offsets(data), tmp_path / "parts")
    return data, parts, sums


def _whole(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _no_zip_parsing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("zipfile.ZipFile must not be reached before the checksums pass")

    monkeypatch.setattr(archive_mod.zipfile, "ZipFile", _boom)


# --- ConcatReader ---------------------------------------------------------------------------


def test_concat_reader_matches_the_original_bytes_across_boundaries(split) -> None:
    data, parts, _ = split
    with ConcatReader(parts) as raw:
        assert raw.size == len(data) and sum(raw.part_sizes) == len(data)
        # Raw reads may stop at a part boundary (RawIOBase semantics); the importer wraps the
        # reader in io.BufferedReader, which returns exactly n bytes until EOF.
        assert len(raw.read(len(data))) == raw.part_sizes[0]  # stops at the first boundary
        raw.seek(0)
        r = io.BufferedReader(raw, buffer_size=8)
        assert r.read() == data
        for pos, n in [(0, 5), (15, 10), (len(data) - 12, 50), (len(data) // 2, 4096)]:
            r.seek(pos)
            assert r.read(n) == data[pos : pos + n]
        assert r.seek(-3, io.SEEK_END) == len(data) - 3 and r.read() == data[-3:]
        r.seek(10)
        assert r.seek(5, io.SEEK_CUR) == 15 and r.tell() == 15
        r.seek(len(data) + 10)
        assert r.read(4) == b""
        with pytest.raises(ValueError):
            raw.seek(-1)
        assert not raw.writable()


def test_concat_reader_skips_empty_parts(tmp_path: Path) -> None:
    folder = tmp_path / "p"
    folder.mkdir()
    paths = []
    for i, chunk in enumerate([b"abc", b"", b"de", b""]):
        p = folder / f"x{i}"
        p.write_bytes(chunk)
        paths.append(p)
    with ConcatReader(paths) as r:
        assert r.read() == b"abcde"
        r.seek(3)
        assert r.read(1) == b"d"


def test_concat_reader_fails_loudly_when_a_part_shrinks(split) -> None:
    _, parts, _ = split
    with ConcatReader(parts) as r:
        parts[-1].write_bytes(b"")  # truncated after opening (Windows allows rewriting)
        r.seek(r.size - 2)
        with pytest.raises(MultipartError, match="returned 0 bytes"):
            r.read(2)


def test_zipfile_opens_the_concatenation(split) -> None:
    data, parts, _ = split
    with ConcatReader(parts) as r, zipfile.ZipFile(io.BufferedReader(r)) as zf:
        assert zf.read("XBTEUR_240.csv") == zipfile.ZipFile(io.BytesIO(data)).read("XBTEUR_240.csv")


def test_part_and_whole_sha256_in_one_pass(split) -> None:
    data, parts, _ = split
    with ConcatReader(parts) as r:
        per_part, whole = r.part_and_whole_sha256(chunk=7)
    assert per_part == [sha256_hex(p) for p in parts]
    assert whole == _whole(data)


# --- checksum list and part order ------------------------------------------------------------


def test_parse_sums_file_reads_sha256sum_output(tmp_path: Path) -> None:
    f = tmp_path / "s.txt"
    f.write_text(f"{'A' * 64}  a.part00\n\n{'b' * 64} *a.part01\n", encoding="ascii")
    assert parse_sums_file(f) == [("a.part00", "a" * 64), ("a.part01", "b" * 64)]


@pytest.mark.parametrize(
    ("text", "match"),
    [
        ("not a checksum line\n", "not a '<sha256>  <name>' line"),
        (f"{'a' * 63}  x\n", "not a"),
        (f"{'a' * 64}  ../x\n", "path separator"),
        (f"{'a' * 64}  dir\\x\n", "path separator"),
        (f"{'a' * 64}  x\n{'b' * 64}  x\n", "listed twice"),
        ("\n\n", "no checksum lines"),
    ],
)
def test_parse_sums_file_refuses_bad_lines(tmp_path: Path, text: str, match: str) -> None:
    f = tmp_path / "s.txt"
    f.write_text(text, encoding="ascii")
    with pytest.raises(MultipartError, match=match):
        parse_sums_file(f)


@pytest.mark.parametrize(
    ("order", "match"),
    [
        ([0, 2, 1, 3, 4], "out of order"),
        ([0, 1, 3, 4], "missing part"),
        ([0, 1, 1, 2, 3, 4], "given twice"),
    ],
)
def test_part_order_is_enforced(split, order: list[int], match: str) -> None:
    _, parts, sums = split
    with pytest.raises(MultipartError, match=match):
        check_part_order([parts[i] for i in order], parse_sums_file(sums))


def test_extra_part_not_in_the_list_is_refused(split, tmp_path: Path) -> None:
    _, parts, sums = split
    extra = tmp_path / "parts" / "stray.bin"
    extra.write_bytes(b"x")
    with pytest.raises(MultipartError, match="not in the checksum list"):
        check_part_order([*parts, extra], parse_sums_file(sums))


# --- import_archive over parts ---------------------------------------------------------------


def test_split_import_equals_single_file_import(split, repo: Path, tmp_path: Path) -> None:
    data, parts, sums = split
    out = import_archive(
        _settings(repo),
        parts,
        _whole(data),
        ALL_TFS,
        tick_provider=lambda: TICK,
        part_sums=sums,
    )
    single_repo = tmp_path / "single"
    single_repo.mkdir()
    shutil.copy(REPO_ROOT / "config.yaml", single_repo / "config.yaml")
    single = tmp_path / "single.zip"
    single.write_bytes(data)
    ref = import_archive(
        _settings(single_repo), single, _whole(data), ALL_TFS, tick_provider=lambda: TICK
    )
    for tf in ALL_TFS:
        pd.testing.assert_frame_equal(out[tf], ref[tf])
        assert len(out[tf]) == 200 and set(out[tf]["source"]) == {"archive"}
        cached = read_cache(repo / "var" / "data" / "BTC-EUR" / f"{tf}.parquet")
        assert cached is not None and len(cached) == 200


def test_bad_part_hash_refused_before_zip_parsing(split, repo: Path, monkeypatch) -> None:
    data, parts, sums = split
    raw = bytearray(parts[2].read_bytes())
    raw[0] ^= 0xFF  # corrupt part02; the checksum list still has the published value
    parts[2].write_bytes(bytes(raw))
    _no_zip_parsing(monkeypatch)
    with pytest.raises(ArchiveError, match=r"part checksum mismatch for .*part02"):
        import_archive(
            _settings(repo), parts, _whole(data), ALL_TFS, tick_provider=lambda: TICK,
            part_sums=sums,
        )  # fmt: skip
    assert not (repo / "var").exists()


def test_bad_whole_hash_refused_before_zip_parsing(split, repo: Path, monkeypatch) -> None:
    _, parts, sums = split
    _no_zip_parsing(monkeypatch)
    with pytest.raises(ArchiveError, match="checksum mismatch for the concatenated parts"):
        import_archive(
            _settings(repo), parts, "0" * 64, ALL_TFS, tick_provider=lambda: TICK,
            part_sums=sums,
        )  # fmt: skip
    assert not (repo / "var").exists()


def test_parts_and_matching_list_but_tampered_list_is_refused(split, repo, monkeypatch) -> None:
    """A part replaced together with its listed checksum still fails the whole-file hash."""
    data, parts, sums = split
    parts[1].write_bytes(b"evil" + parts[1].read_bytes()[4:])
    lines = sums.read_text(encoding="ascii").splitlines()
    lines[1] = f"{sha256_hex(parts[1])}  {parts[1].name}"
    sums.write_text("\n".join(lines) + "\n", encoding="ascii")
    _no_zip_parsing(monkeypatch)
    with pytest.raises(ArchiveError, match="concatenated parts"):
        import_archive(
            _settings(repo), parts, _whole(data), ALL_TFS, tick_provider=lambda: TICK,
            part_sums=sums,
        )  # fmt: skip


def test_missing_part_refused_before_opening_parts(split, repo, monkeypatch) -> None:
    data, parts, sums = split

    def _boom(*_a: object, **_k: object) -> None:
        raise AssertionError("parts must not be opened when the list does not match")

    monkeypatch.setattr(archive_mod, "ConcatReader", _boom)
    with pytest.raises(ArchiveError, match="missing part"):
        import_archive(
            _settings(repo), parts[:-1], _whole(data), ALL_TFS, tick_provider=lambda: TICK,
            part_sums=sums,
        )  # fmt: skip


def test_several_parts_need_part_sums(split, repo: Path) -> None:
    data, parts, _ = split
    with pytest.raises(ArchiveError, match="need --part-sums"):
        import_archive(_settings(repo), parts, _whole(data), ALL_TFS, tick_provider=lambda: TICK)


def test_part_sums_with_a_single_zip_is_refused(split, repo: Path) -> None:
    data, parts, sums = split
    with pytest.raises(ArchiveError, match="give --zip once per part"):
        import_archive(
            _settings(repo), [parts[0]], _whole(data), ALL_TFS, tick_provider=lambda: TICK,
            part_sums=sums,
        )  # fmt: skip


# --- CLI ---------------------------------------------------------------------------------


def _cli(repo: Path, *extra: str) -> int:
    base = ["--config", str(repo / "config.yaml"), "--env-file", str(repo / "none.env")]
    return cli.main(["data", "import-archive", *extra, *base], env={})


def test_cli_imports_parts_in_place(split, repo: Path, capsys, network_attempts) -> None:
    data, parts, sums = split
    zips = [arg for p in parts for arg in ("--zip", str(p))]
    code = _cli(repo, *zips, "--part-sums", str(sums), "--sha256", _whole(data))
    captured = capsys.readouterr()
    assert code == cli.EXIT_OK, captured.err
    for tf in ALL_TFS:
        assert f"{tf}: rows=200" in captured.out
    assert network_attempts == []


def test_cli_out_of_order_parts_exit_4(split, repo: Path, capsys) -> None:
    data, parts, sums = split
    order = [parts[1], parts[0], *parts[2:]]
    zips = [arg for p in order for arg in ("--zip", str(p))]
    assert _cli(repo, *zips, "--part-sums", str(sums), "--sha256", _whole(data)) == 4
    assert "parts out of order" in capsys.readouterr().err
    assert not (repo / "var").exists()
