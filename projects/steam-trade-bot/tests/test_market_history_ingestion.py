import sys
sys.path.insert(0, "app")
"""Tests for V0.5.6 market history ingestion service.

All tests are offline — client/parser/importer are mocked/injected.
"""

from decimal import Decimal
from unittest.mock import Mock

import pytest
import requests
import sqlite3

from market_history_adapter import (
    MarketHistoryEvent,
    SteamMarketHistoryClient,
    SteamMarketHistoryParser,
)
from market_history_ingestion import (
    IngestionResult,
    MarketHistoryIngestionError,
    MarketHistoryIngestionService,
)
from market_history_importer import (
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
            total_value TEXT NOT NULL DEFAULT '0',
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


def make_service(conn, bot_name, pages):
    """Create a service with client/parser/importer stubbed to return pre-parsed events."""
    importer = MarketHistoryImporter.__new__(MarketHistoryImporter)
    importer.session = Mock(spec=requests.Session)
    importer.conn = conn
    importer.bot_name = bot_name
    importer.base_url = "https://steamcommunity.com"

    page_iter = iter(pages)
    client = Mock()
    client.fetch_page = Mock(side_effect=lambda **kw: next(page_iter))
    parser = Mock()
    parser.parse_response = Mock(
        side_effect=lambda page: list(page.get("_events", []))
    )

    service = MarketHistoryIngestionService(client, parser, importer)
    return service


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


# --- Tests -----------------------------------------------------------------


def test_buy_creates_one_transaction_no_lots(conn, bot_name):
    ev = make_event(external_ref="buy-only-tx")
    service = make_service(conn, bot_name, [make_page([ev], total_count=1)])
    result = service.ingest_history()

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


def test_sell_creates_one_transaction_no_lots(conn, bot_name):
    ev = make_event(
        type="SELL", quantity=2, unit_price=Decimal("1.50"),
        fees=Decimal("0.23"), total_value=Decimal("3.00"),
        external_ref="sell-only-tx",
    )
    service = make_service(conn, bot_name, [make_page([ev], total_count=1)])
    result = service.ingest_history()
    assert result.imported_count == 1
    assert result.skipped_count == 0
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 0

    tx = conn.execute("SELECT * FROM transactions WHERE external_ref='sell-only-tx'").fetchone()
    assert tx["type"] == "SELL"


def test_multiple_pages_imported(conn, bot_name):
    ev1 = make_event(unit_price=Decimal("0.10"), fees=Decimal("0.02"),
                     total_value=Decimal("0.12"),
                     timestamp="2026-09-14T19:00:00Z", external_ref="page1-buy")
    ev2 = make_event(unit_price=Decimal("0.20"), fees=Decimal("0.03"),
                     total_value=Decimal("0.40"),
                     timestamp="2026-09-15T19:00:00Z", external_ref="page2-buy")
    p1 = make_page([ev1], total_count=2, start=0, pagesize=1)
    p2 = make_page([ev2], total_count=2, start=1, pagesize=1)
    service = make_service(conn, bot_name, [p1, p2])
    result = service.ingest_history(start=0, count=100)
    assert result.imported_count == 2
    assert result.skipped_count == 0
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_pagination_stops_at_total_count(conn, bot_name):
    events = [
        make_event(unit_price=Decimal("0.01"), fees=Decimal("0.00"),
                   total_value=Decimal("0.01"),
                   timestamp="2026-09-14T19:00:00Z", external_ref=f"event-{i}")
        for i in range(3)
    ]
    service = make_service(conn, bot_name, [make_page(events, total_count=3, start=0, pagesize=3)])
    result = service.ingest_history(start=0, count=100)
    assert result.imported_count == 3
    assert result.skipped_count == 0


def test_server_pagesize_not_equal_requested_count(conn, bot_name):
    """When server returns pagesize != requested count, pagination uses server pagesize."""
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
    service = make_service(conn, bot_name, [p1, p2, p3])
    result = service.ingest_history(start=0, count=100)
    assert result.imported_count == 25
    assert result.skipped_count == 0
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 25


def test_duplicate_external_ref_not_imported_twice(conn, bot_name):
    ev1 = make_event(market_hash_name="Dup Card", external_ref="dup-ref")
    ev2 = make_event(market_hash_name="Dup Card v2", external_ref="dup-ref")
    service = make_service(conn, bot_name, [make_page([ev1, ev2], total_count=2)])
    result = service.ingest_history()
    assert result.imported_count == 1
    assert result.skipped_count == 1
    assert "duplicate" in result.skipped_reasons[0].lower()
    assert conn.execute("SELECT COUNT(*) FROM transactions WHERE external_ref='dup-ref'").fetchone()[0] == 1


def test_duplicate_skipped_on_second_import(conn, bot_name):
    ev = make_event(external_ref="dup-ref-2")
    service1 = make_service(conn, bot_name, [make_page([ev], total_count=1)])
    service1.ingest_history()

    service2 = make_service(conn, bot_name, [make_page([ev], total_count=1)])
    result = service2.ingest_history()
    assert result.imported_count == 0
    assert result.skipped_count == 1
    assert "duplicate" in result.skipped_reasons[0].lower()


def test_timestamp_none_is_skipped(conn, bot_name):
    ev = make_event(timestamp=None, external_ref="no-timestamp-ref")
    service = make_service(conn, bot_name, [make_page([ev], total_count=1)])
    result = service.ingest_history()
    assert result.imported_count == 0
    assert result.skipped_count == 1
    assert "timestamp unavailable" in result.skipped_reasons[0].lower()
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_fees_none_is_skipped(conn, bot_name):
    ev = make_event(fees=None, total_value=Decimal("0.10"), external_ref="no-fees")
    service = make_service(conn, bot_name, [make_page([ev], total_count=1)])
    result = service.ingest_history()
    assert result.imported_count == 0
    assert result.skipped_count == 1
    assert "fees unavailable" in result.skipped_reasons[0]
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_empty_result(conn, bot_name):
    service = make_service(conn, bot_name, [make_page([], total_count=0)])
    result = service.ingest_history()
    assert isinstance(result, IngestionResult)
    assert result.imported_count == 0
    assert result.skipped_count == 0
    assert result.skipped_reasons == []


def test_dependency_injection(conn, bot_name):
    """Verify that injected client/parser/importer are actually used."""
    ev = make_event(external_ref="inject-test")
    page = make_page([ev], total_count=1)

    client = Mock(spec=SteamMarketHistoryClient)
    client.fetch_page = Mock(return_value=page)

    parser = Mock(spec=SteamMarketHistoryParser)
    parser.parse_response = Mock(return_value=[ev])

    importer = MarketHistoryImporter.__new__(MarketHistoryImporter)
    importer.session = Mock(spec=requests.Session)
    importer.conn = conn
    importer.bot_name = bot_name
    importer.base_url = "https://steamcommunity.com"

    service = MarketHistoryIngestionService(client, parser, importer)
    result = service.ingest_history()

    assert result.imported_count == 1
    client.fetch_page.assert_called_once()
    parser.parse_response.assert_called_once()


def test_persistence_failure_rolls_back(conn, bot_name):
    events = [
        make_event(external_ref="good-1"),
        make_event(external_ref="good-2"),
    ]
    service = make_service(conn, bot_name, [make_page(events, total_count=2)])

    call_count = [0]
    original_persist = MarketHistoryIngestionService._persist_event

    def failing_persist(c, bn, nevent):
        call_count[0] += 1
        if call_count[0] == 2:
            raise sqlite3.OperationalError("disk I/O error")
        return original_persist(c, bn, nevent)

    MarketHistoryIngestionService._persist_event = failing_persist

    with pytest.raises(MarketHistoryIngestionError):
        service.ingest_history()
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0

    # Restore
    MarketHistoryIngestionService._persist_event = original_persist


def test_no_acquisition_lots(conn, bot_name):
    ev = make_event(external_ref="no-lot")
    service = make_service(conn, bot_name, [make_page([ev], total_count=1)])
    service.ingest_history()
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 0


def test_no_authentication_or_cookies():
    import inspect
    source = inspect.getsource(MarketHistoryIngestionService)
    low = source.lower()
    assert "login" not in low
    assert "cookie" not in low
    assert "password" not in low
    assert "steamcommunity.com/login" not in low


def test_source_events_not_mutated(conn, bot_name):
    ev = make_event(external_ref="immutable-test")
    original_unit_price = ev.unit_price
    original_ref = ev.external_ref
    service = make_service(conn, bot_name, [make_page([ev], total_count=1)])
    service.ingest_history()
    assert ev.unit_price == original_unit_price
    assert ev.external_ref == original_ref


def test_buy_no_acquisition_lot(conn, bot_name):
    ev = make_event(type="BUY", external_ref="buy-no-lot")
    service = make_service(conn, bot_name, [make_page([ev], total_count=1)])
    service.ingest_history()
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 0


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
    service = make_service(conn, bot_name, [make_page([ev], total_count=1)])
    service.ingest_history()
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 1
    rem = conn.execute("SELECT remaining_quantity FROM acquisition_lots WHERE id=1").fetchone()[0]
    assert rem == 2


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

    client = Mock()
    client.fetch_page = Mock(return_value=page)
    parser = Mock()
    parser.parse_response = Mock(return_value=[ev])

    service = MarketHistoryIngestionService(client, parser, importer)
    service.ingest_history()

    session.get.assert_called_once()
    args, kwargs = session.get.call_args
    assert "/market/myhistory/render/" in args[0]
    params = kwargs.get("params", {})
    assert params.get("start") == 0
    assert params.get("count") == 100
    assert params.get("norender") == 1


def test_no_profit_calculations():
    import inspect
    source = inspect.getsource(MarketHistoryIngestionService)
    low = source.lower()
    for term in ("profit", "roi", "margin", "pnl", "return_on_investment"):
        assert term not in low, f"found forbidden term: {term}"


def test_result_is_immutable():
    result = IngestionResult(
        fetched_event_count=1,
        imported_count=1,
        skipped_count=0,
        skipped_reasons=[],
    )
    with pytest.raises(Exception):
        result.imported_count = 99


def test_fetched_event_count(conn, bot_name):
    ev1 = make_event(external_ref="fetched-1")
    ev2 = make_event(external_ref="fetched-2")
    p1 = make_page([ev1], total_count=2, start=0, pagesize=1)
    p2 = make_page([ev2], total_count=2, start=1, pagesize=1)
    service = make_service(conn, bot_name, [p1, p2])
    result = service.ingest_history(start=0, count=100)
    assert result.fetched_event_count == 2


def test_empty_first_page_safe_result(conn, bot_name):
    client = Mock()
    client.fetch_page = Mock(return_value={})  # non-dict response
    parser = Mock()
    importer = MarketHistoryImporter.__new__(MarketHistoryImporter)
    importer.session = Mock(spec=requests.Session)
    importer.conn = conn
    importer.bot_name = bot_name
    importer.base_url = "https://steamcommunity.com"

    service = MarketHistoryIngestionService(client, parser, importer)
    result = service.ingest_history()
    assert isinstance(result, IngestionResult)
    assert result.imported_count == 0
    assert result.skipped_count == 0


def test_invalid_first_page_raises(conn, bot_name):
    client = Mock()
    client.fetch_page = Mock(return_value={"total_count": -1})
    parser = Mock()
    importer = MarketHistoryImporter.__new__(MarketHistoryImporter)
    importer.session = Mock(spec=requests.Session)
    importer.conn = conn
    importer.bot_name = bot_name
    importer.base_url = "https://steamcommunity.com"

    service = MarketHistoryIngestionService(client, parser, importer)
    with pytest.raises(MarketHistoryIngestionError):
        service.ingest_history()


def test_normalize_failure_raises(conn, bot_name):
    bad_event = make_event(market_hash_name="", fees=None, external_ref="bad-event")
    client = Mock()
    client.fetch_page = Mock(return_value=make_page([bad_event], total_count=1))
    parser = Mock()
    parser.parse_response = Mock(return_value=[bad_event])
    importer = MarketHistoryImporter.__new__(MarketHistoryImporter)
    importer.session = Mock(spec=requests.Session)
    importer.conn = conn
    importer.bot_name = bot_name
    importer.base_url = "https://steamcommunity.com"

    service = MarketHistoryIngestionService(client, parser, importer)
    with pytest.raises(MarketHistoryIngestionError):
        service.ingest_history()
