import sys
sys.path.insert(0, "app")
"""Tests for the V0.5.5 market history importer.

These tests stub the client/parser boundary with already-parsed
MarketHistoryEvent objects, isolating the importer's normalization,
persistence, and pagination logic from Steam HTML scraping.
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest
import requests
import sqlite3

from market_history_adapter import MarketHistoryEvent
from market_history_importer import (
    ImportResult,
    MarketHistoryImportError,
    MarketHistoryImporter,
)


# --- Schema helpers (match production V0.5.5) -----------------------------


def create_schema(conn):
    conn.executescript(
        """
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL CHECK(type IN ('BUY', 'SELL')),
            market_hash_name TEXT NOT NULL,
            quantity INTEGER NOT NULL CHECK(quantity > 0),
            unit_price TEXT NOT NULL,
            fees TEXT NOT NULL DEFAULT '0',
            total_value TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            external_ref TEXT
        );

        CREATE UNIQUE INDEX idx_transactions_bot_external_ref
        ON transactions(bot_name, external_ref)
        WHERE external_ref IS NOT NULL;

                CREATE TABLE acquisition_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_transaction_id INTEGER NOT NULL REFERENCES transactions(id),
            market_hash_name TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            original_quantity INTEGER NOT NULL CHECK(original_quantity > 0),
            remaining_quantity INTEGER NOT NULL,
            unit_cost TEXT,
            acquired_at TEXT NOT NULL,
            cost_status TEXT NOT NULL CHECK(cost_status IN ('TRACKED', 'UNKNOWN')),
            provenance TEXT,
            source_type TEXT,
            external_ref TEXT,
            FOREIGN KEY(source_transaction_id) REFERENCES transactions(id)
        );
        """
    )


# --- Event & page builders -------------------------------------------------


def make_event(**kwargs):
    defaults = dict(
        type="BUY",
        market_hash_name="Example Card",
        quantity=1,
        unit_price=Decimal("0.10"),
        fees=Decimal("0.02"),
        total_value=Decimal("0.12"),
        timestamp="2026-09-14T19:00:00Z",
        external_ref="ref-1",
    )
    defaults.update(kwargs)
    return MarketHistoryEvent(**defaults)


def make_page(events, total_count, start=0, pagesize=None):
    if pagesize is None:
        pagesize = max(len(events), 1)
    return {
        "success": True,
        "total_count": total_count,
        "pagesize": pagesize,
        "start": start,
        "_events": list(events),
    }


def make_importer(conn, bot_name, pages):
    """Create an importer with client/parser stubbed to return pre-parsed events."""
    importer = MarketHistoryImporter.__new__(MarketHistoryImporter)
    importer.session = Mock(spec=requests.Session)
    importer.conn = conn
    importer.bot_name = bot_name
    importer.base_url = "https://steamcommunity.com"

    page_iter = iter(pages)
    importer.client = Mock()
    importer.client.fetch_page = Mock(side_effect=lambda **kw: next(page_iter))
    importer.parser = Mock()
    importer.parser.parse_response = Mock(
        side_effect=lambda page: list(page.get("_events", []))
    )
    return importer


# --- Fixtures --------------------------------------------------------------


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def bot_name():
    return "Rixqor"


# --- Test 1: BUY with timestamp creates exactly one transaction, zero lots ---


def test_buy_with_timestamp_creates_one_transaction_no_lots(conn, bot_name):
    ev = make_event(external_ref="buy-only-tx")
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    result = importer.import_history()

    assert result.imported_count == 1
    assert result.skipped_count == 0
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 0

    tx = conn.execute("SELECT * FROM transactions WHERE external_ref='buy-only-tx'").fetchone()
    assert tx["type"] == "BUY"
    assert tx["market_hash_name"] == "Example Card"
    assert tx["quantity"] == 1
    assert tx["unit_price"] == "0.10"
    assert tx["fees"] == "0.02"
    assert tx["total_value"] == "0.12"
    assert tx["timestamp"] == "2026-09-14T19:00:00Z"
    assert tx["bot_name"] == "Rixqor"


# --- Test 2: SELL with timestamp creates exactly one transaction, zero lots ---


def test_sell_with_timestamp_creates_one_transaction_no_lots(conn, bot_name):
    ev = make_event(
        type="SELL", quantity=2, unit_price=Decimal("1.50"),
        fees=Decimal("0.23"), total_value=Decimal("3.00"),
        external_ref="sell-only-tx",
    )
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    result = importer.import_history()
    assert result.imported_count == 1
    assert result.skipped_count == 0
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 0

    tx = conn.execute("SELECT * FROM transactions WHERE external_ref='sell-only-tx'").fetchone()
    assert tx["type"] == "SELL"


# --- Test 3: Multiple pages are imported ---


def test_multiple_pages_imported(conn, bot_name):
    ev1 = make_event(unit_price=Decimal("0.10"), fees=Decimal("0.02"),
                     total_value=Decimal("0.12"),
                     timestamp="2026-09-14T19:00:00Z", external_ref="page1-buy")
    ev2 = make_event(unit_price=Decimal("0.20"), fees=Decimal("0.03"),
                     total_value=Decimal("0.40"),
                     timestamp="2026-09-15T19:00:00Z", external_ref="page2-buy")
    p1 = make_page([ev1], total_count=2, start=0, pagesize=1)
    p2 = make_page([ev2], total_count=2, start=1, pagesize=1)
    importer = make_importer(conn, bot_name, [p1, p2])
    result = importer.import_history(start=0, count=100)
    assert result.imported_count == 2
    assert result.skipped_count == 0
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


# --- Test 4: Pagination stops at total_count ---


def test_pagination_stops_at_total_count(conn, bot_name):
    events = [
        make_event(unit_price=Decimal("0.01"), fees=Decimal("0.00"),
                   total_value=Decimal("0.01"),
                   timestamp="2026-09-14T19:00:00Z", external_ref=f"event-{i}")
        for i in range(3)
    ]
    importer = make_importer(conn, bot_name, [make_page(events, total_count=3, start=0, pagesize=3)])
    result = importer.import_history(start=0, count=100)
    assert result.imported_count == 3
    assert result.skipped_count == 0


# --- Test 5: Duplicate external_ref does not create second transaction ---


def test_duplicate_external_ref_not_imported_twice(conn, bot_name):
    ev1 = make_event(market_hash_name="Dup Card", external_ref="dup-ref")
    ev2 = make_event(market_hash_name="Dup Card v2", external_ref="dup-ref")
    importer = make_importer(conn, bot_name, [make_page([ev1, ev2], total_count=2)])
    result = importer.import_history()
    assert result.imported_count == 1
    assert result.skipped_count == 1
    assert "duplicate" in result.skipped_reasons[0].lower()
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE external_ref='dup-ref'").fetchone()[0] == 1


# --- Test 5b: Duplicate is skipped on second import pass ---


def test_duplicate_skipped_on_second_import(conn, bot_name):
    ev = make_event(external_ref="dup-ref-2")
    importer1 = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    importer1.import_history()

    importer2 = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    result = importer2.import_history()
    assert result.imported_count == 0
    assert result.skipped_count == 1
    assert "duplicate" in result.skipped_reasons[0].lower()


# --- Test 6: fees=None is skipped ---


def test_fees_none_is_skipped(conn, bot_name):
    ev = make_event(fees=None, total_value=Decimal("0.10"), external_ref="no-fees")
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    result = importer.import_history()
    assert result.imported_count == 0
    assert result.skipped_count == 1
    assert "fees unavailable" in result.skipped_reasons[0]
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


# --- Test 7: timestamp=None is skipped ---


def test_timestamp_none_is_skipped(conn, bot_name):
    ev = make_event(timestamp=None, external_ref="no-timestamp-ref")
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    result = importer.import_history()
    assert result.imported_count == 0
    assert result.skipped_count == 1
    assert "timestamp unavailable" in result.skipped_reasons[0].lower()
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


# --- Test 8: No timestamp is fabricated ---


def test_no_timestamp_fabricated(conn, bot_name):
    ev = make_event(timestamp=None, external_ref="no-ts-ref-2")
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    result = importer.import_history()
    assert result.imported_count == 0
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


# --- Test 9: No acquisition cost is fabricated ---


def test_no_acquisition_cost_fabricated(conn, bot_name):
    ev = make_event(external_ref="no-cost")
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    importer.import_history()
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 0


# --- Test 10: BUY normalization retains cost_status UNKNOWN ---


def test_buy_normalization_cost_status_unknown(conn, bot_name):
    from historical_event_normalizer import normalize_market_history_event
    ev = make_event(type="BUY", external_ref="buy-unknown")
    normalized = normalize_market_history_event(ev)
    assert normalized.cost_status == "UNKNOWN"


# --- Test 11: SELL does not modify pre-existing acquisition_lots ---


def test_sell_does_not_modify_existing_lots(conn, bot_name):
    conn.execute(
        """INSERT INTO transactions
           (type, market_hash_name, quantity, unit_price, fees, total_value,
            timestamp, bot_name, external_ref)
           VALUES ('BUY','Existing Item',2,'0.50','0.00','1.00',
                   '2026-09-14T10:00:00Z','Rixqor','existing-buy')"""
    )
    conn.execute(
        """INSERT INTO acquisition_lots
           (source_transaction_id, market_hash_name, bot_name,
            original_quantity, remaining_quantity, unit_cost,
            acquired_at, cost_status)
           VALUES (1, 'Existing Item', 'Rixqor', 2, 2, '0.50',
                   '2026-09-14T10:00:00Z', 'TRACKED')"""
    )
    conn.commit()
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 1

    ev = make_event(type="SELL", market_hash_name="Existing Item",
                    unit_price=Decimal("0.60"), fees=Decimal("0.09"),
                    total_value=Decimal("0.60"),
                    external_ref="sell-modifies")
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    importer.import_history()
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 1
    rem = conn.execute("SELECT remaining_quantity FROM acquisition_lots WHERE id=1").fetchone()[0]
    assert rem == 2


# --- Test 12: Invalid normalized event is skipped/rejected safely ---


def test_invalid_normalized_event_skipped_safely(conn, bot_name):
    bad_event = make_event(market_hash_name="", fees=None, external_ref="bad-event")
    importer = make_importer(conn, bot_name, [make_page([bad_event], total_count=1)])
    result = importer.import_history()
    assert result.imported_count == 0
    assert result.skipped_count == 1
    assert "normalization error" in result.skipped_reasons[0].lower()
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


# --- Test 13: Database failure rolls back entire batch ---


def test_database_failure_rolls_back_batch(conn, bot_name):
    events = [
        make_event(external_ref="good-1"),
        make_event(external_ref="good-2"),
    ]
    importer = make_importer(conn, bot_name, [make_page(events, total_count=2)])

    call_count = [0]
    original_persist = MarketHistoryImporter._persist_event

    def failing_persist(self_nevent, nevent):
        call_count[0] += 1
        if call_count[0] == 2:
            raise sqlite3.OperationalError("disk I/O error")
        return original_persist(self_nevent, nevent)

    importer._persist_event = failing_persist.__get__(importer, MarketHistoryImporter)

    with pytest.raises(MarketHistoryImportError):
        importer.import_history()
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


# --- Test 14: Inventory tables are untouched ---


def test_inventory_tables_not_touched(conn, bot_name):
    ev = make_event(external_ref="no-inventory")
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    importer.import_history()
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "inventory_snapshots" not in tables
    assert "inventory_items" not in tables


# --- Test 15: No production DB path is referenced ---


def test_no_production_db_path():
    import inspect
    source = inspect.getsource(MarketHistoryImporter)
    assert "/data/tradebot.db" not in source
    assert "DB_PATH" not in source


# --- Test 16: Injected requests.Session is used (real client path) ---


def test_injected_session_is_used(conn, bot_name):
    ev = make_event(external_ref="session-test")
    page = make_page([ev], total_count=1)

    session = Mock(spec=requests.Session)
    mock_resp = Mock()
    mock_resp.raise_for_status.return_value = None
    mock_resp.json.return_value = page
    session.get.return_value = mock_resp

    importer = MarketHistoryImporter(session, conn, bot_name)
    importer.parser = Mock()
    importer.parser.parse_response = Mock(return_value=[ev])

    importer.import_history()

    session.get.assert_called_once()
    args, kwargs = session.get.call_args
    assert "/market/myhistory/render/" in args[0]
    params = kwargs.get("params", {})
    assert params.get("start") == 0
    assert params.get("count") == 100
    assert params.get("norender") == 1


# --- Test 17: No login/cookie acquisition occurs ---


def test_no_login_or_cookie_acquisition():
    import inspect
    source = inspect.getsource(MarketHistoryImporter)
    low = source.lower()
    assert "login" not in low
    assert "cookie" not in low
    assert "password" not in low
    assert "steamcommunity.com/login" not in low


# --- Test 18: Zero events returns safe ImportResult ---


def test_zero_events_safe_result(conn, bot_name):
    importer = make_importer(conn, bot_name, [make_page([], total_count=0)])
    result = importer.import_history()
    assert isinstance(result, ImportResult)
    assert result.imported_count == 0
    assert result.skipped_count == 0
    assert result.skipped_reasons == []


# --- Test 19: Source events are not mutated ---


def test_source_events_not_mutated(conn, bot_name):
    ev = make_event(external_ref="immutable-test")
    original_unit_price = ev.unit_price
    original_ref = ev.external_ref
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    importer.import_history()
    assert ev.unit_price == original_unit_price
    assert ev.external_ref == original_ref


# --- Test 20: No P&L/ROI/margin calculations ---


def test_no_profit_calculations():
    import inspect
    source = inspect.getsource(MarketHistoryImporter)
    low = source.lower()
    for term in ("profit", "roi", "margin", "pnl", "return_on_investment"):
        assert term not in low, f"found forbidden term: {term}"


# --- Test 21: Successful BUY creates NO acquisition lot ---


def test_successful_buy_creates_no_acquisition_lot(conn, bot_name):
    ev = make_event(type="BUY", external_ref="buy-no-lot")
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    importer.import_history()
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 0


# --- Test 22: Successful SELL creates NO acquisition lot ---


def test_successful_sell_creates_no_acquisition_lot(conn, bot_name):
    ev = make_event(type="SELL", external_ref="sell-no-lot")
    importer = make_importer(conn, bot_name, [make_page([ev], total_count=1)])
    importer.import_history()
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 0


# --- Test 23: Pagination uses actual pagesize, not requested count ---


def test_pagination_uses_actual_pagesize(conn, bot_name):
    events = [
        make_event(unit_price=Decimal("0.01"), fees=Decimal("0.00"),
                   total_value=Decimal("0.01"),
                   timestamp="2026-09-14T19:00:00Z",
                   external_ref=f"event-{i:03d}")
        for i in range(25)
    ]
    p1 = make_page(events[0:10], total_count=25, start=0, pagesize=10)
    p2 = make_page(events[10:20], total_count=25, start=10, pagesize=10)
    p3 = make_page(events[20:25], total_count=25, start=20, pagesize=10)
    importer = make_importer(conn, bot_name, [p1, p2, p3])
    result = importer.import_history(start=0, count=100)
    assert result.imported_count == 25
    assert result.skipped_count == 0
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 25


# --- Test 24: Handles empty subsequent page safely ---


def test_handles_empty_pages_safely(conn, bot_name):
    ev = make_event(external_ref="only-event")
    p1 = make_page([ev], total_count=1, start=0, pagesize=10)
    p2 = make_page([], total_count=1, start=10, pagesize=10)
    importer = make_importer(conn, bot_name, [p1, p2])
    result = importer.import_history(start=0, count=100)
    assert result.imported_count == 1
    assert result.skipped_count == 0
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
