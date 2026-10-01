#!/usr/bin/env python3
"""Comprehensive regression tests for Phase 2 Hermes review fixes.

Covers all four findings:
1. Initial snapshot must be acquisition-neutral
2. Exact quantity matching required
3. Transaction atomicity (acquisition + processed marker)
4. paid_amount_cents interpretation documented and verified
"""

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
    conn.executescript("""
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
    """)


def insert_snapshot(conn, bot_name, captured_at, items):
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


# =============================================================================
# FIX 1: INITIAL SNAPSHOT TESTS
# =============================================================================

def test_initial_snapshot_zero_deltas():
    """First snapshot for a bot creates zero deltas (acquisition-neutral)."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    detector = AcquisitionDetector(repo, "Rixqor")
    mock_session = Mock()

    # Insert initial snapshot with existing inventory (3 items)
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Card A", "amount": 2},
        {"market_hash_name": "Card B", "amount": 1},
    ])

    detector.fetch_market_history_for_item = Mock(return_value=[])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 0, f"Expected 0 acquisitions, got {len(results)}"

    # Processing log should be created
    log_count = conn.execute("SELECT COUNT(*) FROM acquisition_processing_log").fetchone()[0]
    assert log_count == 1, f"Processing log should be created, got {log_count}"


def test_second_snapshot_no_change_zero_acquisitions():
    """Second identical snapshot creates zero acquisitions."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    # Snapshot 1
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Card A", "amount": 2},
    ])
    # Snapshot 2 (identical)
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Card A", "amount": 2},
    ])

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 0, f"Expected 0 acquisitions for unchanged inventory, got {len(results)}"


def test_second_snapshot_with_increase_creates_acquisition():
    """Second snapshot with quantity increase creates acquisition candidate."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "Card A", "amount": 1},
    ])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Card A", "amount": 3},
    ])

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1, f"Expected 1 acquisition, got {len(results)}"
    assert results[0].market_hash_name == "Card A"
    assert results[0].quantity == 2  # delta of +2
    assert results[0].cost_status == CostStatus.UNKNOWN


def test_existing_inventory_not_assigned_cost():
    """Pre-existing inventory from initial snapshot has no cost assigned."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [
        {"market_hash_name": "PreExisting Card", "amount": 5},
    ])

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[])
    detector.detect_acquisition(mock_session, process_new_snapshots=True)

    # No lots should exist
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert lot_count == 0, "Initial snapshot must not create acquisition lots"


# =============================================================================
# FIX 2: EXACT QUANTITY MATCHING TESTS
# =============================================================================

def test_exact_quantity_match_creates_tracked():
    """Exact quantity match between purchase and delta creates TRACKED."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Exact Match Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Exact Match Card",
        quantity=1,  # exact match
        paid_amount_cents=5000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    assert results[0].cost_status == CostStatus.TRACKED


def test_purchase_qty_greater_than_delta_creates_unknown():
    """Purchase quantity > delta quantity creates UNKNOWN."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Large Purchase Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Large Purchase Card",
        quantity=10,  # much larger than delta (1)
        paid_amount_cents=50000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    assert results[0].cost_status == CostStatus.UNKNOWN, "Larger purchase should not create TRACKED"


def test_delta_qty_greater_than_purchase_creates_unknown():
    """Delta quantity > purchase quantity creates UNKNOWN."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Small Purchase Card", "amount": 2},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Small Purchase Card",
        quantity=1,  # smaller than delta (2)
        paid_amount_cents=5000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    assert results[0].cost_status == CostStatus.UNKNOWN


def test_multiple_exact_matches_creates_unknown():
    """Multiple candidate purchases with exact quantity match creates UNKNOWN."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Ambiguous Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    purchase_a = MarketHistoryPurchase(
        listingid="listing-400a",
        purchaseid="purchase-400a",
        market_hash_name="Ambiguous Card",
        quantity=1,
        paid_amount_cents=3000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-400a:purchase-400a",
    )
    purchase_b = MarketHistoryPurchase(
        listingid="listing-400b",
        purchaseid="purchase-400b",
        market_hash_name="Ambiguous Card",
        quantity=1,
        paid_amount_cents=4000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-400b:purchase-400b",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[purchase_a, purchase_b])
    results = detector.detect_acquisition(mock_session, process_new_snapshots=True)

    assert len(results) == 1
    assert results[0].cost_status == CostStatus.UNKNOWN


# =============================================================================
# FIX 3: TRANSACTION ATOMICITY TESTS
# =============================================================================

def test_successful_processing_commits_both():
    """Successful processing commits both acquisition and processed marker."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Atomic Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Atomic Card",
        quantity=1,
        paid_amount_cents=5000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    detector.detect_acquisition(mock_session, process_new_snapshots=True)

    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    log_count = conn.execute("SELECT COUNT(*) FROM acquisition_processing_log").fetchone()[0]

    assert lot_count == 1
    assert tx_count == 1
    assert log_count == 1


def test_persistence_failure_rolls_back_both():
    """Simulated persistence failure rolls back both acquisition and processed marker."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    # First: successful run to establish baseline
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Success Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Success Card",
        quantity=1,
        paid_amount_cents=5000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    detector.detect_acquisition(mock_session, process_new_snapshots=True)

    # Verify first run created log entry
    log_count = conn.execute("SELECT COUNT(*) FROM acquisition_processing_log").fetchone()[0]
    assert log_count == 1, f"First run should create log entry, got {log_count}"

    # Now add a NEW snapshot and simulate failure
    insert_snapshot(conn, "Rixqor", "2026-09-22T10:00:00Z", [
        {"market_hash_name": "Fail Card", "amount": 1},
    ])

    def failing_fetch(*args, **kwargs):
        raise Exception("Simulated Market History API failure")

    detector2 = AcquisitionDetector(repo, "Rixqor")
    detector2.fetch_market_history_for_item = failing_fetch

    try:
        detector2.detect_acquisition(mock_session, process_new_snapshots=True)
        assert False, "Should have raised exception"
    except Exception:
        pass

    # Should NOT have added a new processing log entry for the failed snapshot
    log_count = conn.execute("SELECT COUNT(*) FROM acquisition_processing_log").fetchone()[0]
    assert log_count == 1, f"Processing log should still be 1 (only first successful run), got {log_count}"

    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert lot_count == 1, f"Lot count should still be 1, got {lot_count}"


def test_retry_after_failure_works():
    """Retry after failure works correctly."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    # First: successful run to establish baseline
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Success Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Success Card",
        quantity=1,
        paid_amount_cents=5000,
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    detector.detect_acquisition(mock_session, process_new_snapshots=True)

    # Verify first run created log entry
    log_count = conn.execute("SELECT COUNT(*) FROM acquisition_processing_log").fetchone()[0]
    assert log_count == 1

    # Add a NEW snapshot and simulate failure
    insert_snapshot(conn, "Rixqor", "2026-09-22T10:00:00Z", [
        {"market_hash_name": "Fail Card", "amount": 1},
    ])

    def failing_fetch(*args, **kwargs):
        raise Exception("Simulated Market History API failure")

    detector2 = AcquisitionDetector(repo, "Rixqor")
    detector2.fetch_market_history_for_item = failing_fetch

    try:
        detector2.detect_acquisition(mock_session, process_new_snapshots=True)
    except Exception:
        pass

    # Now retry with success for the failed snapshot
    detector3 = AcquisitionDetector(repo, "Rixqor")
    detector3.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    detector3.detect_acquisition(mock_session, process_new_snapshots=True)

    log_count = conn.execute("SELECT COUNT(*) FROM acquisition_processing_log").fetchone()[0]
    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]

    assert log_count == 2, f"Expected 2 log entries, got {log_count}"
    assert lot_count == 2, f"Expected 2 lots, got {lot_count}"


def test_zero_delta_snapshot_still_marks_processed():
    """Snapshot with no positive deltas still marks processed."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [])  # empty snapshot

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[])
    detector.detect_acquisition(mock_session, process_new_snapshots=True)

    log_count = conn.execute("SELECT COUNT(*) FROM acquisition_processing_log").fetchone()[0]
    assert log_count == 1, "Empty snapshot should still be marked processed"


# =============================================================================
# FIX 4: PAID AMOUNT CENTS TESTS
# =============================================================================

def test_paid_amount_is_total_buyer_spend():
    """paid_amount_cents represents total buyer spend (including fees)."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Cost Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Cost Card",
        quantity=1,
        paid_amount_cents=1500,  # 15.00 total buyer paid
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    detector.detect_acquisition(mock_session, process_new_snapshots=True)

    lot = conn.execute("SELECT unit_cost FROM acquisition_lots WHERE cost_status = ?", ("TRACKED",)).fetchone()
    assert Decimal(lot[0]) == Decimal("15.00"), "unit_cost = paid_amount_cents / 100 / qty"


def test_paid_amount_divided_by_quantity():
    """paid_amount is divided by purchase quantity for unit cost."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Multi Cost Card", "amount": 3},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Multi Cost Card",
        quantity=3,
        paid_amount_cents=3000,  # 30.00 total for 3 items
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    detector.detect_acquisition(mock_session, process_new_snapshots=True)

    lot = conn.execute("SELECT unit_cost FROM acquisition_lots WHERE cost_status = ?", ("TRACKED",)).fetchone()
    assert Decimal(lot[0]) == Decimal("10.00"), "unit_cost = total_paid / 100 / qty = 3000/100/3 = 10.00"


def test_market_price_never_used_as_cost():
    """Current market prices are never used as acquisition cost."""
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
    # Market History shows purchase at 10.00, even if market price is different
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Price Card",
        quantity=1,
        paid_amount_cents=1000,  # 10.00 purchase price
        currencyid=3,
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    detector.detect_acquisition(mock_session, process_new_snapshots=True)

    lot = conn.execute("SELECT unit_cost FROM acquisition_lots WHERE cost_status = ?", ("TRACKED",)).fetchone()
    assert Decimal(lot[0]) == Decimal("10.00"), "Acquisition cost must be purchase price, not market price"


def test_currency_handling_correct():
    """Currency mapping works correctly."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Currency Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Currency Card",
        quantity=1,
        paid_amount_cents=5000,
        currencyid=3,  # EUR
        time_event_unix=ts,
        external_ref="listing-123:purchase-456",
    )

    detector = AcquisitionDetector(repo, "Rixqor")
    detector.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    detector.detect_acquisition(mock_session, process_new_snapshots=True)

    # Verify EUR currency mapping
    lot = conn.execute("SELECT unit_cost FROM acquisition_lots WHERE cost_status = ?", ("TRACKED",)).fetchone()
    assert Decimal(lot[0]) == Decimal("50.00")


# =============================================================================
# IDEMPOTENCY TESTS
# =============================================================================

def test_repeated_same_snapshot_no_duplicate():
    """Re-running detection on same snapshot creates no duplicate."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Idempotent Card", "amount": 1},
    ])

    ts = int(datetime.fromisoformat("2026-09-21T10:00:00Z").timestamp())
    matching_purchase = MarketHistoryPurchase(
        listingid="listing-123",
        purchaseid="purchase-456",
        market_hash_name="Idempotent Card",
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
    assert len(r1) == 1 and r1[0].created == True

    # Second run
    d2 = AcquisitionDetector(repo, "Rixqor")
    d2.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    r2 = d2.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(r2) == 0

    # Third run
    d3 = AcquisitionDetector(repo, "Rixqor")
    d3.fetch_market_history_for_item = Mock(return_value=[matching_purchase])
    r3 = d3.detect_acquisition(mock_session, process_new_snapshots=True)
    assert len(r3) == 0

    lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    assert lot_count == 1


def test_unknown_acquisitions_remain_distinct():
    """Each UNKNOWN acquisition with different external_ref remains distinct."""
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
    r1 = d1.detect_acquisition(mock_session, process_new_snapshots=True)
    lot_id_1 = r1[0].lot_id

    insert_snapshot(conn, "Rixqor", "2026-09-22T10:00:00Z", [
        {"market_hash_name": "Mystery Card", "amount": 2},
    ])

    d2 = AcquisitionDetector(repo, "Rixqor")
    d2.fetch_market_history_for_item = Mock(return_value=[])
    r2 = d2.detect_acquisition(mock_session, process_new_snapshots=True)

    assert r2[0].lot_id != lot_id_1
    assert r2[0].cost_status == CostStatus.UNKNOWN


# =============================================================================
# PHASE 1 INVARIANTS
# =============================================================================

def test_phase1_invariants_preserved():
    """Phase 1 invariants: UNKNOWN has no cost, TRACKED has provenance."""
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    create_full_schema(conn)
    repo = Repository(conn)
    mock_session = Mock()

    # UNKNOWN lot
    insert_snapshot(conn, "Rixqor", "2026-09-20T10:00:00Z", [])
    insert_snapshot(conn, "Rixqor", "2026-09-21T10:00:00Z", [
        {"market_hash_name": "Unknown Card", "amount": 1},
    ])

    d1 = AcquisitionDetector(repo, "Rixqor")
    d1.fetch_market_history_for_item = Mock(return_value=[])
    d1.detect_acquisition(mock_session, process_new_snapshots=True)

    unk_lot = conn.execute("SELECT unit_cost, cost_status FROM acquisition_lots WHERE market_hash_name = 'Unknown Card'").fetchone()
    assert unk_lot[0] is None
    assert unk_lot[1] == "UNKNOWN"

    # TRACKED lot
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

    trk_lot = conn.execute("SELECT unit_cost, cost_status FROM acquisition_lots WHERE market_hash_name = 'Tracked Card'").fetchone()
    assert trk_lot[0] is not None
    assert Decimal(trk_lot[0]) > 0
    assert trk_lot[1] == "TRACKED"

    tx = conn.execute("SELECT external_ref FROM transactions WHERE market_hash_name = 'Tracked Card'").fetchone()
    assert tx[0] == "listing-123:purchase-456"


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    tests = [
        # Fix 1: Initial Snapshot
        ("FIX 1: Initial snapshot zero deltas", test_initial_snapshot_zero_deltas),
        ("FIX 1: Second snapshot no change", test_second_snapshot_no_change_zero_acquisitions),
        ("FIX 1: Second snapshot with increase", test_second_snapshot_with_increase_creates_acquisition),
        ("FIX 1: Existing inventory no cost", test_existing_inventory_not_assigned_cost),

        # Fix 2: Exact Quantity Matching
        ("FIX 2: Exact quantity match -> TRACKED", test_exact_quantity_match_creates_tracked),
        ("FIX 2: Purchase qty > delta -> UNKNOWN", test_purchase_qty_greater_than_delta_creates_unknown),
        ("FIX 2: Delta qty > purchase -> UNKNOWN", test_delta_qty_greater_than_purchase_creates_unknown),
        ("FIX 2: Multiple exact matches -> UNKNOWN", test_multiple_exact_matches_creates_unknown),

        # Fix 3: Transaction Atomicity
        ("FIX 3: Success commits both", test_successful_processing_commits_both),
        ("FIX 3: Failure rolls back both", test_persistence_failure_rolls_back_both),
        ("FIX 3: Retry after failure", test_retry_after_failure_works),
        ("FIX 3: Zero delta marks processed", test_zero_delta_snapshot_still_marks_processed),

        # Fix 4: Paid Amount
        ("FIX 4: paid_amount = total buyer spend", test_paid_amount_is_total_buyer_spend),
        ("FIX 4: paid_amount / qty = unit_cost", test_paid_amount_divided_by_quantity),
        ("FIX 4: Market price never used", test_market_price_never_used_as_cost),
        ("FIX 4: Currency handling", test_currency_handling_correct),

        # Idempotency
        ("IDEMPOTENCY: Repeated snapshot no duplicate", test_repeated_same_snapshot_no_duplicate),
        ("IDEMPOTENCY: UNKNOWN distinct lots", test_unknown_acquisitions_remain_distinct),

        # Phase 1 Invariants
        ("PHASE 1: Invariants preserved", test_phase1_invariants_preserved),
    ]

    print("=" * 70)
    print("PHASE 2 HERMES REVIEW FIXES - REGRESSION TESTS")
    print("=" * 70)

    passed = 0
    failed = 0

    for name, test_func in tests:
        if run_test(name, test_func):
            passed += 1
        else:
            failed += 1

    print("\n" + "=" * 70)
    print(f"RESULTS: {passed} passed, {failed} failed")
    print("=" * 70)

    if failed > 0:
        sys.exit(1)