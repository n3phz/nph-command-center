#!/usr/bin/env python3
"""Tests for Phase 2 schema migration (migrate_schema_v2.py).

Validates:
1. Migration creates acquisition_processing_log table
2. Required columns exist (id, bot_name, snapshot_id, processed_at)
3. UNIQUE(bot_name, snapshot_id) constraint exists
4. Migration is idempotent (can run twice safely)
5. Existing production data remains unchanged
6. Phase 2 acquisition persistence still works after migration
"""

import os
import sys
import sqlite3
import tempfile
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from migrate_schema_v2 import migrate


def create_minimal_v1_db():
    """Create a minimal V1 schema database for testing."""
    conn = sqlite3.connect(":memory:")
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
            amount INTEGER NOT NULL,
            market_hash_name TEXT NOT NULL,
            market_name TEXT,
            type TEXT,
            tradable INTEGER,
            marketable INTEGER,
            raw_json TEXT
        );
        CREATE TABLE market_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            market_hash_name TEXT NOT NULL UNIQUE,
            lowest_price TEXT,
            median_price TEXT,
            volume TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE sale_proposals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id TEXT NOT NULL UNIQUE,
            bot_name TEXT NOT NULL,
            asset_id INTEGER NOT NULL,
            market_hash_name TEXT NOT NULL,
            market_name TEXT,
            price_cents INTEGER NOT NULL,
            requested_fee_percent REAL NOT NULL,
            actual_fee_percent REAL NOT NULL,
            status TEXT NOT NULL DEFAULT 'PENDING',
            expires_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT
        );
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            market_hash_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price TEXT NOT NULL,
            fees TEXT NOT NULL DEFAULT '0',
            total_value TEXT NOT NULL DEFAULT '0',
            timestamp TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            external_ref TEXT
        );
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
    """)
    return conn


def insert_test_data(conn):
    """Insert test data to verify preservation."""
    # Insert snapshots
    conn.execute(
        "INSERT INTO inventory_snapshots (captured_at, bot_name, app_id, context_id, item_count, raw_json) VALUES (?, ?, ?, ?, ?, ?)",
        ("2026-09-29T10:00:00Z", "cesarpereira27", 753, 6, 5, "{}")
    )
    snap_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    # Insert items
    conn.execute(
        "INSERT INTO inventory_items (snapshot_id, bot_name, app_id, context_id, asset_id, class_id, instance_id, amount, market_hash_name, market_name, type, tradable, marketable, raw_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (snap_id, "cesarpereira27", 753, 6, "asset-1", "class1", "instance1", 1, "Test Item", "Test Item", "Type", 1, 1, "{}")
    )
    
    # Insert market price
    conn.execute(
        "INSERT INTO market_prices (market_hash_name, lowest_price, median_price, volume, updated_at) VALUES (?, ?, ?, ?, ?)",
        ("Test Item", "€1.50", "€1.45", "100", "2026-09-29T10:00:00Z")
    )
    
    # Insert old-format transaction
    conn.execute(
        "INSERT OR IGNORE INTO transactions (id, type, market_hash_name, quantity, unit_price, fees, total_value, timestamp, bot_name, external_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (1, "BUY", "Test Item", 1, "1.50", "0.15", "1.65", "2026-09-29T10:00:00Z", "cesarpereira27", "old-tx-1")
    )
    
    # Insert old-format acquisition lot
    conn.execute(
        "INSERT OR IGNORE INTO acquisition_lots (id, source_transaction_id, market_hash_name, original_quantity, remaining_quantity, unit_cost, acquired_at, cost_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (1, 1, "Test Item", 1, 1, "1.50", "2026-09-29T10:00:00Z", "TRACKED")
    )
    
    conn.commit()
    return conn


def test_migration_creates_processing_log():
    """Test that migration creates the acquisition_processing_log table."""
    conn = create_minimal_v1_db()
    
    print("  Creating minimal V1 database...")
    insert_test_data(conn)
    
    print("  Running migration...")
    migrate(conn)
    
    # Check table exists
    cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='acquisition_processing_log'")
    assert cursor.fetchone() is not None, "acquisition_processing_log table should be created"
    
    print("  PASS: acquisition_processing_log table created")
    conn.close()


def test_processing_log_columns():
    """Test that required columns exist in processing log table."""
    conn = create_minimal_v1_db()
    insert_test_data(conn)
    migrate(conn)
    
    # Get column info
    cursor = conn.execute("PRAGMA table_info(acquisition_processing_log)")
    cols = {row[1]: row[2] for row in cursor.fetchall()}
    
    expected_cols = {
        "id": "INTEGER",
        "bot_name": "TEXT",
        "snapshot_id": "INTEGER",
        "processed_at": "TEXT"
    }
    
    for col_name, col_type in expected_cols.items():
        assert col_name in cols, f"Column {col_name} should exist"
        assert cols[col_name] == col_type, f"Column {col_name} should be {col_type}, got {cols[col_name]}"
    
    print("  PASS: All required columns exist with correct types")
    conn.close()


def test_processing_log_unique_constraint():
    """Test that UNIQUE(bot_name, snapshot_id) constraint exists."""
    conn = create_minimal_v1_db()
    insert_test_data(conn)
    migrate(conn)
    
    # Check that the table has the right structure
    cursor = conn.execute("PRAGMA table_info('acquisition_processing_log')")
    cols = {row[1]: row for row in cursor.fetchall()}
    
    assert 'bot_name' in cols, "Column bot_name should exist"
    assert 'snapshot_id' in cols, "Column snapshot_id should exist"
    
    # Try to insert duplicate rows to verify constraint works
    conn.execute(
        "INSERT INTO acquisition_processing_log (bot_name, snapshot_id, processed_at) VALUES (?, ?, ?)",
        ("test-bot", 1, "2026-09-29T10:00:00Z")
    )
    
    try:
        conn.execute(
            "INSERT INTO acquisition_processing_log (bot_name, snapshot_id, processed_at) VALUES (?, ?, ?)",
            ("test-bot", 1, "2026-09-29T10:00:00Z")
        )
        assert False, "Should have raised an error for duplicate"
    except sqlite3.IntegrityError:
        pass  # Expected - UNIQUE constraint working
    
    print("  PASS: UNIQUE constraint works correctly")
    conn.close()


def test_migration_idempotent():
    """Test that migration can run twice safely."""
    conn = create_minimal_v1_db()
    insert_test_data(conn)
    
    print("  Running first migration...")
    migrate(conn)
    
    print("  Running second migration...")
    migrate(conn)  # Should not raise
    
    # Verify table still exists and is valid
    cursor = conn.execute("SELECT COUNT(*) FROM acquisition_processing_log")
    count = cursor.fetchone()[0]
    assert count == 0, "Table should be empty (no prior processing)"
    
    print("  PASS: Migration is idempotent")
    conn.close()


def test_existing_data_preserved():
    """Test that existing data is preserved through migration."""
    conn = create_minimal_v1_db()
    original_snapshots = insert_test_data(conn)
    
    # Record original counts
    original_snapshot_count = conn.execute("SELECT COUNT(*) FROM inventory_snapshots").fetchone()[0]
    original_item_count = conn.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0]
    original_price_count = conn.execute("SELECT COUNT(*) FROM market_prices").fetchone()[0]
    original_tx_count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    original_lot_count = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
    
    migrate(conn)
    
    # Verify counts unchanged
    assert conn.execute("SELECT COUNT(*) FROM inventory_snapshots").fetchone()[0] == original_snapshot_count
    assert conn.execute("SELECT COUNT(*) FROM inventory_items").fetchone()[0] == original_item_count
    assert conn.execute("SELECT COUNT(*) FROM market_prices").fetchone()[0] == original_price_count
    assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == original_tx_count
    assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == original_lot_count
    
    # Verify transactions have new columns
    cursor = conn.execute("PRAGMA table_info(transactions)")
    tx_cols = [row[1] for row in cursor.fetchall()]
    assert "type" in tx_cols
    assert "timestamp" in tx_cols
    assert "fees" in tx_cols
    assert "total_value" in tx_cols
    assert "bot_name" in tx_cols
    assert "external_ref" in tx_cols
    
    # Verify acquisition_lots have new columns
    cursor = conn.execute("PRAGMA table_info(acquisition_lots)")
    lot_cols = [row[1] for row in cursor.fetchall()]
    assert "source_transaction_id" in lot_cols
    assert "bot_name" in lot_cols
    assert "original_quantity" in lot_cols
    
    print("  PASS: Existing data preserved with new columns added")
    conn.close()


def test_acquisition_persistence_after_migration():
    """Test that Phase 2 acquisition detection still works after migration."""
    from decimal import Decimal
    from acquisition import Repository
    from acquisition_detector import AcquisitionDetector
    from transactions import CostStatus
    
    conn = create_minimal_v1_db()
    insert_test_data(conn)
    migrate(conn)
    
    # Verify processing log table exists and can be used
    repo = Repository(conn)
    detector = AcquisitionDetector(repo, "test-bot")
    
    # Should not raise
    detector._mark_snapshot_processed_atomic(999)
    
    log_count = conn.execute(
        "SELECT COUNT(*) FROM acquisition_processing_log WHERE bot_name=? AND snapshot_id=?",
        ("test-bot", 999)
    ).fetchone()[0]
    
    assert log_count == 1, "Processing log should have one entry"
    
    # Test idempotency - second call should not create duplicate
    detector._mark_snapshot_processed_atomic(999)
    log_count = conn.execute(
        "SELECT COUNT(*) FROM acquisition_processing_log WHERE bot_name=? AND snapshot_id=?",
        ("test-bot", 999)
    ).fetchone()[0]
    
    assert log_count == 1, "Processing log should still have one entry (idempotent)"
    
    # Verify transactions table has correct schema for new code
    cursor = conn.execute("PRAGMA table_info(transactions)")
    cols = {row[1] for row in cursor.fetchall()}
    required = {'type', 'market_hash_name', 'quantity', 'unit_price', 'fees', 'total_value', 'timestamp', 'bot_name', 'external_ref'}
    assert required.issubset(cols), f"Required columns missing: {required - cols}"
    
    print("  PASS: Acquisition persistence works after migration")
    conn.close()


def main():
    """Run all tests."""
    tests = [
        test_migration_creates_processing_log,
        test_processing_log_columns,
        test_processing_log_unique_constraint,
        test_migration_idempotent,
        test_existing_data_preserved,
        test_acquisition_persistence_after_migration,
    ]
    
    passed = 0
    failed = 0
    
    print("\n=== Phase 2 Migration Tests ===\n")
    
    for test in tests:
        try:
            print(f"\n{test.__name__}...")
            test()
            passed += 1
        except Exception as e:
            print(f"FAIL: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    print(f"\n{'='*50}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*50}\n")
    
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
