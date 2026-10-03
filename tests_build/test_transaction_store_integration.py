import sys
sys.path.insert(0, "app")
import sqlite3

import main as main
from transaction_store import (
    insert_buy_with_lot,
    read_acquisition_lot,
    read_transaction,
)
from transactions import create_transaction


def test_buy_persists_through_real_init_db(tmp_path, monkeypatch):
    db_path = tmp_path / "integration.db"

    monkeypatch.setattr(main, "DB_PATH", str(db_path))

    main.init_db()

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row

    transaction = create_transaction(
        type="BUY",
        market_hash_name="Integration Card",
        quantity=4,
        unit_price="0.37",
        fees="0.05",
        timestamp="2026-09-14T19:00:00Z",
        bot_name="Rixqor",
        external_ref="integration-buy-001",
    )

    transaction_id, lot_id = insert_buy_with_lot(
        conn,
        transaction,
    )

    persisted_tx = read_transaction(
        conn,
        transaction_id,
    )

    persisted_lot = read_acquisition_lot(
        conn,
        lot_id,
    )

    assert persisted_tx is not None
    assert persisted_lot is not None

    assert persisted_tx["type"] == "BUY"
    assert persisted_tx["market_hash_name"] == "Integration Card"
    assert persisted_tx["quantity"] == 4
    assert persisted_tx["unit_price"] == "0.37"
    assert persisted_tx["fees"] == "0.05"
    assert persisted_tx["total_value"] == "1.48"
    assert persisted_tx["bot_name"] == "Rixqor"
    assert persisted_tx["external_ref"] == "integration-buy-001"

    assert persisted_lot["source_transaction_id"] == transaction_id
    assert persisted_lot["market_hash_name"] == "Integration Card"
    assert persisted_lot["bot_name"] == "Rixqor"
    assert persisted_lot["original_quantity"] == 4
    assert persisted_lot["remaining_quantity"] == 4
    assert persisted_lot["unit_cost"] == "0.37"
    assert persisted_lot["cost_status"] == "TRACKED"

    conn.close()
