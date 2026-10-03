import sys
sys.path.insert(0, "app")
import sqlite3
from decimal import Decimal

import pytest

from transaction_store import (
    insert_buy_with_lot,
    read_acquisition_lot,
    read_transaction,
)
from transactions import create_transaction


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


def make_buy(**overrides):
    values = {
        "type": "BUY",
        "market_hash_name": "Example Card",
        "quantity": 3,
        "unit_price": "0.42",
        "fees": "0.06",
        "timestamp": "2026-09-14T19:00:00Z",
        "bot_name": "Rixqor",
        "external_ref": "steam-buy-001",
    }
    values.update(overrides)
    return create_transaction(**values)


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    create_schema(connection)
    yield connection
    connection.close()


def test_buy_creates_transaction_and_lot(conn):
    transaction = make_buy()

    transaction_id, lot_id = insert_buy_with_lot(conn, transaction)

    tx = read_transaction(conn, transaction_id)
    lot = read_acquisition_lot(conn, lot_id)

    assert tx is not None
    assert lot is not None

    assert tx["type"] == "BUY"
    assert tx["market_hash_name"] == "Example Card"
    assert tx["quantity"] == 3
    assert tx["unit_price"] == "0.42"
    assert tx["fees"] == "0.06"
    assert tx["total_value"] == "1.26"

    assert lot["source_transaction_id"] == transaction_id
    assert lot["market_hash_name"] == "Example Card"
    assert lot["original_quantity"] == 3
    assert lot["remaining_quantity"] == 3
    assert lot["unit_cost"] == "0.42"
    assert lot["cost_status"] == "TRACKED"


def test_buy_is_atomic_when_lot_insert_fails(conn):
    transaction = make_buy()

    # Force the acquisition-lot INSERT to fail through a real SQLite
    # constraint, rather than monkey-patching sqlite3.Connection.
    conn.execute(
        """
        CREATE TRIGGER force_lot_failure
        BEFORE INSERT ON acquisition_lots
        BEGIN
            SELECT RAISE(ABORT, 'forced lot failure');
        END;
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="forced lot failure"):
        insert_buy_with_lot(conn, transaction)

    assert conn.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == 0

    assert conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots"
    ).fetchone()[0] == 0

def test_duplicate_external_ref_is_rejected_atomically(conn):
    first = make_buy()
    second = make_buy(
        market_hash_name="Different Card",
        external_ref="steam-buy-001",
    )

    first_id, first_lot_id = insert_buy_with_lot(conn, first)

    with pytest.raises(sqlite3.IntegrityError):
        insert_buy_with_lot(conn, second)

    assert conn.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == 1

    assert conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots"
    ).fetchone()[0] == 1

    assert conn.execute(
        "SELECT id FROM transactions"
    ).fetchone()[0] == first_id

    assert conn.execute(
        "SELECT id FROM acquisition_lots"
    ).fetchone()[0] == first_lot_id


def test_same_external_ref_is_allowed_for_different_bots(conn):
    first = make_buy(
        bot_name="Rixqor",
        external_ref="same-ref",
    )
    second = make_buy(
        bot_name="cesarpereira27",
        external_ref="same-ref",
    )

    insert_buy_with_lot(conn, first)
    insert_buy_with_lot(conn, second)

    assert conn.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == 2

    assert conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots"
    ).fetchone()[0] == 2


def test_non_buy_cannot_create_acquisition_lot(conn):
    sell = create_transaction(
        type="SELL",
        market_hash_name="Example Card",
        quantity=1,
        unit_price=Decimal("1.00"),
        fees=Decimal("0.10"),
        timestamp="2026-09-14T19:00:00Z",
        bot_name="Rixqor",
    )

    with pytest.raises(ValueError):
        insert_buy_with_lot(conn, sell)

    assert conn.execute(
        "SELECT COUNT(*) FROM transactions"
    ).fetchone()[0] == 0

    assert conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots"
    ).fetchone()[0] == 0
