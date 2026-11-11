---
title: 'Kraken OHLCVT archive import with checksum'
type: feature
ticket: '3'
created: '2026-11-11'
status: built
baseline_revision: '2d3a0b613d0e5fca741810c22944a213d4731369'
route: full
route_source: auto
risk: medium
review: quick
review_source: pinned
lenses_ran: [quick]
review_loop_iteration: 0
followup_review_recommended: false
context:
  - '{project-root}/docs/stories/initiative-trading-bot-v1/tickets/epic-m1-data/tickets/story-validation-fails-loudly-and-never-repairs-plan.md'
  - '{project-root}/docs/data-manifest.md'
warnings: []
deferred: []
---

<intent-contract>

## Intent

**Problem:** The public OHLC endpoint returns only the last 720 candles, so years of history must come from Kraken's official OHLCVT ZIP archive, which is large, untrusted input.

**Approach:** `bot data import-archive --zip <path> --sha256 <hex> [--timeframe TF]...` hashes the whole file first and refuses on mismatch before opening it as a ZIP; then streams only the exact members `XBTEUR_{1440,240,15}.csv` with `pandas.read_csv` (no extraction to disk), converts Unix seconds to UTC, tags `source="archive"`, applies the no-trade policy, validates, and writes the cache per timeframe.

## Boundaries & Constraints

**Always:** checksum verified (streamed `hashlib.sha256`, 1 MiB chunks, case-insensitive hex compare, 64 hex chars required) before any ZIP parsing; member chosen by exact name match (basename, any directory prefix allowed) — `AIXBTEUR_1440.csv`, `XBTEURC_1440.csv`, `XBTEUROP_1440.csv` must never match; exactly one matching member, else refuse; refuse encrypted members and members whose declared uncompressed size exceeds a cap (512 MiB) and stop reading if actual decompressed bytes exceed it; CSV read with explicit column names/dtypes and `header=None`; timestamps must be integral Unix seconds within [2013-01-01, 2100-01-01) else refuse (unit guard); the Kraken pair code `XBTEUR` and the interval mapping `{"1d": 1440, "4h": 240, "15m": 15}` live only in `bot/data/archive.py`; the pair mapping is `{"BTC/EUR": "XBTEUR"}` and an unmapped pair is refused; each timeframe is all-or-nothing (on error nothing is written for it, other timeframes already written stay); errors raise `ArchiveError` (or `DataValidationError`) and the CLI exits 4.

**Never:** extract members to disk, call `extractall`, execute or import anything from the archive, read members other than the needed CSVs; download anything (the operator supplies the file); new dependencies; touch protected files; weaken tests.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Wrong checksum | fixture ZIP, wrong `--sha256` | refused, no member read (prove: `zipfile.ZipFile` never constructed — monkeypatch it to fail) | `ArchiveError("checksum mismatch")`, exit 4 |
| Malformed `--sha256` | not 64 hex | refused before hashing | exit 4 (or argparse error 2) |
| Happy path | fixture ZIP with XBTEUR_1440/240/15 + decoys AIXBTEUR_1440, XBTEURC_1440 | three caches written, rows from XBTEUR only, `source=archive`, `trades` populated, UTC ms | none |
| Member in subfolder | `Kraken_OHLCVT/XBTEUR_240.csv` | matched | none |
| Missing member | no `XBTEUR_15.csv` for a requested tf | that tf refused naming the member | `ArchiveError` |
| Duplicate member names | two entries named `XBTEUR_1440.csv` | refused | `ArchiveError` |
| Oversize member | declared size > cap | refused | `ArchiveError` |
| Bad CSV | header row, wrong column count, non-numeric, ms timestamps | refused naming the member | `ArchiveError` |
| No-trade gap in archive | missing interval between archive rows | filled per `data.no_trade_policy` (story 2) | `fail` policy → error |
| Existing cache | cache already holds rows | story 4 owns the overlap merge; in this story, refuse if the target cache file exists and is non-empty unless story 4's merge exists (`ArchiveError("cache exists; merge arrives in story 4")`) | `ArchiveError` |

</intent-contract>

## Code Map

- `bot/data/archive.py` (new) -- `ArchiveError(RuntimeError)`; `ARCHIVE_PAIRS`, `ARCHIVE_INTERVALS`; `sha256_file(path)`; `verify_checksum(path, expected)`; `member_name(pair, tf)`; `find_member(zf, name)` exact basename match; `read_member(zf, info, tf) -> DataFrame` (normalized via `bot.data.cache.normalize`, `source="archive"`, `trades` Int64); `import_archive(settings, zip_path, expected_sha256, timeframes) -> dict[tf, DataFrame]` doing per-tf: read → `apply_no_trade_policy` → `validate_frame` → `write_cache`.
- `bot/data/cache.py`, `bot/data/validate.py` -- reuse (`normalize`, `write_cache`, `read_cache`, `cache_path`, `apply_no_trade_policy`, `validate_frame`); do not change their behaviour.
- `bot/cli.py` -- add `bot data import-archive --zip PATH --sha256 HEX [--timeframe TF]...`; prints per tf rows/first/last; exit 4 on error.
- `tests/data/archive_fixtures.py` (new) -- builds small synthetic Kraken-format ZIPs in `tmp_path` with stdlib `zipfile` (no header, Unix seconds), including decoys; label them synthetic in docstrings.
- `tests/data/test_archive.py` (new) -- every matrix row; plus an AST/grep test that `"XBTEUR"` appears in no `bot/` file other than `bot/data/archive.py`.
- Real archive facts (from `docs/data-manifest.md`): members sit at the ZIP root, rows like `1782864000,51302.0,53899.9,50650.1,52701.6,619.62760253,40702`; a `MANIFEST.json` member exists (ignore it).

## Tasks & Acceptance

**Execution:**
- [x] `bot/data/archive.py` -- checksum-first streaming importer -- AD-18, research B6
- [x] `bot/cli.py` -- `bot data import-archive` -- operator entry point
- [x] `tests/data/archive_fixtures.py`, `tests/data/test_archive.py` -- matrix coverage

**Acceptance Criteria:**
- Given a fixture ZIP and its correct sha256, when `bot data import-archive` runs, then 1d, 4h and 15m caches are written with `source=archive` and `bot data validate` exits 0.
- Given a wrong sha256, when import runs, then it exits 4 before any ZIP parsing.
- Given a fixture ZIP whose XBTEUR_1440.csv omits one day between two archive rows, when `bot data import-archive` runs with `no_trade_policy: fill_flat`, then the written cache holds a `synthetic` row for that day (flat at the previous close, volume 0) and `bot data validate` exits 0; with `fail` it exits 4 and writes nothing (closes story 2's deferred item: production writer fills, validates, writes).
- Writers must pass `apply_no_trade_policy` a frame that is sorted, unique, with exact dtypes (story 2 refuses anything else): build the archive frame with `bot.data.cache.normalize` and sort by `open_at` first.

## Implementation Notes

- Order in `import_archive`: map pair/timeframes to member names (unmapped refused) -> `verify_checksum` (format check, then streamed hash) -> `zipfile.ZipFile` -> per tf: refuse existing non-empty cache -> `find_member` -> `read_member` -> `apply_no_trade_policy` -> `validate_frame(now=clock.now())` -> `write_cache`. Stops at the first failing tf (`ArchiveError.timeframe` set, CLI prints `DATA ERROR [tf]: ...`); earlier tfs stay written. A per-tf `on_written` callback lets the CLI print `rows/first/last/synthetic` as each cache lands.
- `read_member`: refuses encrypted (flag bit 0x1) and declared size > `MAX_MEMBER_BYTES`; streams through a byte-counting `_CappedReader` (raises past the cap) into `pd.read_csv(header=None, dtype={0: int64, 1-5: float64, 6: int64}, encoding="ascii", compression=None)`. Then: exactly 7 columns, at least one row, no missing values, timestamps in [2013-01-01, 2100-01-01) Unix seconds (a fractional timestamp fails the int64 parse), finite prices/volume. Any parser/decode/zlib error is re-raised as `ArchiveError("member <name>: ...")`. Frame is sorted by `open_at` then built with `normalize`.
- Basename match splits on `/` and `\`; directory entries are ignored; a root and a subfolder copy of the same name count as duplicates and are refused.
- Existing cache: a cache file with rows is refused (`cache exists; merge arrives in story 4`); an empty cache file is replaced. An unreadable cache is refused.
- Malformed `--sha256` exits 4 (refused in `verify_checksum` before hashing), not argparse 2.
- Gap fixture uses 2015 dates (before `data.history_start`) so one synthetic row passes the ratio cap with a 6-row fixture.
- Story 2's deferred item (AC2 only through a stand-in writer) is now covered by `test_no_trade_gap_filled_flat_then_validates` through the production writer.
- Real archive check 2026-11-11 (temp var dir, not the repo `var/`): `Kraken_OHLCVT_2026Q3.zip` with the manifest sha256 -> exit 0 in ~3.5 s, 1d 92 / 4h 552 / 15m 8832 rows, synthetic 0, `bot data validate` exit 0; wrong sha256 -> exit 4 `checksum mismatch`; rerun -> exit 4 `cache exists`.

## Plan Change Log

## Review Triage Log

### 2026-11-11 — Review pass
- verdicts: 3 findings — high 0, medium 1, low 2, false 0, maybe-false 0
- findings:
  - `[medium]` `[patch]` encrypted-member test passed through a different error whose message contained "encrypted" (header signatures were unescaped control bytes, hard to audit) — escaped signatures, exact-message assertion proves `read_member`'s own check fires.
  - `[low]` `[patch]` checksum and ZIP parse used two opens of the path (TOCTOU) — single handle: hash, seek(0), parse.
  - `[low]` `[patch]` pair-code isolation test did not cover the interval mapping — AST scan for timeframe→minutes dicts added.

## Verification

**Commands:**
- `uv run ruff check . && uv run ruff format --check . && uv run pytest` -- expected: all pass

**Result 2026-11-11:** ruff check and format clean; 362 passed (41 new in `tests/data/test_archive.py`).

## Auto Run Result

- Review (orchestrator): 3 patches (1 medium, 2 low), 0 deferred, 0 rejected; follow-up review recommended: false.
- Verification: full check → 362 passed; scan for raw control bytes in bot/data and tests/data → none. Story 2's deferred AC (production writer fills, validates, writes) is now covered by the archive import tests.
- Real run by the implementer on `data/raw/kraken_ohlcvt/Kraken_OHLCVT_2026Q3.zip` into a scratch var dir: 92/552/8832 rows, 0 synthetic, validate exit 0; wrong checksum exit 4. The repo cache import runs in story 6 after story 4's merge.
