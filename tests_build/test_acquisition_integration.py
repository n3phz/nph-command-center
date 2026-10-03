import sys
sys.path.insert(0, "app")
"""Tests for Phase 2 acquisition detection integration.

These tests verify the end-to-end flow from inventory snapshot
through acquisition detection to ledger persistence.
"""

import sqlite3
from decimal import Decimal
from datetime import date, datetime, timezone
from unittest.mock import Mock

# import pytest

from acquisition import Repository, record_acquisition, AcquisitionError
from acquisition_detector import (
    AcquisitionDetector,
    InventorySnapshot,
    InventoryDelta,
    MarketHistoryPurchase,
)
from transactions import CostStatus, SourceType, Provenance, EvidenceType


# --- Schema helpers (match production V0.5.0+) -----------------------------


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


# --- Fixtures --------------------------------------------------------------


@pytest.fixture
def conn():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    create_full_schema(connection)
    yield connection
    connection.close()


@pytest.fixture
def repo(conn):
    return Repository(conn)


@pytest.fixture
def detector(repo):
    return AcquisitionDetector(repo, "Rixqor")


@pytest.fixture
def mock_session():
    return Mock()


# --- Test 1: Initial inventory snapshot creates UNKNOWN acquisitions --------


def test_initial_snapshot_creates_unknown(repo, detector, mock_session):
    """First snapshot for a bot creates UNKNOWN for all items."""
    # Insert initial snapshot with 2 items
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Card A", "amount": 2},
        {"market_hash_name": "Card B", "amount": 1},
    ])

    detector.fetch_market_history_for_item = Mock(return_value=[])

    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 2
    for r in results:
        assert r.cost_status == CostStatus.UNKNOWN
        assert r.created == True
        assert r.lot_id is not None
        assert r.error is None

    # Verify DB state
    lot_count = conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots WHERE cost_status = 'UNKNOWN'"
    ).fetchone()[0]
    assert lot_count == 2


# --- Test 2: New item detected on subsequent snapshot ----------------------


def test_new_item_on_subsequent_snapshot(repo, detector, mock_session):
    """New item appearing in later snapshot creates UNKNOWN acquisition."""
    # Snapshot 1: empty
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])

    # Snapshot 2: 1 new item
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "New Card", "amount": 1},
    ])

    detector.fetch_market_history_for_item = Mock(return_value=[])

    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    assert results[0].market_hash_name == "New Card"
    assert results[0].quantity == 1
    assert results[0].cost_status == CostStatus.UNKNOWN


# --- Test 3: Quantity increase detected ------------------------------------


def test_quantity_increase_detected(repo, detector, mock_session):
    """Quantity increase from 1 to 3 creates acquisition for delta (+2)."""
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Multi Card", "amount": 1},
    ])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Multi Card", "amount": 3},
    ])

    detector.fetch_market_history_for_item = Mock(return_value=[])

    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    assert results[0].market_hash_name == "Multi Card"
    assert results[0].quantity == 2  # delta of +2
    assert results[0].cost_status == CostStatus.UNKNOWN


# --- Test 4: Quantity decrease does NOT create acquisition -----------------


def test_quantity_decrease_no_acquisition(repo, detector, mock_session):
    """Quantity decrease from 3 to 1 creates no acquisition."""
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Multi Card", "amount": 3},
    ])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Multi Card", "amount": 1},
    ])

    detector.fetch_market_history_for_item = Mock(return_value=[])

    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 0


# --- Test 5: No inventory change -------------------------------------------


def test_no_inventory_change_no_acquisition(repo, detector, mock_session):
    """Identical snapshots create no acquisitions."""
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Same Card", "amount": 2},
    ])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Same Card", "amount": 2},
    ])

    detector.fetch_market_history_for_item = Mock(return_value=[])

    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 0


# --- Test 6: Market History exact match creates TRACKED --------------------


def test_market_history_exact_match_creates_tracked(repo, detector, mock_session):
    """Exact quantity match in Market History creates TRACKED acquisition."""
    # Snapshot 1: empty
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])

    # Snapshot 2: item purchased
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Purchased Card", "amount": 1},
    ])

    # Matching Market History purchase (exact quantity)
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

    # Need fresh detector to pick up new snapshot
    fresh_detector = AcquisitionDetector(repo, "Rixqor")
    fresh_detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])

    results = fresh_detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    r = results[0]
    assert r.market_hash_name == "Purchased Card"
    assert r.cost_status == CostStatus.TRACKED
    assert r.created == True
    assert r.lot_id is not None

    # Verify unit cost is correct (5000 cents / 100 / 1 = 50.00)
    lot = conn.execute(
        "SELECT unit_cost FROM acquisition_lots WHERE cost_status = 'TRACKED'"
    ).fetchone()
    assert lot is not None
    assert Decimal(lot[0]) == Decimal("50.00")


# --- Test 7: Market History partial/quantity match -------------------------


def test_market_history_partial_match_creates_tracked(repo, detector, mock_session):
    """Purchase with >= quantity creates TRACKED (purchase qty >= delta qty)."""
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Partial Card", "amount": 1},
    ])

    # Purchase was for 2 items, we only received 1 (or only detecting 1)
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

    fresh_detector = AcquisitionDetector(repo, "Rixqor")
    fresh_detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])

    results = fresh_detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    r = results[0]
    assert r.cost_status == CostStatus.TRACKED
    # Unit cost = 10000 cents / 100 / 2 = 50.00 per unit
    lot = conn.execute(
        "SELECT unit_cost FROM acquisition_lots WHERE cost_status = 'TRACKED'"
    ).fetchone()
    assert Decimal(lot[0]) == Decimal("50.00")


# --- Test 8: No Market History match creates UNKNOWN -----------------------


def test_no_market_history_match_creates_unknown(repo, detector, mock_session):
    """No matching purchase in Market History → UNKNOWN acquisition."""
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Mystery Card", "amount": 1},
    ])

    # No matching purchase returned
    fresh_detector = AcquisitionDetector(repo, "Rixqor")
    fresh_detector.fetch_market_history_for_item = Mock(return_value=[])

    results = fresh_detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    assert results[0].cost_status == CostStatus.UNKNOWN


# --- Test 9: Repeated polling does not create duplicate TRACKED ------------


def test_repeated_polling_no_duplicate_tracked(repo, detector, mock_session):
    """Re-running detection on same snapshot creates no duplicates."""
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

    # Verify only 1 lot in DB
    lot_count = conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots WHERE cost_status = 'TRACKED'"
    ).fetchone()[0]
    assert lot_count == 1


# --- Test 10: Repeated UNKNOWN acquisitions remain distinct ----------------


def test_repeated_unknown_remain_distinct(repo, detector, mock_session):
    """Each UNKNOWN acquisition gets unique external_ref when provenance unavailable."""
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Mystery Card", "amount": 1},
    ])

    d1 = AcquisitionDetector(repo, "Rixqor")
    d1.fetch_market_history_for_item = Mock(return_value=[])
    results1 = d1.detect_acquisition(mock_session, process_new_snapshots=True)
    lot_id_1 = results1[0].lot_id

    # Simulate another new item in a later snapshot
    insert_snapshot(conn, "Rixqor", "2026-09-22T10:00:00Z", [
        {"market_hash_name": "Mystery Card", "amount": 2},  # now 2 total
    ])

    d2 = AcquisitionDetector(repo, "Rixqor")
    d2.fetch_market_history_for_item = Mock(return_value=[])
    results2 = d2.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results2) == 1
    assert results2[0].quantity == 1  # delta of +1
    assert results2[0].lot_id != lot_id_1  # different lot
    assert results2[0].cost_status == CostStatus.UNKNOWN

    # Verify 2 UNKNOWN lots for same item
    lot_count = conn.execute(
        "SELECT COUNT(*) FROM acquisition_lots WHERE market_hash_name = 'Mystery Card' AND cost_status = 'UNKNOWN'"
    ).fetchone()[0]
    assert lot_count == 2


# --- Test 11: Verified acquisition cost reaches ledger correctly ----------


def test_verified_acquisition_cost_in_ledger(repo, detector, mock_session):
    """TRACKED acquisition has correct unit_cost persisted in ledger."""
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

    fresh_detector = AcquisitionDetector(repo, "Rixqor")
    fresh_detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])

    results = fresh_detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    r = results[0]
    assert r.cost_status == CostStatus.TRACKED

    # Verify ledger: transaction unit_price = unit_cost = 150.00
    tx = conn.execute(
        """SELECT unit_price, fees, total_value FROM transactions
           WHERE market_hash_name = 'Cost Card'""").fetchone()
    assert tx is not None
    assert Decimal(tx[0]) == Decimal("150.00")  # unit_price = unit_cost
    assert Decimal(tx[1]) == Decimal("0")  # fees = 0 for acquisition
    assert Decimal(tx[2]) == Decimal("300.00")  # total = 150 * 2

    # Verify lot unit_cost
    lot = conn.execute(
        "SELECT unit_cost FROM acquisition_lots WHERE cost_status = 'TRACKED'"
    ).fetchone()
    assert Decimal(lot[0]) == Decimal("150.00")


# --- Test 12: Market price is never used as cost ---------------------------


def test_market_price_never_used_as_cost(repo, detector, mock_session):
    """Even if market price available, only verified purchase cost is used."""
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Price Card", "amount": 1},
    ])

    # Market History returns a purchase at 10.00
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

    fresh_detector = AcquisitionDetector(repo, "Rixqor")
    fresh_detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])

    results = fresh_detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    r = results[0]
    assert r.cost_status == CostStatus.TRACKED

    # Verify acquisition cost is the purchase price (10.00), NOT current market price
    lot = conn.execute(
        "SELECT unit_cost FROM acquisition_lots WHERE cost_status = 'TRACKED'"
    ).fetchone()
    assert Decimal(lot[0]) == Decimal("10.00")


# --- Test 13: Phase 1 invariants remain intact -----------------------------


def test_phase1_invariants_preserved(repo, detector, mock_session):
    """Phase 1 invariants: UNKNOWN has no cost, TRACKED has provenance."""
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
    assert unk_lot[0] is None  # unit_cost = NULL
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
    assert trk_lot[0] is not None  # unit_cost is set
    assert Decimal(trk_lot[0]) > 0
    assert trk_lot[1] == "TRACKED"

    # Verify transaction exists with external_ref
    tx = conn.execute(
        "SELECT external_ref FROM transactions WHERE market_hash_name = 'Tracked Card'"
    ).fetchone()
    assert tx is not None
    assert tx[0] == "listing-123:purchase-456"


# --- Test 14: Existing transaction behavior not corrupted ------------------


def test_existing_transactions_not_duplicated(repo, detector, mock_session):
    """Pre-existing transactions/ lots are not duplicated or modified."""
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

    # Verify existing lot unchanged
    existing_lot = conn.execute(
        "SELECT remaining_quantity, unit_cost FROM acquisition_lots WHERE market_hash_name = 'Existing Card'"
    ).fetchone()
    assert existing_lot[0] == 1  # remaining unchanged
    assert Decimal(existing_lot[1]) == Decimal("25.00")

    # Verify new lot created
    new_lot = conn.execute(
        "SELECT cost_status FROM acquisition_lots WHERE market_hash_name = 'New Card'"
    ).fetchone()
    assert new_lot[0] == "UNKNOWN"


# --- Test 15: No SELL candidate behavior change ----------------------------


def test_sell_allocation_unchanged(repo, detector, mock_session):
    """Acquisition detection does not affect SELL allocation logic."""
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

    # Verify Sell Card lot unchanged
    sell_lot = conn.execute(
        "SELECT remaining_quantity, unit_cost FROM acquisition_lots WHERE market_hash_name = 'Sell Card'"
    ).fetchone()
    assert sell_lot[0] == 2
    assert Decimal(sell_lot[1]) == Decimal("10.00")


# --- Test 16: Market valuation never becomes acquisition cost --------------


def test_market_valuation_not_acquisition_cost(repo, detector, mock_session):
    """Current market prices are never used as acquisition cost."""
    # This is enforced by only using Market History purchases for TRACKED
    # UNKNOWN lots have unit_cost = NULL
    # Test already covered by test_market_price_never_used_as_cost


# --- Test 17: Re-running same cycle no duplicate tracked -------------------


def test_rerun_same_cycle_no_duplicate(repo, detector, mock_session):
    """Re-running detection on already-processed snapshot produces no results."""
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

    # First run
    d1 = AcquisitionDetector(repo, "Rixqor")
    d1.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    r1 = d1.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(r1) == 1

    # Second run on same snapshot
    d2 = AcquisitionDetector(repo, "Rixqor")
    d2.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    r2 = d2.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(r2) == 0

    # Third run
    d3 = AcquisitionDetector(repo, "Rixqor")
    d3.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    r3 = d3.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(r3) == 0


# --- Test 18: Different bots have independent processing -------------------


def test_different_bots_independent(repo, detector, mock_session):
    """Each bot's snapshots are processed independently."""
    # Bot 1 snapshot
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Bot1 Card", "amount": 1},
    ])
    # Bot 2 snapshot
    insert_snapshot(conn, "cesarpereira27", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Bot2 Card", "amount": 1},
    ])

    detector.fetch_market_history_for_item = Mock(return_value=[])

    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(results) == 1
    assert results[0].market_hash_name == "Bot1 Card"

    # Bot 2 should have its own detector
    detector2 = AcquisitionDetector(repo, "cesarpereira27")
    detector2.fetch_market_history_for_item = Mock(return_value=[])
    results2 = detector2.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(results2) == 1
    assert results2[0].market_hash_name == "Bot2 Card"


# --- Test 19: record_acquisition TRACKED validation ------------------------


def test_record_acquisition_tracked_requires_provenance(repo):
    """record_acquisition enforces provenance for TRACKED."""
    with pytest.raises(AcquisitionError, match="TRACKED cost requires provenance"):
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


# --- Test 20: record_acquisition UNKNOWN requires unit_cost=None -----------


def test_record_acquisition_unknown_requires_no_cost(repo):
    """record_acquisition enforces unit_cost=None for UNKNOWN."""
    with pytest.raises(AcquisitionError, match="UNKNOWN cost requires unit_cost = None"):
        record_acquisition(
            repository=repo,
            bot_name="Rixqor",
            market_hash_name="Test",
            quantity=1,
            acquired_at=date.today().isoformat(),
            unit_cost=Decimal("10.00"),  # Should be None
            currency=None,
            source_type=None,
            provenance=None,
            external_reference="ext-ref-2",
            entered_at=datetime.now(timezone.utc).isoformat(),
        )


# --- Test 21: record_acquisition idempotency -------------------------------


def test_record_acquisition_idempotent(repo):
    """record_acquisition is idempotent via external_reference."""
    prov = Provenance(
        evidence_type=EvidenceType.STEAM_MARKET_HISTORY,
        evidence_id="purchase-123",
        evidence_data={"listingid": "listing-456"},
    )

    # First call
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

    # Second call with same external_reference
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

    # Verify only 1 transaction and 1 lot
    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert tx_count == 1
    assert lot_count == 1


# --- Test 22: Unknown external_ref for UNKNOWN creates distinct lots -------


def test_unknown_external_ref_distinct(repo):
    """Each UNKNOWN acquisition gets unique external_reference."""
    # First UNKNOWN
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

    # Second UNKNOWN for same item (different external_ref)
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

    # Same external_ref would be idempotent
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])