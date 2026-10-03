import sys
sys.path.insert(0, "app")
import inspect
import sqlite3
from decimal import Decimal

import pytest

from economic_events import ingest_completed_buy
from transaction_store import read_acquisition_lot, read_transaction
from transactions import TransactionValidationError


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


def test_valid_completed_buy_creates_one_transaction_and_one_lot(conn):
    transaction_id, lot_id = ingest_completed_buy(conn, make_event())

    tx = read_transaction(conn, transaction_id)
    lot = read_acquisition_lot(conn, lot_id)

    assert tx is not None
    assert lot is not None

    assert conn.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == 1

    assert conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots"
    ).fetchone()[0] == 1


def test_all_buy_fields_are_preserved(conn):
    event = make_event(external_ref="steam-buy-042")

    transaction_id, lot_id = ingest_completed_buy(conn, event)

    tx = read_transaction(conn, transaction_id)
    lot = read_acquisition_lot(conn, lot_id)

    assert tx["type"] == "BUY"
    assert tx["market_hash_name"] == event["market_hash_name"]
    assert tx["quantity"] == 3
    assert tx["unit_price"] == "0.42"
    assert tx["fees"] == "0.06"
    assert tx["timestamp"] == event["timestamp"]
    assert tx["bot_name"] == event["bot_name"]
    assert tx["external_ref"] == event["external_ref"]

    assert lot["source_transaction_id"] == transaction_id
    assert lot["market_hash_name"] == event["market_hash_name"]
    assert lot["original_quantity"] == 3
    assert lot["remaining_quantity"] == 3
    assert lot["unit_cost"] == "0.42"
    assert lot["cost_status"] == "TRACKED"


def test_total_value_is_unit_price_times_quantity(conn):
    transaction_id, _ = ingest_completed_buy(conn, make_event())

    tx = read_transaction(conn, transaction_id)

    assert tx["total_value"] == str(Decimal("0.42") * 3)


def test_duplicate_external_ref_for_same_bot_is_rejected(conn):
    event = make_event()

    first_id, _ = ingest_completed_buy(conn, event)
    assert read_transaction(conn, first_id)["external_ref"] == event["external_ref"]

    duplicate = make_event(
        market_hash_name="Different Card",
        external_ref=event["external_ref"],
    )

    with pytest.raises(sqlite3.IntegrityError):
        ingest_completed_buy(conn, duplicate)

    assert conn.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == 1

    assert conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots"
    ).fetchone()[0] == 1


def test_invalid_quantity_is_rejected(conn):
    with pytest.raises(TransactionValidationError):
        ingest_completed_buy(conn, make_event(quantity=0))

    assert conn.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == 0


def test_invalid_money_is_rejected(conn):
    with pytest.raises(TransactionValidationError):
        ingest_completed_buy(conn, make_event(unit_price="-0.42"))

    assert conn.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == 0


def test_sell_event_is_rejected(conn):
    with pytest.raises(TransactionValidationError):
        ingest_completed_buy(conn, make_event(type="SELL"))

    assert conn.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == 0


def test_function_does_not_depend_on_inventory_snapshots():
    sig = inspect.signature(ingest_completed_buy)
    assert set(sig.parameters) == {"conn", "event"}

    source = inspect.getsource(ingest_completed_buy)
    assert "snapshot" not in source.lower()
    assert "inventory" not in source.lower()
