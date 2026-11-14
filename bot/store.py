"""SQLite persistence via stdlib sqlite3 (FR-39, architecture §2, AD-7, AD-17, AD-26).

One database per (mode, strategy): a file under ``var/state/`` or ``":memory:"`` (backtest).
Read-write connections set ``journal_mode=WAL``, ``synchronous=FULL``, ``foreign_keys=ON``
and ``busy_timeout=5000``; read-only connections (dashboard) open ``file:...?mode=ro`` and
set only ``busy_timeout``. Numbered migrations in ``bot/migrations/`` are applied at open;
``schema_meta.schema_version`` must equal ``SCHEMA_VERSION`` or opening fails.

Money and quantities are Decimal in Python and decimal TEXT in the database. Balances are
never stored: position, cash and equity are derived from the write-once account baseline
(``schema_meta.initial_*``) plus the fills (AD-26).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 3
MIGRATIONS_DIR = Path(__file__).resolve().parent / "migrations"


class StoreError(RuntimeError):
    """The database is missing, of another schema version, or a write-once rule was hit."""


def iso(t: datetime) -> str:
    """ISO-8601 UTC with milliseconds and ``Z`` (architecture §2 DDL conventions)."""
    if t.tzinfo is None or t.utcoffset() != timedelta(0):
        raise ValueError(f"store timestamps must be timezone-aware UTC, got {t!r}")
    return t.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def parse_iso(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=UTC)


def dec(d: Decimal | int | str) -> str:
    """Decimal TEXT without exponent notation."""
    value = Decimal(d)
    if not value.is_finite():
        raise ValueError(f"non-finite decimal {value}")
    return format(value, "f")


def _migrations() -> list[tuple[int, Path]]:
    out = []
    for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
        out.append((int(path.name.split("_", 1)[0]), path))
    return out


class Store:
    """A connection to one store. Build with ``Store.open`` or ``Store.open_readonly``."""

    def __init__(self, conn: sqlite3.Connection, read_only: bool) -> None:
        self._conn = conn
        self.read_only = read_only

    # --- opening ----------------------------------------------------------------------

    @classmethod
    def open(cls, path: str | Path) -> Store:
        """Open read-write, creating and migrating a new database.

        An existing SQLite file that is not a trading-bot store (tables but no
        ``schema_meta``) is refused, never migrated in place.
        """
        conn = sqlite3.connect(str(path), isolation_level=None)
        conn.row_factory = sqlite3.Row
        mode = conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
        if str(path) != ":memory:" and str(mode).lower() != "wal":
            conn.close()
            raise StoreError(f"could not enable WAL journal mode on {path} (got {mode})")
        for pragma in ("synchronous=FULL", "foreign_keys=ON", "busy_timeout=5000"):
            conn.execute(f"PRAGMA {pragma}")
        store = cls(conn, read_only=False)
        try:
            store._migrate()
        except BaseException:
            conn.close()
            raise
        return store

    @classmethod
    def open_existing(cls, path: Path) -> Store:
        """Open an EXISTING store read-write without creating or migrating it; refuses a
        schema version other than the code's. Used by the CLI to insert operator actions
        (AD-17): only the engine, holding its lock, creates or migrates a store."""
        if not Path(path).is_file():
            raise StoreError(f"no store at {path}")
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=rw", uri=True,
                               isolation_level=None)  # fmt: skip
        conn.row_factory = sqlite3.Row
        for pragma in ("foreign_keys=ON", "busy_timeout=5000"):
            conn.execute(f"PRAGMA {pragma}")
        store = cls(conn, read_only=False)
        try:
            store._check_version()
        except BaseException:
            conn.close()
            raise
        return store

    @classmethod
    def open_readonly(cls, path: Path) -> Store:
        """Open an existing file read-only (``mode=ro``); never creates it (AD-17)."""
        if not Path(path).is_file():
            raise StoreError(f"no store at {path}")
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA busy_timeout=5000")
        store = cls(conn, read_only=True)
        store._check_version()
        return store

    def close(self) -> None:
        self._conn.close()

    def backup(self, target: Path) -> None:
        """Online copy of the whole database to ``target`` (sqlite3 backup API), written
        to a temporary file first and then renamed, so a copy is never half-written."""
        target = Path(target)
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_name(target.name + ".tmp")
        dst = sqlite3.connect(str(tmp))
        try:
            self._conn.backup(dst)
        finally:
            dst.close()
        tmp.replace(target)

    def _has_table(self, name: str) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchone()
        return row is not None

    def _version(self) -> int:
        row = self._conn.execute(
            "SELECT value FROM schema_meta WHERE key='schema_version'"
        ).fetchone()
        if row is None:
            raise StoreError("schema_meta has no schema_version")
        return int(row["value"])

    def _check_version(self) -> None:
        if not self._has_table("schema_meta"):
            raise StoreError("not a trading-bot store (no schema_meta)")
        version = self._version()
        if version != SCHEMA_VERSION:
            raise StoreError(f"store schema_version {version} != code {SCHEMA_VERSION}")

    def _migrate(self) -> None:
        # The version is read inside the write transaction, so two processes opening a new
        # file cannot both apply a migration.
        for number, path in _migrations():
            # Table rebuilds need foreign keys off; the pragma only works outside a
            # transaction. Integrity is re-checked in full before COMMIT.
            self._conn.execute("PRAGMA foreign_keys=OFF")
            try:
                self._migrate_one(number, path)
            finally:
                self._conn.execute("PRAGMA foreign_keys=ON")
        self._check_version()

    def _migrate_one(self, number: int, path: Path) -> None:
        """Apply migration ``number`` if the store is older, in one transaction."""
        with self.transaction():
            if self._has_table("schema_meta"):
                current = self._version()
            else:
                others = self._conn.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
                if others:
                    raise StoreError("existing database is not a trading-bot store")
                current = 0
            if current > SCHEMA_VERSION:
                raise StoreError(
                    f"store schema_version {current} is newer than code {SCHEMA_VERSION}"
                )
            if number <= current or number > SCHEMA_VERSION:
                return
            for statement in _statements(path.read_text(encoding="utf-8")):
                self._conn.execute(statement)
            if current == 0:
                self._conn.execute(
                    "INSERT INTO schema_meta(key, value) VALUES ('schema_version', ?)",
                    (str(number),),
                )
            else:
                self._conn.execute(
                    "UPDATE schema_meta SET value = ? WHERE key = 'schema_version'",
                    (str(number),),
                )
            bad = self._conn.execute("PRAGMA foreign_key_check").fetchall()
            if bad:
                raise StoreError(f"migration {number} breaks foreign keys: {bad[:3]}")

    # --- low-level --------------------------------------------------------------------

    @contextmanager
    def transaction(self) -> Iterator[None]:
        """One atomic unit (AD-7). Nested use joins the outer transaction.

        If COMMIT fails the transaction is rolled back before the error propagates, so no
        later write can silently join a dangling transaction.
        """
        if self._conn.in_transaction:
            yield
            return
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._conn.execute("COMMIT")
        except BaseException:
            if self._conn.in_transaction:
                # Keep the original error; SQLite may have rolled back already.
                with suppress(sqlite3.Error):
                    self._conn.execute("ROLLBACK")
            raise

    def execute(self, sql: str, params: tuple[Any, ...] | Mapping[str, Any] = ()) -> sqlite3.Cursor:
        # A read-only store is opened with mode=ro: SQLite itself refuses every write.
        return self._conn.execute(sql, params)

    def insert(self, table: str, **cols: Any) -> int:
        names = ", ".join(cols)
        marks = ", ".join("?" for _ in cols)
        cur = self.execute(f"INSERT INTO {table} ({names}) VALUES ({marks})", tuple(cols.values()))  # noqa: S608
        return int(cur.lastrowid or 0)

    def update(self, table: str, key: str, key_value: Any, **cols: Any) -> None:
        sets = ", ".join(f"{c} = ?" for c in cols)
        cur = self.execute(
            f"UPDATE {table} SET {sets} WHERE {key} = ?",  # noqa: S608
            (*cols.values(), key_value),
        )
        if cur.rowcount != 1:
            raise StoreError(f"update of {table}.{key}={key_value!r} touched {cur.rowcount} rows")

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self.execute(sql, params).fetchone()

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return list(self.execute(sql, params).fetchall())

    # --- schema_meta (write-once) -----------------------------------------------------

    def get_meta(self, key: str) -> str | None:
        row = self.one("SELECT value FROM schema_meta WHERE key = ?", (key,))
        return None if row is None else str(row["value"])

    def set_meta_once(self, key: str, value: str) -> None:
        """Write a schema_meta key; refuses to overwrite an existing key (AD-26)."""
        try:
            self.insert("schema_meta", key=key, value=value)
        except sqlite3.IntegrityError as exc:
            raise StoreError(f"schema_meta.{key} is write-once and already set") from exc

    def init_account(
        self, *, initial_quote: Decimal, initial_base: Decimal, at: datetime, **meta: str
    ) -> None:
        """Write the account baseline once, in one transaction (AD-26)."""
        with self.transaction():
            self.set_meta_once("initial_quote", dec(initial_quote))
            self.set_meta_once("initial_base", dec(initial_base))
            self.set_meta_once("initial_at", iso(at))
            for key, value in meta.items():
                self.set_meta_once(key, value)

    # --- derived quantities (AD-26) ---------------------------------------------------

    def _initial(self, key: str) -> Decimal:
        value = self.get_meta(key)
        if value is None:
            raise StoreError(f"account baseline schema_meta.{key} is not set")
        return Decimal(value)

    def _fills(self, pair: str | None, until: datetime | None) -> list[sqlite3.Row]:
        store_pair = self.get_meta("pair")
        if pair is not None and store_pair is not None and pair != store_pair:
            raise StoreError(f"store holds {store_pair}, not {pair}")
        sql, params = "SELECT side, qty, price, fee FROM fills WHERE 1=1", []
        if pair is not None:
            sql += " AND pair = ?"
            params.append(pair)
        if until is not None:
            sql += " AND at <= ?"
            params.append(iso(until))
        return self.all(sql + " ORDER BY at, fill_id", tuple(params))

    def position(self, pair: str | None = None, until: datetime | None = None) -> Decimal:
        """initial_base + sum(buy qty) - sum(sell qty)."""
        pos = self._initial("initial_base")
        for f in self._fills(pair, until):
            qty = Decimal(f["qty"])
            pos += qty if _side(f["side"]) == "buy" else -qty
        return pos

    def cash(self, until: datetime | None = None) -> Decimal:
        """initial_quote - sum(buy qty x price + fee) + sum(sell qty x price - fee)."""
        cash = self._initial("initial_quote")
        for f in self._fills(None, until):
            gross = Decimal(f["qty"]) * Decimal(f["price"])
            fee = Decimal(f["fee"])
            cash += -(gross + fee) if _side(f["side"]) == "buy" else gross - fee
        return cash

    def equity_at(self, t: datetime, mark: Decimal, pair: str | None = None) -> Decimal:
        """cash + base x mark, using fills up to ``t``."""
        return self.cash(until=t) + self.position(pair, until=t) * mark

    def total_fees(self) -> Decimal:
        return sum((Decimal(r["fee"]) for r in self.all("SELECT fee FROM fills")), Decimal(0))


def _side(side: str) -> str:
    if side not in ("buy", "sell"):
        raise StoreError(f"fill side {side!r} is neither buy nor sell")
    return side


def _statements(script: str) -> list[str]:
    """Split a migration into statements; ``sqlite3.complete_statement`` handles triggers."""
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        if not buf and line.strip().startswith("--"):
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        raise StoreError(f"incomplete SQL statement in migration: {buf[:80]!r}")
    return out
