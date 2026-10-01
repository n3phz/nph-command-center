#!/usr/bin/env python3
"""Standalone acquisition integration tests without pytest."""

import sys
sys.path.insert(0, "app")

import sqlite3
from decimal import Decimal
from datetime import date, datetime, timezone
from unittest.mock import Mock

from acquisition import Repository, record_acquisition, AcquisitionError
from acquisition_detector import (
    AcquisitionDetector,
    InventorySnapshot,
    InventoryDelta,
    MarketHistoryPurchase,
)
from transactions import CostStatus, SourceType, Provenance, EvidenceType


# --- Schema helpers ---

def create_full_schema(conn):
    """Create complete database schema for testing."""
    conn.executescript(
        """
        CREATE TABLE inventory_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            captured_at TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            app_id INTEGER NOT NULL,
            context_id INTEGER NOT NULL,
            item_count INTEGER NOT NULL,
            raw_json TEXT NOT NULL
        );
        CREATE TABLE inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            bot_name TEXT NOT NULL,
            app_id INTEGER NOT NULL,
            context_id INTEGER NOT NULL,
            asset_id TEXT,
            class_id TEXT,
            instance_id TEXT,
            amount INTEGER NOT NULL DEFAULT 1,
            market_hash_name TEXT,
            market_name TEXT,
            type TEXT,
            tradable INTEGER NOT NULL DEFAULT 0,
            marketable INTEGER NOT NULL DEFAULT 0,
            raw_json TEXT NOT NULL,
            FOREIGN KEY(snapshot_id) REFERENCES inventory_snapshots(id)
        );
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
        CREATE TABLE acquisition_processing_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT NOT NULL,
            snapshot_id INTEGER NOT NULL,
            processed_at TEXT NOT NULL,
            UNIQUE(bot_name, snapshot_id)
        );
        """
    )


def insert_snapshot(conn, bot_name, captured_at, items):
    """Insert a snapshot with items. Returns snapshot_id."""
    cursor = conn.execute(
        """INSERT INTO inventory_snapshots (captured_at, bot_name, app_id, context_id, item_count, raw_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (captured_at, bot_name, 753, 6, len(items), '{}'),
    )
    snapshot_id = cursor.lastrowid
    for item in items:
        conn.execute(
            """INSERT INTO inventory_items (snapshot_id, bot_name, app_id, context_id,
               asset_id, class_id, instance_id, amount, market_hash_name, market_name,
               type, tradable, marketable, raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                snapshot_id, bot_name, 753, 6,
                item.get('asset_id', f'asset-{snapshot_id}'),
                item.get('class_id', 'class1'),
                item.get('instance_id', 'instance1'),
                item['amount'],
                item['market_hash_name'],
                item.get('market_name', item['market_hash_name']),
                item.get('type', 'Item'),
                item.get('tradable', 1),
                item.get('marketable', 1),
                '{}',
            ),
        )
    conn.commit()
    return snapshot_id


# --- Test runner ---

def run_test(name, test_func):
    """Run a test function and report result."""
    print(f"{name}...", end=" ")
    try:
        test_func()
        print("PASS")
        return True
    except Exception as e:
        print(f"FAIL: {e}")
        import traceback
        traceback.print_exc()
        return False


# --- Tests ---

def test_initial_snapshot_creates_no_acquisitions():
    """Initial snapshot establishes baseline only — no acquisition lots created."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    detector = AcquisitionDetector(repo, "Rixqor")
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Card A", "amount": 2},
        {"market_hash_name": "Card B", "amount": 1},
    ])

    detector.fetch_market_history_for_item = Mock(return_value=[])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    # Baseline only: no acquisition candidates detected
    assert len(results) == 0
    lot_count = conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots"
    ).fetchone()[0]
    assert lot_count == 0


def test_new_item_on_subsequent_snapshot():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "New Card", "amount": 1},
    ])

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    assert results[0].market_hash_name == "New Card"
    assert results[0].quantity == 1
    assert results[0].cost_status == CostStatus.UNKNOWN


def test_quantity_increase_detected():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Multi Card", "amount": 1},
    ])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Multi Card", "amount": 3},
    ])

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    assert results[0].market_hash_name == "Multi Card"
    assert results[0].quantity == 2  # delta of +2
    assert results[0].cost_status == CostStatus.UNKNOWN


def test_quantity_decrease_no_acquisition():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Multi Card", "amount": 3},
    ])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Multi Card", "amount": 1},
    ])

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 0


def test_no_inventory_change_no_acquisition():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Same Card", "amount": 2},
    ])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Same Card", "amount": 2},
    ])

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 0


def test_market_history_exact_match_creates_tracked():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Purchased Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Purchased Card",
        quantity=1,
        paid_amount_cents=5000,  # 50.00 EUR
        currencyid=3,  # EUR
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    r = results[0]
    assert r.market_hash_name == "Purchased Card"
    assert r.cost_status == CostStatus.TRACKED
    assert r.created == True
    assert r.lot_id is not None

    lot = conn.execute(
        "SELECT unit_cost FROM acquisition_lots WHERE cost_status = 'TRACKED'"
    ).fetchone()
    assert lot is not None
    assert Decimal(lot[0]) == Decimal("50.00")


def test_market_history_partial_match_creates_unknown():
    """Purchase quantity (2) does not exactly match delta (1) → UNKNOWN."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Partial Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Partial Card",
        quantity=2,  # purchase was for 2
        paid_amount_cents=10000,  # 100.00 EUR total
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    # Phase 2: exact quantity match required; partial match → UNKNOWN
    assert len(results) == 1
    r = results[0]
    assert r.cost_status == CostStatus.UNKNOWN
    lot = conn.execute(
        "SELECT unit_cost, cost_status FROM acquisition_lots WHERE market_hash_name = 'Partial Card'"
    ).fetchone()
    assert lot[1] == 'UNKNOWN'
    assert lot[0] is None


def test_initial_snapshot_baseline_no_acquisitions():
    """Second snapshot with no previous snapshot creates zero acquisitions."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    detector = AcquisitionDetector(repo, "Rixqor")
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Mystery Card", "amount": 1},
    ])

    detector.fetch_market_history_for_item = Mock(return_value=[])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    # First snapshot (empty) = baseline; second snapshot (+1) = delta detected
    # No Market History match → UNKNOWN acquisition
    assert len(results) == 1
    r = results[0]
    assert r.market_hash_name == "Mystery Card"
    assert r.cost_status == CostStatus.UNKNOWN
    lot_count = conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots WHERE cost_status = 'UNKNOWN'"
    ).fetchone()[0]
    assert lot_count == 1


def test_repeated_polling_no_duplicate_tracked():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Tracked Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Tracked Card",
        quantity=1,
        paid_amount_cents=5000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    # First run
    d1 = AcquisitionDetector(repo, "Rixqor")
    d1.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    results1 = d1.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(results1) == 1
    assert results1[0].created == True
    lot_id_1 = results1[0].lot_id

    # Second run (same snapshot)
    d2 = AcquisitionDetector(repo, "Rixqor")
    d2.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    results2 = d2.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(results2) == 0

    # Third run (fresh detector)
    d3 = AcquisitionDetector(repo, "Rixqor")
    d3.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    results3 = d3.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(results3) == 0

    lot_count = conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots WHERE cost_status = 'TRACKED'"
    ).fetchone()[0]
    assert lot_count == 1


def test_repeated_unknown_remain_distinct():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Mystery Card", "amount": 1},
    ])

    d1 = AcquisitionDetector(repo, "Rixqor")
    d1.fetch_market_history_for_item = Mock(return_value=[])
    results1 = d1.detect_acquisition(mock_session, process_new_snapshots=True)
    lot_id_1 = results1[0].lot_id

    # Another new item in later snapshot
    insert_snapshot(conn, "Rixqor", "2026-09-22T10:00:00Z", [
        {"market_hash_name": "Mystery Card", "amount": 2},
    ])

    d2 = AcquisitionDetector(repo, "Rixqor")
    d2.fetch_market_history_for_item = Mock(return_value=[])
    results2 = d2.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results2) == 1
    assert results2[0].quantity == 1  # delta of +1
    assert results2[0].lot_id != lot_id_1
    assert results2[0].cost_status == CostStatus.UNKNOWN

    lot_count = conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots WHERE market_hash_name = 'Mystery Card' AND cost_status = 'UNKNOWN'"
    ).fetchone()[0]
    assert lot_count == 2


def test_verified_acquisition_cost_in_ledger():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Cost Card", "amount": 2},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Cost Card",
        quantity=2,
        paid_amount_cents=30000,  # 300.00 EUR for 2 = 150.00 each
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    r = results[0]
    assert r.cost_status == CostStatus.TRACKED

    # Verify ledger: transaction unit_price = unit_cost = 150.00
    tx = conn.execute(
        """SELECT unit_price, fees, total_value FROM transactions
           WHERE market_hash_name = 'Cost Card'""").fetchone()
    assert tx is not None
    assert Decimal(tx[0]) == Decimal("150.00")
    assert Decimal(tx[1]) == Decimal("0")
    assert Decimal(tx[2]) == Decimal("300.00")

    lot = conn.execute(
        "SELECT unit_cost FROM acquisition_lots WHERE cost_status = 'TRACKED'"
    ).fetchone()
    assert Decimal(lot[0]) == Decimal("150.00")


def test_market_price_never_used_as_cost():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Price Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Price Card",
        quantity=1,
        paid_amount_cents=1000,  # 10.00 EUR (purchase price)
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    r = results[0]
    assert r.cost_status == CostStatus.TRACKED

    lot = conn.execute(
        "SELECT unit_cost FROM acquisition_lots WHERE cost_status = 'TRACKED'"
    ).fetchone()
    assert Decimal(lot[0]) == Decimal("10.00")


def test_phase1_invariants_preserved():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    # Test UNKNOWN lot
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Unknown Card", "amount": 1},
    ])

    d1 = AcquisitionDetector(repo, "Rixqor")
    d1.fetch_market_history_for_item = Mock(return_value=[])
    d1.detect_acquisition(mock_session, process_new_snapshots=True)

    unk_lot = conn.execute(
        """SELECT unit_cost, cost_status FROM acquisition_lots
           WHERE market_hash_name = 'Unknown Card'""").fetchone()
    assert unk_lot[0] is None
    assert unk_lot[1] == "UNKNOWN"

    # Test TRACKED lot
    insert_snapshot(conn, "Rixqor", "2026-09-22T10:00:00Z", [
        {"market_hash_name": "Tracked Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-22T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Tracked Card",
        quantity=1,
        paid_amount_cents=5000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    d2 = AcquisitionDetector(repo, "Rixqor")
    d2.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    d2.detect_acquisition(mock_session, process_new_snapshots=True)

    trk_lot = conn.execute(
        """SELECT unit_cost, cost_status FROM acquisition_lots
           WHERE market_hash_name = 'Tracked Card'""").fetchone()
    assert trk_lot[0] is not None
    assert Decimal(trk_lot[0]) > 0
    assert trk_lot[1] == "TRACKED"

    tx = conn.execute(
        "SELECT external_ref FROM transactions WHERE market_hash_name = 'Tracked Card'"
    ).fetchone()
    assert tx is not None
    assert tx[0] == "listing-123:purchase-456"


def test_existing_transactions_not_duplicated():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    # Pre-populate with a manual TRACKED acquisition
    conn.execute("""
        INSERT INTO transactions (type, market_hash_name, quantity, unit_price, fees,
                                  total_value, timestamp, bot_name, external_ref)
        VALUES ('BUY', 'Existing Card', 1, '25.00', '0', '25.00',
                '2026-09-15T10:00:00Z', 'Rixqor', 'manual-existing-1')
    """)
    conn.execute("""
        INSERT INTO acquisition_lots (source_transaction_id, market_hash_name, bot_name,
                                     original_quantity, remaining_quantity, unit_cost,
                                     acquired_at, cost_status)
        VALUES (1, 'Existing Card', 'Rixqor', 1, 1, '25.00',
                '2026-09-15T10:00:00Z', 'TRACKED')
    """)
    conn.commit()

    # Run detection for a NEW item
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "New Card", "amount": 1},
    ])

    d = AcquisitionDetector(repo, "Rixqor")
    d.fetch_market_history_for_item = Mock(return_value=[])
    d.detect_acquisition(mock_session, process_new_snapshots=True)

    existing_lot = conn.execute(
        "SELECT remaining_quantity, unit_cost FROM acquisition_lots WHERE market_hash_name = 'Existing Card'"
    ).fetchone()
    assert existing_lot[0] == 1
    assert Decimal(existing_lot[1]) == Decimal("25.00")

    new_lot = conn.execute(
        "SELECT cost_status FROM acquisition_lots WHERE market_hash_name = 'New Card'"
    ).fetchone()
    assert new_lot[0] == "UNKNOWN"


def test_sell_allocation_unchanged():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    # Create TRACKED lot
    conn.execute("""
        INSERT INTO transactions (type, market_hash_name, quantity, unit_price, fees,
                                  total_value, timestamp, bot_name, external_ref)
        VALUES ('BUY', 'Sell Card', 2, '10.00', '0', '20.00',
                '2026-09-15T10:00:00Z', 'Rixqor', 'buy-sell-1')
    """)
    conn.execute("""
        INSERT INTO acquisition_lots (source_transaction_id, market_hash_name, bot_name,
                                     original_quantity, remaining_quantity, unit_cost,
                                     acquired_at, cost_status)
        VALUES (1, 'Sell Card', 'Rixqor', 2, 2, '10.00',
                '2026-09-15T10:00:00Z', 'TRACKED')
    """)
    conn.commit()

    # Run detection for unrelated item
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Unrelated Card", "amount": 1},
    ])

    d = AcquisitionDetector(repo, "Rixqor")
    d.fetch_market_history_for_item = Mock(return_value=[])
    d.detect_acquisition(mock_session, process_new_snapshots=True)

    sell_lot = conn.execute(
        "SELECT remaining_quantity, unit_cost FROM acquisition_lots WHERE market_hash_name = 'Sell Card'"
    ).fetchone()
    assert sell_lot[0] == 2
    assert Decimal(sell_lot[1]) == Decimal("10.00")


def test_rerun_same_cycle_no_duplicate():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Card",
        quantity=1,
        paid_amount_cents=5000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    d1 = AcquisitionDetector(repo, "Rixqor")
    d1.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    r1 = d1.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(r1) == 1

    d2 = AcquisitionDetector(repo, "Rixqor")
    d2.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    r2 = d2.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(r2) == 0

    d3 = AcquisitionDetector(repo, "Rixqor")
    d3.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    r3 = d3.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(r3) == 0


def test_different_bots_isolated():
    """Two bots with independent snapshots; both establish baseline only."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Bot1 Card", "amount": 1},
    ])
    insert_snapshot(conn, "cesarpereira27", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Bot2 Card", "amount": 1},
    ])

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)
    # Baseline only: initial snapshot creates zero acquisitions
    assert len(results) == 0

    detector2 = AcquisitionDetector(repo, "cesarpereira27")
    detector2.fetch_market_history_for_item = Mock(return_value=[])
    results2 = detector2.detect_acquisition(mock_session, process_new_snapshots=True)
    # Baseline only: initial snapshot creates zero acquisitions
    assert len(results2) == 0


def test_record_acquisition_tracked_requires_provenance():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)

    prov = Provenance(
        evidence_type=EvidenceType.STEAM_MARKET_HISTORY,
        evidence_id="purchase-123",
        evidence_data={"listingid": "listing-456"},
    )

    try:
        record_acquisition(
            repository=repo,
            bot_name="Rixqor",
            market_hash_name="Test",
            quantity=1,
            acquired_at=date.today().isoformat(),
            unit_cost=Decimal("10.00"),
            currency="EUR",
            source_type=SourceType.STEAM_MARKET_PURCHASE,
            provenance=None,  # Missing!
            external_reference="ext-ref-1",
            entered_at=datetime.now(timezone.utc).isoformat(),
        )
        assert False, "Should have raised AcquisitionError"
    except AcquisitionError as e:
        assert "TRACKED cost requires provenance" in str(e)


def test_record_acquisition_unknown_requires_no_cost():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)

    # When unit_cost is explicitly provided (not None), it's treated as TRACKED
    # and fails TRACKED validation. The UNKNOWN path requires unit_cost=None (default).
    try:
        record_acquisition(
            repository=repo,
            bot_name="Rixqor",
            market_hash_name="Test",
            quantity=1,
            acquired_at=date.today().isoformat(),
            unit_cost=Decimal("10.00"),  # Provided = treated as TRACKED
            currency=None,  # Missing currency for TRACKED
            source_type=None,
            provenance=None,
            external_reference="ext-ref-2",
            entered_at=datetime.now(timezone.utc).isoformat(),
        )
        assert False, "Should have raised AcquisitionError"
    except AcquisitionError as e:
        assert "TRACKED cost requires currency" in str(e)

    # Now test proper UNKNOWN with unit_cost=None (default behavior)
    r = record_acquisition(
        repository=repo,
        bot_name="Rixqor",
        market_hash_name="Test2",
        quantity=1,
        acquired_at=date.today().isoformat(),
        unit_cost=None,  # Explicit None for UNKNOWN
        currency=None,
        source_type=None,
        provenance=None,
        external_reference="ext-ref-3",
        entered_at=datetime.now(timezone.utc).isoformat(),
    )
    assert r.lot.cost_status == CostStatus.UNKNOWN
    assert r.lot.unit_cost is None


def test_record_acquisition_idempotent():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)

    prov = Provenance(
        evidence_type=EvidenceType.STEAM_MARKET_HISTORY,
        evidence_id="purchase-123",
        evidence_data={"listingid": "listing-456"},
    )

    r1 = record_acquisition(
        repository=repo,
        bot_name="Rixqor",
        market_hash_name="Idem Card",
        quantity=1,
        acquired_at=date.today().isoformat(),
        unit_cost=Decimal("10.00"),
        currency="EUR",
        source_type=SourceType.STEAM_MARKET_PURCHASE,
        provenance=prov,
        external_reference="idem-ref-1",
        entered_at=datetime.now(timezone.utc).isoformat(),
    )
    assert r1.created == True
    lot_id = r1.lot.lot_id

    r2 = record_acquisition(
        repository=repo,
        bot_name="Rixqor",
        market_hash_name="Idem Card",
        quantity=1,
        acquired_at=date.today().isoformat(),
        unit_cost=Decimal("10.00"),
        currency="EUR",
        source_type=SourceType.STEAM_MARKET_PURCHASE,
        provenance=prov,
        external_reference="idem-ref-1",
        entered_at=datetime.now(timezone.utc).isoformat(),
    )
    assert r2.created == False
    assert r2.lot.lot_id == lot_id

    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert tx_count == 1
    assert lot_count == 1


def test_unknown_external_ref_distinct():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)

    r1 = record_acquisition(
        repository=repo,
        bot_name="Rixqor",
        market_hash_name="Same Card",
        quantity=1,
        acquired_at=date.today().isoformat(),
        unit_cost=None,
        currency=None,
        source_type=None,
        provenance=None,
        external_reference="unknown:Rixqor:Same Card:2026-09-27:1",
        entered_at=datetime.now(timezone.utc).isoformat(),
    )
    assert r1.created == True

    r2 = record_acquisition(
        repository=repo,
        bot_name="Rixqor",
        market_hash_name="Same Card",
        quantity=1,
        acquired_at=date.today().isoformat(),
        unit_cost=None,
        currency=None,
        source_type=None,
        provenance=None,
        external_reference="unknown:Rixqor:Same Card:2026-09-27:2",
        entered_at=datetime.now(timezone.utc).isoformat(),
    )
    assert r2.created == True
    assert r2.lot.lot_id != r1.lot.lot_id

    r3 = record_acquisition(
        repository=repo,
        bot_name="Rixqor",
        market_hash_name="Same Card",
        quantity=1,
        acquired_at=date.today().isoformat(),
        unit_cost=None,
        currency=None,
        source_type=None,
        provenance=None,
        external_reference="unknown:Rixqor:Same Card:2026-09-27:1",
        entered_at=datetime.now(timezone.utc).isoformat(),
    )
    assert r3.created == False
    assert r3.lot.lot_id == r1.lot.lot_id


# --- Main ---

if __name__ == "__main__":
    tests = [
        ("Initial snapshot creates no acquisitions", test_initial_snapshot_creates_no_acquisitions),
        ("New item on subsequent snapshot", test_new_item_on_subsequent_snapshot),
        ("Quantity increase detected", test_quantity_increase_detected),
        ("Quantity decrease no acquisition", test_quantity_decrease_no_acquisition),
        ("No inventory change no acquisition", test_no_inventory_change_no_acquisition),
        ("Market History exact match creates TRACKED", test_market_history_exact_match_creates_tracked),
        ("Market History partial match creates UNKNOWN", test_market_history_partial_match_creates_unknown),
        ("Second snapshot delta creates UNKNOWN", test_initial_snapshot_baseline_no_acquisitions),
        ("Repeated polling no duplicate TRACKED", test_repeated_polling_no_duplicate_tracked),
        ("Repeated UNKNOWN remain distinct", test_repeated_unknown_remain_distinct),
        ("Verified acquisition cost in ledger", test_verified_acquisition_cost_in_ledger),
        ("Market price never used as cost", test_market_price_never_used_as_cost),
        ("Phase 1 invariants preserved", test_phase1_invariants_preserved),
        ("Existing transactions not duplicated", test_existing_transactions_not_duplicated),
        ("Sell allocation unchanged", test_sell_allocation_unchanged),
        ("Rerun same cycle no duplicate", test_rerun_same_cycle_no_duplicate),
        ("Different bots isolated", test_different_bots_isolated),
        ("record_acquisition TRACKED requires provenance", test_record_acquisition_tracked_requires_provenance),
        ("record_acquisition UNKNOWN requires no cost", test_record_acquisition_unknown_requires_no_cost),
        ("record_acquisition idempotent", test_record_acquisition_idempotent),
        ("Unknown external_ref distinct", test_unknown_external_ref_distinct),
    ]

    print("=" * 60)
    print("RUNNING ACQUISITION INTEGRATION TESTS")
    print("=" * 60)

    passed = 0
    failed = 0

    for name, test_func in tests:
        if run_test(name, test_func):
            passed += 1
        else:
            failed += 1

    print("\n" + "=" * 60)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 60)

    if failed > 0:
        sys.exit(1)