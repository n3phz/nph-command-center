import sys
sys.path.insert(0, "app")
import pytest
import sqlite3
from decimal import Decimal

from historical_import import import_historical_buys


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


def make_event(**overrides):
    event = {
        "market_hash_name": "Example Card",
        "quantity": 3,
        "unit_price": "0.42",
        "fees": "0.06",
        "timestamp": "2026-09-14T19:00:00Z",
        "bot_name": "Rixqor",
        "external_ref": "steam-buy-001",
    }
    event.update(overrides)
    return event


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    yield connection
    connection.close()


def test_empty_input(conn):
    result = import_historical_buys(conn, [])
    assert result == {"imported": 0, "rejected": 0, "errors": []}


def test_imports_one_buy(conn):
    events = [make_event()]
    result = import_historical_buys(conn, events)
    assert result == {"imported": 1, "rejected": 0, "errors": []}
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 1


def test_imports_multiple_buys(conn):
    events = [
        make_event(external_ref="a"),
        make_event(market_hash_name="Another Card", external_ref="b"),
    ]
    result = import_historical_buys(conn, events)
    assert result == {"imported": 2, "rejected": 0, "errors": []}
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 2


def test_preserves_all_fields(conn):
    event = make_event(external_ref="custom-ref-123", quantity=5)
    result = import_historical_buys(conn, [event])
    assert result == {"imported": 1, "rejected": 0, "errors": []}
    tx = conn.execute("SELECT * FROM transactions WHERE external_ref = 'custom-ref-123'").fetchone()
    assert tx is not None
    assert tx["market_hash_name"] == "Example Card"
    assert tx["quantity"] == 5
    assert tx["unit_price"] == "0.42"
    assert tx["fees"] == "0.06"
    assert tx["timestamp"] == "2026-09-14T19:00:00Z"
    assert tx["bot_name"] == "Rixqor"
    assert tx["external_ref"] == "custom-ref-123"
    assert tx["total_value"] == str(Decimal("0.42") * 5)
    lot = conn.execute("SELECT * FROM acquisition_lots WHERE source_transaction_id = ?", (tx["id"],)).fetchone()
    assert lot is not None
    assert lot["original_quantity"] == 5
    assert lot["remaining_quantity"] == 5
    assert lot["unit_cost"] == "0.42"
    assert lot["cost_status"] == "TRACKED"


def test_creates_one_acquisition_lot_per_buy(conn):
    events = [
        make_event(external_ref="x"),
        make_event(market_hash_name="Diff Card", external_ref="y"),
    ]
    result = import_historical_buys(conn, events)
    assert result == {"imported": 2, "rejected": 0, "errors": []}
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert lot_count == 2


def test_invalid_quantity_rejected(conn):
    events = [
        make_event(quantity=0),
        make_event(external_ref="valid-2"),
    ]
    with pytest.raises(ValueError) as exc:
        import_historical_buys(conn, events)
    error_list = exc.value.args[0]
    assert isinstance(error_list, list)
    assert len(error_list) == 1
    assert error_list[0]["index"] == 1
    # No data persisted due to atomic rollback.
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 0


def test_invalid_money_rejected(conn):
    events = [
        make_event(unit_price="-5.00"),
        make_event(external_ref="valid-2"),
    ]
    with pytest.raises(ValueError):
        import_historical_buys(conn, events)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_sell_type_rejected(conn):
    events = [
        {**make_event(), "type": "SELL"},
        make_event(external_ref="valid-2"),
    ]
    with pytest.raises(ValueError):
        import_historical_buys(conn, events)
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0


def test_duplicate_external_ref_for_same_bot_is_rejected_and_rolls_back(conn):
    events = [
        make_event(external_ref="dup-ref"),
        make_event(market_hash_name="Second Card", external_ref="dup-ref"),
    ]
    with pytest.raises(ValueError):
        import_historical_buys(conn, events)
    # No data persists because of atomic rollback.
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 0


def test_same_external_ref_allowed_for_different_bots(conn):
    events = [
        make_event(bot_name="BotA", external_ref="shared-ref"),
        make_event(bot_name="BotB", external_ref="shared-ref"),
    ]
    result = import_historical_buys(conn, events)
    assert result == {"imported": 2, "rejected": 0, "errors": []}
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 2


def test_no_inventory_rows_created(conn):
    events = [make_event()]
    result = import_historical_buys(conn, events)
    assert result == {"imported": 1, "rejected": 0, "errors": []}
    # Confirm no tables beyond the expected V0.5 tables exist.
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    table_names = {row[0] for row in tables}
    # sqlite_sequence is auto-created by AUTOINCREMENT; that's expected.
    assert "transactions" in table_names
    assert "acquisition_lots" in table_names
    # No inventory snapshot or item tables were created.
    for forbidden in ("inventory_snapshots", "inventory_items"):
        assert forbidden not in table_names, f"{forbidden} table should not exist"
