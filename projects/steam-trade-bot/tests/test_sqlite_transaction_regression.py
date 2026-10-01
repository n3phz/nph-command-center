"""
SQLite Transaction Regression Tests

These tests verify the fix for the zero-positive-delta snapshot processing
bug where _mark_snapshot_processed_atomic() was called without an enclosing
BEGIN/COMMIT, leaving an open write transaction that blocked subsequent
database writes with "database is locked".

Test coverage:
- zero-delta snapshot is marked processed and committed
- database connection is released after zero-delta processing
- subsequent write from another SQLite connection succeeds
- positive-delta acquisition remains atomic
- exception during positive-delta processing rolls back both acquisition data and processing marker
- production sequence: bot A zero-delta -> bot B write succeeds
"""

import sys
sys.path.insert(0, 'app')

import sqlite3
import tempfile
import os
from datetime import datetime, timezone, timedelta
from decimal import Decimal

from acquisition import Repository, record_acquisition
from acquisition_detector import AcquisitionDetector, InventorySnapshot, InventoryDelta
from transactions import SourceType, Provenance, EvidenceType, CostStatus


def create_test_db():
    """Create a fresh test database with Phase 2 schema."""
    fd, path = tempfile.mkstemp(suffix='.db')
    os.close(fd)
    
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    
    # Phase 2 schema
    conn.executescript("""
        CREATE TABLE inventory_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT NOT NULL,
            captured_at TEXT NOT NULL,
            item_count INTEGER NOT NULL
        );
        
        CREATE TABLE inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            market_hash_name TEXT NOT NULL,
            amount INTEGER NOT NULL,
            FOREIGN KEY (snapshot_id) REFERENCES inventory_snapshots(id)
        );
        
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL,
            market_hash_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price TEXT NOT NULL,
            fees TEXT NOT NULL,
            total_value TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            external_ref TEXT
        );
        
        CREATE TABLE acquisition_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_transaction_id INTEGER NOT NULL,
            market_hash_name TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            original_quantity INTEGER NOT NULL,
            remaining_quantity INTEGER NOT NULL,
            unit_cost TEXT,
            acquired_at TEXT NOT NULL,
            cost_status TEXT NOT NULL,
            source_type TEXT,
            provenance TEXT,
            external_ref TEXT,
            FOREIGN KEY (source_transaction_id) REFERENCES transactions(id)
        );
        
        CREATE TABLE acquisition_processing_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT NOT NULL,
            snapshot_id INTEGER NOT NULL,
            processed_at TEXT NOT NULL,
            UNIQUE(bot_name, snapshot_id)
        );
    """)
    conn.commit()
    conn.close()
    return path


def create_snapshot(conn, bot_name, items, captured_at=None):
    """Create an inventory snapshot with items."""
    if captured_at is None:
        captured_at = datetime.now(timezone.utc).isoformat()
    
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO inventory_snapshots (bot_name, captured_at, item_count) VALUES (?, ?, ?)",
        (bot_name, captured_at, len(items))
    )
    snapshot_id = cur.lastrowid
    
    for mhn, qty in items.items():
        cur.execute(
            "INSERT INTO inventory_items (snapshot_id, market_hash_name, amount) VALUES (?, ?, ?)",
            (snapshot_id, mhn, qty)
        )
    conn.commit()
    return snapshot_id


def test_zero_delta_marks_processed_and_commits():
    """Test that zero-delta snapshot gets processing log entry committed."""
    db_path = create_test_db()
    conn = None
    try:
        c1 = sqlite3.connect(db_path)
        create_snapshot(c1, "BotA", {"Item1": 1, "Item2": 2}, "2026-01-01T10:00:00+00:00")
        create_snapshot(c1, "BotA", {"Item1": 1, "Item2": 2}, "2026-01-01T11:00:00+00:00")
        c1.close()
        
        # Run detector with zero deltas
        conn = sqlite3.connect(db_path)
        repo = Repository(conn)
        detector = AcquisitionDetector(repo, "BotA")
        
        class MockSession:
            pass
        
        results = detector.detect_acquisition(MockSession(), process_new_snapshots=True)
        
        # Should have no results (no positive deltas)
        assert len(results) == 0, f"Expected 0 results, got {len(results)}"
        
        # Check processing log was committed
        c2 = sqlite3.connect(db_path)
        count = c2.execute(
            "SELECT COUNT(*) FROM acquisition_processing_log WHERE bot_name = ?",
            ("BotA",)
        ).fetchone()[0]
        c2.close()
        
        assert count == 1, f"Expected 1 processing log entry, got {count}"
        
        # Verify the snapshot is marked processed
        c3 = sqlite3.connect(db_path)
        log = c3.execute(
            "SELECT * FROM acquisition_processing_log WHERE bot_name = ?",
            ("BotA",)
        ).fetchone()
        c3.close()
        
        assert log is not None
        assert log[1] == "BotA"  # bot_name
        assert log[2] == 2  # latest snapshot_id
        print("✓ test_zero_delta_marks_processed_and_commits PASSED")
    finally:
        if conn:
            conn.close()
        os.unlink(db_path)


def test_zero_delta_releases_connection_subsequent_write_succeeds():
    """Test that after zero-delta processing, another connection can write."""
    db_path = create_test_db()
    conn = None
    try:
        c1 = sqlite3.connect(db_path)
        create_snapshot(c1, "BotA", {"Item1": 1}, "2026-01-01T10:00:00+00:00")
        create_snapshot(c1, "BotA", {"Item1": 1}, "2026-01-01T11:00:00+00:00")
        c1.close()
        
        # Run detector for BotA (zero deltas)
        conn = sqlite3.connect(db_path)
        repo = Repository(conn)
        detector = AcquisitionDetector(repo, "BotA")
        
        class MockSession:
            pass
        
        results = detector.detect_acquisition(MockSession(), process_new_snapshots=True)
        assert len(results) == 0
        
        # NOW attempt to write from a SEPARATE connection (simulating BotB)
        # This used to fail with "database is locked" before the fix
        c2 = sqlite3.connect(db_path, timeout=1.0)
        create_snapshot(c2, "BotB", {"Item2": 3}, "2026-01-01T12:00:00+00:00")
        c2.close()
        
        # Verify the write succeeded
        c3 = sqlite3.connect(db_path)
        count = c3.execute(
            "SELECT COUNT(*) FROM inventory_snapshots WHERE bot_name = ?",
            ("BotB",)
        ).fetchone()[0]
        c3.close()
        
        assert count == 1, f"Expected 1 BotB snapshot, got {count}"
        print("✓ test_zero_delta_releases_connection_subsequent_write_succeeds PASSED")
    finally:
        if conn:
            conn.close()
        os.unlink(db_path)


def test_production_sequence_botA_zero_delta_botB_write():
    """Reproduce exact production sequence: BotA zero-delta -> BotB write."""
    db_path = create_test_db()
    conn = None
    try:
        c1 = sqlite3.connect(db_path)
        # Initial state matching production
        create_snapshot(c1, "Rixqor", {}, "2026-09-30T00:06:40+00:00")  # snapshot 17
        create_snapshot(c1, "cesarpereira27", {"Item1": 1}, "2026-09-30T00:06:41+00:00")  # snapshot 18
        create_snapshot(c1, "Rixqor", {}, "2026-10-01T01:21:28+00:00")  # snapshot 19 (new)
        c1.close()
        
        # Run detector for Rixqor (zero deltas - empty inventory both times)
        conn = sqlite3.connect(db_path)
        repo = Repository(conn)
        detector_rixqor = AcquisitionDetector(repo, "Rixqor")
        
        class MockSession:
            pass
        
        results = detector_rixqor.detect_acquisition(MockSession(), process_new_snapshots=True)
        assert len(results) == 0
        
        # NOW simulate cesarpereira27 attempting a snapshot write
        # This should succeed without "database is locked"
        c2 = sqlite3.connect(db_path, timeout=1.0)
        create_snapshot(c2, "cesarpereira27", {"Item1": 1}, "2026-10-01T01:22:00+00:00")
        c2.close()
        
        # Verify both bots have their latest snapshots
        c3 = sqlite3.connect(db_path)
        rixqor_latest = c3.execute(
            "SELECT id FROM inventory_snapshots WHERE bot_name = 'Rixqor' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        cesar_latest = c3.execute(
            "SELECT id FROM inventory_snapshots WHERE bot_name = 'cesarpereira27' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        c3.close()
        
        assert rixqor_latest[0] == 3  # snapshot 19
        assert cesar_latest[0] == 4  # new snapshot for cesarpereira27
        
        # Verify processing log for Rixqor
        c4 = sqlite3.connect(db_path)
        log = c4.execute(
            "SELECT COUNT(*) FROM acquisition_processing_log WHERE bot_name = 'Rixqor'"
        ).fetchone()[0]
        c4.close()
        
        assert log == 1
        
        print("✓ test_production_sequence_botA_zero_delta_botB_write PASSED")
    finally:
        if conn:
            conn.close()
        os.unlink(db_path)


def test_positive_delta_atomic_acquisition_and_processing_marker():
    """Test that positive-delta path commits both acquisition and processing marker atomically."""
    db_path = create_test_db()
    conn = None
    try:
        c1 = sqlite3.connect(db_path)
        # First snapshot
        create_snapshot(c1, "BotA", {"Item1": 1}, "2026-01-01T10:00:00+00:00")
        # Second snapshot with increase (positive delta)
        create_snapshot(c1, "BotA", {"Item1": 2}, "2026-01-01T11:00:00+00:00")
        c1.close()
        
        # Run detector - will need Market History but we can test the atomicity
        # by checking what happens when we mock the session to return no purchases
        # (creating UNKNOWN lots)
        
        conn = sqlite3.connect(db_path)
        repo = Repository(conn)
        detector = AcquisitionDetector(repo, "BotA")
        
        class MockSession:
            pass
        
        # With no Market History matches, we'll get UNKNOWN lots
        results = detector.detect_acquisition(MockSession(), process_new_snapshots=True)
        
        # Should have 1 UNKNOWN result for the +1 delta
        assert len(results) == 1
        assert results[0].cost_status.value == "UNKNOWN"
        assert results[0].created is True
        
        # Check both acquisition_lots and processing_log were committed
        c2 = sqlite3.connect(db_path)
        lots = c2.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
        logs = c2.execute("SELECT COUNT(*) FROM acquisition_processing_log").fetchone()[0]
        c2.close()
        
        assert lots == 1, f"Expected 1 acquisition lot, got {lots}"
        assert logs == 1, f"Expected 1 processing log entry, got {logs}"
        
        print("✓ test_positive_delta_atomic_acquisition_and_processing_marker PASSED")
    finally:
        if conn:
            conn.close()
        os.unlink(db_path)


def test_positive_delta_exception_rolls_back_both():
    """Test that exception during positive-delta processing rolls back both acquisition and processing marker."""
    db_path = create_test_db()
    conn = None
    try:
        c1 = sqlite3.connect(db_path)
        create_snapshot(c1, "BotA", {"Item1": 1}, "2026-01-01T10:00:00+00:00")
        create_snapshot(c1, "BotA", {"Item1": 2}, "2026-01-01T11:00:00+00:00")
        c1.close()
        
        # Create a detector that will fail during _process_delta
        # We'll monkey-patch _process_delta to raise an exception
        
        conn = sqlite3.connect(db_path)
        repo = Repository(conn)
        detector = AcquisitionDetector(repo, "BotA")
        
        class MockSession:
            pass
        
        original_process_delta = detector._process_delta
        
        def failing_process_delta(delta, session):
            raise RuntimeError("Simulated Market History failure")
        
        detector._process_delta = failing_process_delta
        
        class MockSession:
            pass
        
        # This should raise and rollback
        try:
            detector.detect_acquisition(MockSession(), process_new_snapshots=True)
            assert False, "Expected exception to be raised"
        except RuntimeError as e:
            assert "Simulated Market History failure" in str(e)
        
        # Verify BOTH acquisition_lots and processing_log are empty (rolled back)
        c2 = sqlite3.connect(db_path)
        lots = c2.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
        logs = c2.execute("SELECT COUNT(*) FROM acquisition_processing_log").fetchone()[0]
        c2.close()
        
        assert lots == 0, f"Expected 0 acquisition lots after rollback, got {lots}"
        assert logs == 0, f"Expected 0 processing logs after rollback, got {logs}"
        
        print("✓ test_positive_delta_exception_rolls_back_both PASSED")
    finally:
        if conn:
            conn.close()
        os.unlink(db_path)


def test_zero_delta_processing_is_committed():
    """Explicit test that zero-delta processing commits the processing marker."""
    db_path = create_test_db()
    conn = None
    try:
        c1 = sqlite3.connect(db_path)
        create_snapshot(c1, "BotA", {"Item1": 1}, "2026-01-01T10:00:00+00:00")
        create_snapshot(c1, "BotA", {"Item1": 1}, "2026-01-01T11:00:00+00:00")
        c1.close()
        
        conn = sqlite3.connect(db_path)
        repo = Repository(conn)
        detector = AcquisitionDetector(repo, "BotA")
        
        class MockSession:
            pass
        
        results = detector.detect_acquisition(MockSession(), process_new_snapshots=True)
        assert len(results) == 0
        
        # Verify the processing log was COMMITTED (not just in open transaction)
        # by checking from a NEW connection
        c2 = sqlite3.connect(db_path)
        count = c2.execute(
            "SELECT COUNT(*) FROM acquisition_processing_log WHERE bot_name = ?",
            ("BotA",)
        ).fetchone()[0]
        c2.close()
        
        assert count == 1, f"Expected 1 committed processing log entry, got {count}"
        
        # Also verify the log entry has correct data
        c3 = sqlite3.connect(db_path)
        log = c3.execute(
            "SELECT bot_name, snapshot_id FROM acquisition_processing_log WHERE bot_name = ?",
            ("BotA",)
        ).fetchone()
        c3.close()
        
        assert log[0] == "BotA"
        assert log[1] == 2  # latest snapshot
        
        print("✓ test_zero_delta_processing_is_committed PASSED")
    finally:
        if conn:
            conn.close()
        os.unlink(db_path)


if __name__ == "__main__":
    print("Running SQLite Transaction Regression Tests...\n")
    
    test_zero_delta_marks_processed_and_commits()
    test_zero_delta_releases_connection_subsequent_write_succeeds()
    test_production_sequence_botA_zero_delta_botB_write()
    test_positive_delta_atomic_acquisition_and_processing_marker()
    test_positive_delta_exception_rolls_back_both()
    test_zero_delta_processing_is_committed()
    
    print("\n=== ALL SQLITE TRANSACTION REGRESSION TESTS PASSED ===")
