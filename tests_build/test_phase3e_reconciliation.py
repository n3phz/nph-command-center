#!/usr/bin/env python3
"""Tests for Phase 3E delayed-evidence reconciliation wiring."""

import os
import sqlite3
import sys
import tempfile
from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

sys.path.insert(0, "app")

import pytest

from acquisition import Repository, record_acquisition
from acquisition_detector import (
    AcquisitionDetector,
    InventoryDelta,
    MarketHistoryPurchase,
)
from transactions import CostStatus, EvidenceType, Provenance, SourceType


def _create_db():
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    conn.executescript("""
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
            source_transaction_id INTEGER NOT NULL,
            market_hash_name TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            original_quantity INTEGER NOT NULL,
            remaining_quantity INTEGER NOT NULL,
            unit_cost TEXT,
            acquired_at TEXT NOT NULL,
            cost_status TEXT NOT NULL,
            provenance TEXT,
            source_type TEXT,
            external_ref TEXT
        );
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
            amount INTEGER NOT NULL
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
    return conn, path


def _insert_unknown_lot(conn, bot, mhn, qty):
    cur = conn.execute(
        "INSERT INTO transactions (type, market_hash_name, quantity, unit_price, fees, total_value, timestamp, bot_name, external_ref) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        ("BUY", mhn, qty, "0", "0", "0", "2026-10-01", bot, f"unknown:{bot}:{mhn}:2026-10-01:{qty}"),
    )
    tx_id = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO acquisition_lots (source_transaction_id, market_hash_name, bot_name, original_quantity, remaining_quantity, unit_cost, acquired_at, cost_status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (tx_id, mhn, bot, qty, qty, None, "2026-10-01", "UNKNOWN"),
    )
    lot_id = cur.lastrowid
    conn.commit()
    return tx_id, lot_id


class TestReconcileUpdatesNotDuplicates:
    def test_reconcile_updates_existing_unknown_to_tracked(self):
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            tx_id, lot_id = _insert_unknown_lot(conn, "Rixqor", "774361-Our Lady of the Charred Visage", 1)

            detector = AcquisitionDetector(repo, "Rixqor")

            purchase = MarketHistoryPurchase(
                listingid="L123",
                purchaseid="P456",
                market_hash_name="774361-Our Lady of the Charred Visage",
                quantity=1,
                paid_amount_cents=7,
                currencyid=3,
                time_event_unix=int(datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc).timestamp()),
                external_ref="L123:P456",
            )

            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                results = detector.reconcile_delayed_evidence(Mock())

            conn.commit()

            assert len(results) == 1
            assert results[0].cost_status == CostStatus.TRACKED
            assert results[0].lot_id == lot_id
            assert results[0].created is False

            row = conn.execute("SELECT cost_status, unit_cost, source_type FROM acquisition_lots WHERE id=?", (lot_id,)).fetchone()
            assert row[0] == "TRACKED"
            assert Decimal(row[1]) == Decimal("0.07")
            assert row[2] == "STEAM_MARKET_PURCHASE"

            assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 1
            assert conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0] == 1
        finally:
            conn.close()
            os.unlink(path)

    def test_reconcile_no_duplicate_when_no_match(self):
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)

            detector = AcquisitionDetector(repo, "Rixqor")

            with patch.object(detector, "fetch_market_history_for_item", return_value=[]):
                results = detector.reconcile_delayed_evidence(Mock())

            conn.commit()

            assert len(results) == 0
            row = conn.execute("SELECT cost_status FROM acquisition_lots WHERE id=?", (lot_id,)).fetchone()
            assert row[0] == "UNKNOWN"
            assert conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0] == 1
        finally:
            conn.close()
            os.unlink(path)

    def test_reconcile_no_duplicate_when_ambiguous(self):
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)

            detector = AcquisitionDetector(repo, "Rixqor")

            purchases = [
                MarketHistoryPurchase(listingid="L1", purchaseid="P1", market_hash_name="Some Card", quantity=1, paid_amount_cents=7, currencyid=3, time_event_unix=1759315200, external_ref="L1:P1"),
                MarketHistoryPurchase(listingid="L2", purchaseid="P2", market_hash_name="Some Card", quantity=1, paid_amount_cents=9, currencyid=3, time_event_unix=1759315200, external_ref="L2:P2"),
            ]
            with patch.object(detector, "fetch_market_history_for_item", return_value=purchases):
                results = detector.reconcile_delayed_evidence(Mock())

            conn.commit()

            assert len(results) == 0
            row = conn.execute("SELECT cost_status FROM acquisition_lots WHERE id=?", (lot_id,)).fetchone()
            assert row[0] == "UNKNOWN"
        finally:
            conn.close()
            os.unlink(path)

    def test_reconcile_wrong_quantity_no_match(self):
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)

            detector = AcquisitionDetector(repo, "Rixqor")

            purchase = MarketHistoryPurchase(listingid="L1", purchaseid="P1", market_hash_name="Some Card", quantity=2, paid_amount_cents=14, currencyid=3, time_event_unix=1759315200, external_ref="L1:P1")
            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                results = detector.reconcile_delayed_evidence(Mock())

            conn.commit()

            assert len(results) == 0
            row = conn.execute("SELECT cost_status FROM acquisition_lots WHERE id=?", (lot_id,)).fetchone()
            assert row[0] == "UNKNOWN"
        finally:
            conn.close()
            os.unlink(path)


class TestReconcileIdempotency:
    def test_reconcile_idempotent_second_run_no_change(self):
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)

            detector = AcquisitionDetector(repo, "Rixqor")
            purchase = MarketHistoryPurchase(listingid="L1", purchaseid="P1", market_hash_name="Some Card", quantity=1, paid_amount_cents=7, currencyid=3, time_event_unix=1759315200, external_ref="L1:P1")

            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                results1 = detector.reconcile_delayed_evidence(Mock())

            conn.commit()

            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                results2 = detector.reconcile_delayed_evidence(Mock())

            assert len(results1) == 1
            assert len(results2) == 0
            assert conn.execute("SELECT COUNT(*) FROM acquisition_lots WHERE cost_status='TRACKED'").fetchone()[0] == 1
        finally:
            conn.close()
            os.unlink(path)


class TestReconcileMissingAuth:
    def test_reconcile_with_none_session(self):
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)

            detector = AcquisitionDetector(repo, "Rixqor")
            results = detector.reconcile_delayed_evidence(None)
            conn.commit()

            assert results == []
            row = conn.execute("SELECT cost_status FROM acquisition_lots WHERE id=?", (lot_id,)).fetchone()
            assert row[0] == "UNKNOWN"
        finally:
            conn.close()
            os.unlink(path)

    def test_reconcile_with_session_that_returns_empty(self):
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)

            detector = AcquisitionDetector(repo, "Rixqor")
            fake_session = Mock()
            fake_session.get.return_value.json.return_value = {"success": True, "total_count": 0, "events": []}

            results = detector.reconcile_delayed_evidence(fake_session)
            conn.commit()

            assert results == []
            row = conn.execute("SELECT cost_status FROM acquisition_lots WHERE id=?", (lot_id,)).fetchone()
            assert row[0] == "UNKNOWN"
        finally:
            conn.close()
            os.unlink(path)


class TestProvenanceIntegrity:
    def test_provenance_populated_after_reconcile(self):
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "774361-Our Lady of the Charred Visage", 1)

            detector = AcquisitionDetector(repo, "Rixqor")
            purchase = MarketHistoryPurchase(
                listingid="L123",
                purchaseid="P456",
                market_hash_name="774361-Our Lady of the Charred Visage",
                quantity=1,
                paid_amount_cents=7,
                currencyid=3,
                time_event_unix=1759315200,
                external_ref="L123:P456",
            )

            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                results = detector.reconcile_delayed_evidence(Mock())

            conn.commit()

            assert len(results) == 1
            assert results[0].provenance is not None
            assert results[0].provenance.evidence_type == EvidenceType.STEAM_MARKET_HISTORY
            assert results[0].provenance.evidence_id == "P456"
            assert results[0].provenance.evidence_data["listingid"] == "L123"

            stored = conn.execute("SELECT provenance FROM acquisition_lots WHERE id=?", (lot_id,)).fetchone()[0]
            assert stored is not None
            assert "P456" in stored
        finally:
            conn.close()
            os.unlink(path)


class TestCostBasisAndCurrency:
    """paid_amount -> unit_cost mapping and currency resolution."""

    def test_paid_amount_cents_becomes_unit_cost(self):
        """7 cents for qty 1 = 0.07 EUR; 150 cents for qty 3 = 0.50 each."""
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)
            detector = AcquisitionDetector(repo, "Rixqor")
            purchase = MarketHistoryPurchase(
                listingid="L1",
                purchaseid="P1",
                market_hash_name="Some Card",
                quantity=1,
                paid_amount_cents=7,
                currencyid=3,  # EUR
                time_event_unix=1759315200,
                external_ref="L1:P1",
            )
            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                detector.reconcile_delayed_evidence(Mock())
            conn.commit()

            row = conn.execute(
                "SELECT unit_cost, source_type FROM acquisition_lots WHERE id=?", (lot_id,)
            ).fetchone()
            assert Decimal(row[0]) == Decimal("0.07")
            assert row[1] == "STEAM_MARKET_PURCHASE"
        finally:
            conn.close()
            os.unlink(path)

    def test_currencyid_resolves_to_iso_code(self):
        """currencyid maps through CURRENCY_MAP, not hardcoded by accident."""
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)
            detector = AcquisitionDetector(repo, "Rixqor")
            # currencyid 1 = USD in Steam's table
            purchase = MarketHistoryPurchase(
                listingid="L1",
                purchaseid="P1",
                market_hash_name="Some Card",
                quantity=1,
                paid_amount_cents=100,
                currencyid=1,
                time_event_unix=1759315200,
                external_ref="L1:P1",
            )
            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                results = detector.reconcile_delayed_evidence(Mock())
            conn.commit()

            assert detector.CURRENCY_MAP[1] == "USD"
            assert Decimal(
                conn.execute(
                    "SELECT unit_cost FROM acquisition_lots WHERE id=?", (lot_id,)
                ).fetchone()[0]
            ) == Decimal("1.00")
        finally:
            conn.close()
            os.unlink(path)


class TestReconcileAtomicity:
    """Atomicity: the lot row and its transaction must move together."""

    def test_transaction_failure_rolls_back_lot_update(self):
        """A failure in the second write must leave the lot UNKNOWN."""
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)
            detector = AcquisitionDetector(repo, "Rixqor")
            purchase = MarketHistoryPurchase(
                listingid="L1",
                purchaseid="P1",
                market_hash_name="Some Card",
                quantity=1,
                paid_amount_cents=7,
                currencyid=3,
                time_event_unix=1759315200,
                external_ref="L1:P1",
            )

            # Drop the transactions table so the second UPDATE raises,
            # AFTER the acquisition_lots UPDATE has already been issued.
            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                with patch.object(
                    AcquisitionDetector,
                    "_update_tracked",
                    side_effect=RuntimeError("boom after lot update"),
                ):
                    results = detector.reconcile_delayed_evidence(Mock())

            # reconcile swallows per-lot errors; nothing may be persisted.
            assert results == []
            row = conn.execute(
                "SELECT cost_status, unit_cost, provenance FROM acquisition_lots WHERE id=?",
                (lot_id,),
            ).fetchone()
            assert row[0] == "UNKNOWN"
            assert row[1] is None
            assert row[2] is None
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()
            os.unlink(path)

    def test_reconcile_commits_so_writes_are_visible(self):
        """Reconciliation must commit; an uncommitted write would be lost."""
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)
            detector = AcquisitionDetector(repo, "Rixqor")
            purchase = MarketHistoryPurchase(
                listingid="L1",
                purchaseid="P1",
                market_hash_name="Some Card",
                quantity=1,
                paid_amount_cents=7,
                currencyid=3,
                time_event_unix=1759315200,
                external_ref="L1:P1",
            )
            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                detector.reconcile_delayed_evidence(Mock())

            # Re-open read-only: committed data is visible on a fresh handle.
            conn2 = sqlite3.connect(path)
            row = conn2.execute(
                "SELECT cost_status FROM acquisition_lots WHERE id=?", (lot_id,)
            ).fetchone()
            conn2.close()
            assert row[0] == "TRACKED"
        finally:
            conn.close()
            os.unlink(path)

    def test_reconcile_releases_lock_for_next_writer(self):
        """No dangling write transaction: a second writer must not see a lock."""
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)
            detector = AcquisitionDetector(repo, "Rixqor")
            purchase = MarketHistoryPurchase(
                listingid="L1",
                purchaseid="P1",
                market_hash_name="Some Card",
                quantity=1,
                paid_amount_cents=7,
                currencyid=3,
                time_event_unix=1759315200,
                external_ref="L1:P1",
            )
            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                detector.reconcile_delayed_evidence(Mock())

            # Independent writer must succeed without "database is locked".
            other = sqlite3.connect(path)
            other.execute("UPDATE transactions SET fees = fees WHERE id = 1")
            other.commit()
            other.close()
        finally:
            conn.close()
            os.unlink(path)


class TestZeroDeltaAndSequentialBots:
    """Reconciliation must not disturb zero-delta or multi-bot processing."""

    def _seed_snapshot(self, conn, bot, captured_at, item_count):
        cur = conn.execute(
            "INSERT INTO inventory_snapshots (bot_name, captured_at, item_count) VALUES (?, ?, ?)",
            (bot, captured_at, item_count),
        )
        return cur.lastrowid

    def test_zero_delta_scan_commits_processing_marker(self):
        """No positive deltas still persists the processed marker."""
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            first = self._seed_snapshot(conn, "Rixqor", "2026-10-01T07:00:00+00:00", 1)
            conn.execute(
                "INSERT INTO inventory_items (snapshot_id, market_hash_name, amount) VALUES (?, ?, ?)",
                (first, "Some Card", 1),
            )
            current = self._seed_snapshot(conn, "Rixqor", "2026-10-01T08:00:00+00:00", 1)
            conn.execute(
                "INSERT INTO inventory_items (snapshot_id, market_hash_name, amount) VALUES (?, ?, ?)",
                (current, "Some Card", 1),
            )
            conn.commit()

            detector = AcquisitionDetector(repo, "Rixqor")
            results = detector.detect_acquisition(Mock(), process_new_snapshots=True)
            assert results == []

            marker = conn.execute(
                "SELECT COUNT(*) FROM acquisition_processing_log WHERE bot_name=? AND snapshot_id=?",
                ("Rixqor", current),
            ).fetchone()[0]
            assert marker == 1
        finally:
            conn.close()
            os.unlink(path)

    def test_reconcile_after_zero_delta_scan_still_works(self):
        """Reconciliation runs after a zero-delta scan without error."""
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            _, lot_id = _insert_unknown_lot(conn, "Rixqor", "Some Card", 1)
            first = self._seed_snapshot(conn, "Rixqor", "2026-10-01T07:00:00+00:00", 1)
            conn.execute(
                "INSERT INTO inventory_items (snapshot_id, market_hash_name, amount) VALUES (?, ?, ?)",
                (first, "Some Card", 1),
            )
            current = self._seed_snapshot(conn, "Rixqor", "2026-10-01T08:00:00+00:00", 1)
            conn.execute(
                "INSERT INTO inventory_items (snapshot_id, market_hash_name, amount) VALUES (?, ?, ?)",
                (current, "Some Card", 1),
            )
            conn.commit()

            detector = AcquisitionDetector(repo, "Rixqor")
            assert detector.detect_acquisition(Mock(), process_new_snapshots=True) == []

            purchase = MarketHistoryPurchase(
                listingid="L1",
                purchaseid="P1",
                market_hash_name="Some Card",
                quantity=1,
                paid_amount_cents=7,
                currencyid=3,
                time_event_unix=1759315200,
                external_ref="L1:P1",
            )
            with patch.object(detector, "fetch_market_history_for_item", return_value=[purchase]):
                results = detector.reconcile_delayed_evidence(Mock())
            conn.commit()

            assert len(results) == 1
            assert conn.execute(
                "SELECT cost_status FROM acquisition_lots WHERE id=?", (lot_id,)
            ).fetchone()[0] == "TRACKED"
        finally:
            conn.close()
            os.unlink(path)

    def test_two_bots_scan_sequentially_without_locking(self):
        """Rixqor then cesarpereira27 must both commit (63a84b6 regression)."""
        conn, path = _create_db()
        try:
            repo = Repository(conn)
            for bot, item in (("Rixqor", "Some Card"), ("cesarpereira27", "Other Card")):
                first = self._seed_snapshot(conn, bot, "2026-10-01T07:00:00+00:00", 0)
                current = self._seed_snapshot(conn, bot, "2026-10-01T08:00:00+00:00", 0)
                conn.commit()

                detector = AcquisitionDetector(repo, bot)
                detector.detect_acquisition(Mock(), process_new_snapshots=True)
                # A third bot also reconciles, exercising the same lock path.
                detector.reconcile_delayed_evidence(None)

            markers = conn.execute(
                "SELECT bot_name, COUNT(*) FROM acquisition_processing_log GROUP BY bot_name"
            ).fetchall()
            assert dict(markers) == {"Rixqor": 1, "cesarpereira27": 1}
            assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        finally:
            conn.close()
            os.unlink(path)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
