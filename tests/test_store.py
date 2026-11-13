"""SQLite store schema v1 (architecture §2, AD-7, AD-17, AD-26)."""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from bot import store as store_mod
from bot.store import SCHEMA_VERSION, Store, StoreError, dec, iso, parse_iso

T0 = datetime(2024, 1, 2, tzinfo=UTC)

TABLES = {
    "schema_meta", "runs", "heartbeats", "signals", "intents", "orders", "order_events",
    "fills", "equity_snapshots", "equity_baselines", "risk_snapshots", "risk_events",
    "halts", "operator_actions", "errors", "api_calls", "signal_counterfactuals",
    "backtest_predictions", "weekly_reviews", "paper_balances", "paper_orders", "paper_fills",
}  # fmt: skip
INDEXES = {
    "one_active_intent_per_pair", "one_live_order_per_intent", "one_day_open_per_day",
    "one_active_halt_per_rule",
}  # fmt: skip


@pytest.fixture
def st() -> Store:
    s = Store.open(":memory:")
    s.init_account(initial_quote=Decimal("20"), initial_base=Decimal("0"), at=T0, mode="backtest")
    return s


def _run(st: Store) -> int:
    return st.insert(
        "runs", started_at=iso(T0), mode="backtest", strategy_id="v0_trend", git_commit="abc",
        git_dirty=0, config_hash="c", limits_hash="l", pid=1,
    )  # fmt: skip


def _signal(st: Store, run_id: int, candle: str = "2024-01-01T00:00:00.000Z") -> str:
    sid = f"v0_trend|BTC/EUR|1d|{candle}"
    st.insert(
        "signals", signal_id=sid, run_id=run_id, strategy_id="v0_trend", pair="BTC/EUR",
        timeframe="1d", candle_open_at=candle, evaluated_at=iso(T0), target_fraction="1",
        signal_price="40000", indicators_json="{}", outcome="pending",
    )  # fmt: skip
    return sid


def _intent(st: Store, sid: str, state: str = "working") -> int:
    return st.insert(
        "intents", signal_id=sid, pair="BTC/EUR", side="buy", reference_price="40000",
        target_qty="0.0004", state=state, approval_mode="autonomous",
        window_end_at=iso(T0), created_at=iso(T0), updated_at=iso(T0),
    )  # fmt: skip


def _order(st: Store, intent_id: int, cl: str, attempt: int = 1, state: str = "open") -> int:
    return st.insert(
        "orders", intent_id=intent_id, attempt_no=attempt, cl_ord_id=cl, side="buy",
        limit_price="40000", qty="0.0004", state=state, created_at=iso(T0),
    )  # fmt: skip


def _fill(st: Store, order_id: int, trade: str, side: str, qty: str, price: str, fee: str,
          at: datetime = T0) -> None:  # fmt: skip
    st.insert(
        "fills", exchange="paper", exchange_trade_id=trade, order_id=order_id, at=iso(at),
        pair="BTC/EUR", base="BTC", quote_ccy="EUR", side=side, qty=qty, price=price, fee=fee,
        fee_ccy="EUR", liquidity="maker", reference_price=price, slippage_bps=0.0,
        quote_is_fiat=1, simulated=1,
    )  # fmt: skip


def test_every_table_index_and_the_ledger_view_exist(st: Store) -> None:
    rows = st.all("SELECT type, name FROM sqlite_master")
    names = {(r["type"], r["name"]) for r in rows}
    assert {n for t, n in names if t == "table"} >= TABLES
    assert {n for t, n in names if t == "index"} >= INDEXES
    assert ("view", "ledger") in names
    assert st.get_meta("schema_version") == str(SCHEMA_VERSION)


def test_pragmas_on_a_file_store(tmp_path: Path) -> None:
    s = Store.open(tmp_path / "x.sqlite")
    assert s.one("PRAGMA journal_mode")[0] == "wal"
    assert s.one("PRAGMA synchronous")[0] == 2  # FULL
    assert s.one("PRAGMA foreign_keys")[0] == 1
    s.close()
    # Reopening an existing store does not re-apply the migration.
    s2 = Store.open(tmp_path / "x.sqlite")
    assert s2.get_meta("schema_version") == str(SCHEMA_VERSION)
    s2.close()


def test_version_mismatch_refuses_to_open(tmp_path: Path, monkeypatch) -> None:
    Store.open(tmp_path / "x.sqlite").close()
    monkeypatch.setattr(store_mod, "SCHEMA_VERSION", SCHEMA_VERSION + 1)
    with pytest.raises(StoreError, match="schema_version"):
        Store.open_readonly(tmp_path / "x.sqlite")


def test_newer_store_is_refused(tmp_path: Path, monkeypatch) -> None:
    Store.open(tmp_path / "x.sqlite").close()
    monkeypatch.setattr(store_mod, "SCHEMA_VERSION", 0)
    with pytest.raises(StoreError, match="newer"):
        Store.open(tmp_path / "x.sqlite")


def test_read_only_never_creates_and_refuses_writes(tmp_path: Path) -> None:
    with pytest.raises(StoreError):
        Store.open_readonly(tmp_path / "missing.sqlite")
    assert not (tmp_path / "missing.sqlite").exists()
    Store.open(tmp_path / "x.sqlite").close()
    ro = Store.open_readonly(tmp_path / "x.sqlite")
    with pytest.raises((StoreError, sqlite3.OperationalError)):
        ro.insert("schema_meta", key="k", value="v")


def test_schema_meta_initial_values_are_write_once(st: Store) -> None:
    with pytest.raises(StoreError):
        st.set_meta_once("initial_quote", "1000")
    with pytest.raises(sqlite3.IntegrityError):
        st.execute("UPDATE schema_meta SET value='1000' WHERE key='initial_quote'")
    with pytest.raises(sqlite3.IntegrityError):
        st.execute("DELETE FROM schema_meta WHERE key='initial_quote'")
    assert st.get_meta("initial_quote") == "20"


def test_duplicate_signal_is_refused(st: Store) -> None:
    run = _run(st)
    _signal(st, run)
    with pytest.raises(sqlite3.IntegrityError):
        _signal(st, run)


def test_duplicate_cl_ord_id_and_second_live_order_are_refused(st: Store) -> None:
    run = _run(st)
    intent = _intent(st, _signal(st, run))
    _order(st, intent, "c1", 1, state="cancelled")
    with pytest.raises(sqlite3.IntegrityError):
        _order(st, intent, "c1", 2)
    _order(st, intent, "c2", 2, state="open")
    with pytest.raises(sqlite3.IntegrityError):  # one_live_order_per_intent
        _order(st, intent, "c3", 3, state="open")


def test_one_active_intent_per_pair(st: Store) -> None:
    run = _run(st)
    _intent(st, _signal(st, run, "2024-01-01T00:00:00.000Z"))
    with pytest.raises(sqlite3.IntegrityError):
        _intent(st, _signal(st, run, "2024-01-02T00:00:00.000Z"))


def test_duplicate_trade_id_is_refused(st: Store) -> None:
    order = _order(st, _intent(st, _signal(st, _run(st))), "c1")
    _fill(st, order, "T1", "buy", "0.0004", "40000", "0.064")
    with pytest.raises(sqlite3.IntegrityError):
        _fill(st, order, "T1", "buy", "0.0004", "40000", "0.064")


def test_fill_fee_currency_must_be_the_quote(st: Store) -> None:
    order = _order(st, _intent(st, _signal(st, _run(st))), "c1")
    with pytest.raises(sqlite3.IntegrityError):
        st.insert(
            "fills", exchange="paper", exchange_trade_id="T9", order_id=order, at=iso(T0),
            pair="BTC/EUR", base="BTC", quote_ccy="EUR", side="sell", qty="1", price="1",
            fee="0.001", fee_ccy="BTC", liquidity="maker", reference_price="1",
            slippage_bps=0.0, quote_is_fiat=1, simulated=1,
        )  # fmt: skip


def test_second_active_halt_for_a_rule_is_refused(st: Store) -> None:
    st.insert("halts", rule="daily_loss", triggered_at=iso(T0), reason="r")
    with pytest.raises(sqlite3.IntegrityError):
        st.insert("halts", rule="daily_loss", triggered_at=iso(T0), reason="r2")


def test_second_day_open_snapshot_is_refused(st: Store) -> None:
    row = dict(equity="20", cash="20", base_qty="0", mark_price="1", buy_hold_equity="20")
    st.insert("equity_snapshots", at="2024-01-02T00:00:30.000Z", is_day_open=1, **row)
    st.insert("equity_snapshots", at="2024-01-02T06:00:30.000Z", is_day_open=0, **row)
    with pytest.raises(sqlite3.IntegrityError):
        st.insert("equity_snapshots", at="2024-01-02T12:00:30.000Z", is_day_open=1, **row)


def test_equity_baselines_and_fills_are_append_only(st: Store) -> None:
    st.insert("equity_baselines", at=iso(T0), equity="20", reason="start")
    with pytest.raises(sqlite3.IntegrityError):
        st.execute("UPDATE equity_baselines SET equity='1'")
    order = _order(st, _intent(st, _signal(st, _run(st))), "c1")
    _fill(st, order, "T1", "buy", "0.0004", "40000", "0.064")
    with pytest.raises(sqlite3.IntegrityError):
        st.execute("UPDATE fills SET qty='1'")


def test_derived_position_cash_and_equity_match_a_hand_computed_sequence(st: Store) -> None:
    order = _order(st, _intent(st, _signal(st, _run(st))), "c1")
    t1 = datetime(2024, 1, 3, tzinfo=UTC)
    t2 = datetime(2024, 1, 10, tzinfo=UTC)
    _fill(st, order, "T1", "buy", "0.0004", "40000", "0.064", at=t1)  # cost 16 + 0.064
    _fill(st, order, "T2", "sell", "0.0004", "45000", "0.072", at=t2)  # proceeds 18 - 0.072
    # After the buy: cash 20 - 16.064 = 3.936; position 0.0004.
    assert st.cash(until=t1) == Decimal("3.936")
    assert st.position("BTC/EUR", until=t1) == Decimal("0.0004")
    assert st.equity_at(t1, Decimal("41000")) == Decimal("3.936") + Decimal("16.4")
    # After the sell: cash 3.936 + 17.928 = 21.864; flat.
    assert st.cash() == Decimal("21.864")
    assert st.position("BTC/EUR") == Decimal(0)
    assert st.equity_at(t2, Decimal("99999")) == Decimal("21.864")
    assert st.total_fees() == Decimal("0.136")
    assert isinstance(st.cash(), Decimal)


def test_ledger_view_marks_crypto_to_fiat_disposals(st: Store) -> None:
    order = _order(st, _intent(st, _signal(st, _run(st))), "c1")
    _fill(st, order, "T1", "buy", "0.0004", "40000", "0.064")
    _fill(st, order, "T2", "sell", "0.0004", "45000", "0.072", at=datetime(2024, 1, 5, tzinfo=UTC))
    rows = st.all("SELECT side, is_crypto_to_fiat_disposal FROM ledger")
    assert [(r[0], r[1]) for r in rows] == [("buy", 0), ("sell", 1)]


def test_transaction_rolls_back_on_error(st: Store) -> None:
    with pytest.raises(RuntimeError), st.transaction():
        st.insert("halts", rule="daily_loss", triggered_at=iso(T0), reason="r")
        raise RuntimeError("boom")
    assert st.all("SELECT * FROM halts") == []


def test_iso_and_dec_helpers() -> None:
    t = datetime(2026, 11, 11, 0, 0, 0, 123456, tzinfo=UTC)
    assert iso(t) == "2026-11-11T00:00:00.123Z"
    assert parse_iso("2026-11-11T00:00:00.123Z") == t.replace(microsecond=123000)
    with pytest.raises(ValueError):
        iso(datetime(2026, 1, 1))  # noqa: DTZ001
    assert dec(Decimal("1E-8")) == "0.00000001"
    with pytest.raises(ValueError):
        dec(Decimal("NaN"))


def test_append_only_triggers_refuse_deletes_and_order_event_edits(st: Store) -> None:
    st.insert("equity_baselines", at=iso(T0), equity="20", reason="start")
    order = _order(st, _intent(st, _signal(st, _run(st))), "c1")
    _fill(st, order, "T1", "buy", "0.0004", "40000", "0.064")
    st.insert("order_events", order_id=order, at=iso(T0), to_state="open", detail_json="{}")
    for sql in (
        "DELETE FROM equity_baselines",
        "DELETE FROM fills",
        "DELETE FROM order_events",
        "UPDATE order_events SET to_state='x'",
    ):
        with pytest.raises(sqlite3.IntegrityError):
            st.execute(sql)


def test_fill_side_must_be_buy_or_sell(st: Store) -> None:
    order = _order(st, _intent(st, _signal(st, _run(st))), "c1")
    with pytest.raises(sqlite3.IntegrityError):
        _fill(st, order, "T1", "BUY", "0.0004", "40000", "0.064")


def test_read_write_open_refuses_an_older_store(tmp_path: Path, monkeypatch) -> None:
    Store.open(tmp_path / "x.sqlite").close()
    monkeypatch.setattr(store_mod, "SCHEMA_VERSION", SCHEMA_VERSION + 1)
    with pytest.raises(StoreError, match="schema_version"):
        Store.open(tmp_path / "x.sqlite")


def test_foreign_sqlite_file_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "other.sqlite"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE t (x)")
    con.commit()
    con.close()
    with pytest.raises(StoreError, match="not a trading-bot store"):
        Store.open(path)


def test_position_for_another_pair_is_refused(st: Store) -> None:
    st.set_meta_once("pair", "BTC/EUR")
    with pytest.raises(StoreError):
        st.position("ETH/EUR")


def test_schema_version_is_the_only_updatable_meta_key(st: Store) -> None:
    st.execute("UPDATE schema_meta SET value='1' WHERE key='schema_version'")
    with pytest.raises(sqlite3.IntegrityError):
        st.execute("UPDATE schema_meta SET key='schema_version' WHERE key='initial_base'")


def test_failed_commit_leaves_no_dangling_transaction(st: Store) -> None:
    st.execute("PRAGMA defer_foreign_keys=ON")  # the FK violation surfaces at COMMIT
    with pytest.raises(sqlite3.IntegrityError), st.transaction():
        st.insert("heartbeats", run_id=999, at=iso(T0), loop_state="x")
    assert not st._conn.in_transaction  # noqa: SLF001
    with st.transaction():
        st.insert("halts", rule="daily_loss", triggered_at=iso(T0), reason="r")
    assert len(st.all("SELECT * FROM halts")) == 1


def test_v1_store_migrates_to_v2_keeping_intents(tmp_path: Path) -> None:
    """Audit M2 F-3: schema v2 rebuilds intents with parent_intent_id; v1 rows survive."""
    path = tmp_path / "v1.sqlite"
    v1_only = [(1, store_mod.MIGRATIONS_DIR / "0001_init.sql")]
    with pytest.MonkeyPatch.context() as mp:  # build a v1 store, then open it with v2 code
        mp.setattr(store_mod, "SCHEMA_VERSION", 1)
        mp.setattr(store_mod, "_migrations", lambda: v1_only)
        s1 = Store.open(path)
        s1.init_account(initial_quote=Decimal("20"), initial_base=Decimal("0"), at=T0)
        intent = _intent(s1, _signal(s1, _run(s1)), state="done")
        _order(s1, intent, "c1", state="filled")
        assert s1.get_meta("schema_version") == "1"
        s1.close()
    s2 = Store.open(path)
    assert s2.get_meta("schema_version") == str(SCHEMA_VERSION)
    assert s2.one("SELECT parent_intent_id FROM intents WHERE intent_id = ?", (intent,))[0] is None
    assert s2.one("SELECT count(*) FROM orders")[0] == 1
    assert s2.all("PRAGMA foreign_key_check") == []


def test_completion_intent_links_to_its_parent_without_a_signal(st: Store) -> None:
    parent = _intent(st, _signal(st, _run(st)), state="done")
    child = st.insert(
        "intents", parent_intent_id=parent, pair="BTC/EUR", side="buy", reference_price="1",
        target_qty="0.00006", state="working", approval_mode="autonomous",
        window_end_at=iso(T0), created_at=iso(T0), updated_at=iso(T0),
    )  # fmt: skip
    assert st.one("SELECT parent_intent_id FROM intents WHERE intent_id = ?", (child,))[0] == parent
    with pytest.raises(sqlite3.IntegrityError):  # a completion intent never sells
        st.insert(
            "intents", parent_intent_id=child, pair="BTC/EUR", side="sell", reference_price="1",
            target_qty="1", state="done", approval_mode="autonomous", window_end_at=iso(T0),
            created_at=iso(T0), updated_at=iso(T0),
        )  # fmt: skip
