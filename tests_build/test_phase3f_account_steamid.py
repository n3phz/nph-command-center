#!/usr/bin/env python3
"""Phase 3F — account SteamID attribution for Market History classification.

Root cause this covers: `fetch_market_history_for_item()` passed
`account_steamid=""` to `adapt_response()`. The BUY classifier requires
actor == purchaser == account_steamid AND a non-empty account_steamid, so
every genuine purchase was classified UNKNOWN and then dropped by the
`event_type != "BUY"` filter. Live Steam data was present the whole time.

All identifiers below are SYNTHETIC. No real account id, purchaseid,
listingid or cookie value appears in this file.
"""

import json
import os
import sqlite3
import sys
import tempfile
from datetime import date
from unittest.mock import patch

sys.path.insert(0, "app")

import pytest

from acquisition import Repository
from acquisition_detector import AcquisitionDetector

SYNTH_STEAMID = "76561198000000001"
OTHER_STEAMID = "76561198000000002"
SYNTH_LISTING = "111111111111111111"
SYNTH_PURCHASE = "222222222222222222"
SYNTH_MHN = "9999-Synthetic Test Card"
BOT = "TestBot"


def _schema(conn):
    conn.executescript(
        """
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            type TEXT NOT NULL, market_hash_name TEXT NOT NULL,
            quantity INTEGER NOT NULL, unit_price TEXT NOT NULL,
            fees TEXT NOT NULL DEFAULT '0',
            total_value TEXT NOT NULL DEFAULT '0',
            timestamp TEXT NOT NULL, bot_name TEXT NOT NULL,
            external_ref TEXT);
        CREATE TABLE acquisition_lots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_transaction_id INTEGER NOT NULL,
            market_hash_name TEXT NOT NULL, bot_name TEXT NOT NULL,
            original_quantity INTEGER NOT NULL,
            remaining_quantity INTEGER NOT NULL, unit_cost TEXT,
            acquired_at TEXT NOT NULL, cost_status TEXT NOT NULL,
            provenance TEXT, source_type TEXT, external_ref TEXT);
        CREATE TABLE inventory_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT NOT NULL, captured_at TEXT NOT NULL,
            item_count INTEGER NOT NULL);
        CREATE TABLE inventory_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL,
            market_hash_name TEXT NOT NULL, amount INTEGER NOT NULL);
        CREATE TABLE acquisition_processing_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            bot_name TEXT NOT NULL, snapshot_id INTEGER NOT NULL,
            processed_at TEXT NOT NULL,
            UNIQUE(bot_name, snapshot_id));
        """
    )
    conn.commit()


def _db():
    path = tempfile.mktemp(suffix=".db")
    conn = sqlite3.connect(path)
    _schema(conn)
    return conn, path


def _unknown_lot(conn):
    cur = conn.execute(
        "INSERT INTO transactions (type,market_hash_name,quantity,unit_price,"
        "fees,total_value,timestamp,bot_name,external_ref) "
        "VALUES ('BUY',?,1,'0','0','0','2026-10-01',?,?)",
        (SYNTH_MHN, BOT, "unknown:%s:x" % BOT),
    )
    tx = cur.lastrowid
    cur = conn.execute(
        "INSERT INTO acquisition_lots (source_transaction_id,market_hash_name,"
        "bot_name,original_quantity,remaining_quantity,unit_cost,acquired_at,"
        "cost_status) VALUES (?,?,?,1,1,NULL,'2026-10-01','UNKNOWN')",
        (tx, SYNTH_MHN, BOT),
    )
    conn.commit()
    return tx, cur.lastrowid


def _load_fixture():
    """Load the sanitized live-shape fixture."""
    path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "fixtures",
        "mh_purchase_sanitized.json",
    )
    with open(path) as fh:
        return json.load(fh)


def _steam_response(actor=SYNTH_STEAMID, purchaser=SYNTH_STEAMID):
    """Synthetic payload derived from a sanitized capture of the live response.

    Field names, value types and the `purchases` map key
    ("<listingid>_<purchaseid>") all mirror live Steam exactly. Every
    identifier is synthetic; see tests/fixtures/mh_purchase_sanitized.json.
    """
    payload = _load_fixture()
    # Re-key purchases/listings so caller-supplied ids stay authoritative.
    purchases = payload.get("purchases", {})
    new_purchases = {}
    for value in purchases.values():
        value = dict(value)
        value["listingid"] = SYNTH_LISTING
        value["purchaseid"] = SYNTH_PURCHASE
        value["steamid_purchaser"] = purchaser
        new_purchases["%s_%s" % (SYNTH_LISTING, SYNTH_PURCHASE)] = value
    payload["purchases"] = new_purchases

    new_listings = {}
    for value in payload.get("listings", {}).values():
        value = dict(value)
        value["listingid"] = SYNTH_LISTING
        new_listings[SYNTH_LISTING] = value
    payload["listings"] = new_listings

    events = []
    for value in payload.get("events", []):
        value = dict(value)
        value["listingid"] = SYNTH_LISTING
        value["purchaseid"] = SYNTH_PURCHASE
        value["steamid_actor"] = actor
        events.append(value)
    payload["events"] = events
    return payload


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, payload):
        self._payload = payload
        self.calls = 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return _FakeResp(self._payload)


class TestAccountSteamIDAttribution:
    def test_empty_account_steamid_yields_no_purchases(self):
        """Regression guard: empty SteamID must not attribute a BUY."""
        conn, path = _db()
        try:
            det = AcquisitionDetector(Repository(conn), BOT, account_steamid="")
            session = _FakeSession(_steam_response())
            result = det.fetch_market_history_for_item(
                SYNTH_MHN, date(2026, 10, 1), session
            )
            assert result == []
        finally:
            conn.close()
            os.unlink(path)

    def test_matching_account_steamid_yields_purchase(self):
        """The fix: real owner SteamID attributes the BUY."""
        conn, path = _db()
        try:
            det = AcquisitionDetector(
                Repository(conn), BOT, account_steamid=SYNTH_STEAMID
            )
            session = _FakeSession(_steam_response())
            result = det.fetch_market_history_for_item(
                SYNTH_MHN, date(2026, 10, 1), session
            )
            assert len(result) == 1
            p = result[0]
            assert p.listingid == SYNTH_LISTING
            assert p.purchaseid == SYNTH_PURCHASE
            assert p.market_hash_name == SYNTH_MHN
            assert p.quantity == 1
            assert p.paid_amount_cents == 3
            assert p.external_ref == "%s:%s" % (SYNTH_LISTING, SYNTH_PURCHASE)
        finally:
            conn.close()
            os.unlink(path)

    def test_default_construction_is_backward_compatible(self):
        """Omitting the SteamID must not raise and must stay UNKNOWN-safe."""
        conn, path = _db()
        try:
            det = AcquisitionDetector(Repository(conn), BOT)
            assert det.account_steamid == ""
            session = _FakeSession(_steam_response())
            assert det.fetch_market_history_for_item(
                SYNTH_MHN, date(2026, 10, 1), session
            ) == []
        finally:
            conn.close()
            os.unlink(path)

    def test_wrong_account_steamid_does_not_attribute(self):
        """A different account's ID must not claim this purchase."""
        conn, path = _db()
        try:
            det = AcquisitionDetector(
                Repository(conn), BOT, account_steamid=OTHER_STEAMID
            )
            session = _FakeSession(_steam_response())
            assert det.fetch_market_history_for_item(
                SYNTH_MHN, date(2026, 10, 1), session
            ) == []
        finally:
            conn.close()
            os.unlink(path)

    def test_purchaser_mismatch_does_not_attribute(self):
        """Seller-side event (purchaser != actor) stays unattributed."""
        conn, path = _db()
        try:
            det = AcquisitionDetector(
                Repository(conn), BOT, account_steamid=SYNTH_STEAMID
            )
            session = _FakeSession(
                _steam_response(actor=SYNTH_STEAMID, purchaser=OTHER_STEAMID)
            )
            assert det.fetch_market_history_for_item(
                SYNTH_MHN, date(2026, 10, 1), session
            ) == []
        finally:
            conn.close()
            os.unlink(path)


class TestReconciliationEndToEnd:
    def test_unknown_lot_reconciles_with_steamid(self):
        """Full path: UNKNOWN lot -> TRACKED once the SteamID is supplied."""
        conn, path = _db()
        try:
            _unknown_lot(conn)
            det = AcquisitionDetector(
                Repository(conn), BOT, account_steamid=SYNTH_STEAMID
            )
            session = _FakeSession(_steam_response())
            results = det.reconcile_delayed_evidence(session)
            conn.commit()

            assert len(results) == 1
            row = conn.execute(
                "SELECT cost_status, unit_cost, provenance FROM acquisition_lots"
            ).fetchone()
            assert row[0] == "TRACKED"
            assert row[1] is not None
            assert row[2] is not None
            # exactly one economic position
            assert conn.execute(
                "SELECT COUNT(*) FROM acquisition_lots"
            ).fetchone()[0] == 1
            assert conn.execute(
                "SELECT COUNT(*) FROM transactions"
            ).fetchone()[0] == 1
        finally:
            conn.close()
            os.unlink(path)

    def test_unknown_lot_stays_unknown_without_steamid(self):
        """Without the SteamID the lot must remain UNKNOWN, not be forced."""
        conn, path = _db()
        try:
            _, lot_id = _unknown_lot(conn)
            det = AcquisitionDetector(Repository(conn), BOT, account_steamid="")
            session = _FakeSession(_steam_response())
            assert det.reconcile_delayed_evidence(session) == []
            conn.commit()
            row = conn.execute(
                "SELECT cost_status FROM acquisition_lots WHERE id=?", (lot_id,)
            ).fetchone()
            assert row[0] == "UNKNOWN"
        finally:
            conn.close()
            os.unlink(path)


class TestParseBotSteamids:
    def test_parses_well_formed_mapping(self):
        import main

        parsed = main._parse_bot_steamids(
            "Rixqor=76561198000000001,bot2=76561198000000002"
        )
        assert parsed == {
            "Rixqor": "76561198000000001",
            "bot2": "76561198000000002",
        }

    def test_malformed_entries_are_ignored(self):
        import main

        assert main._parse_bot_steamids("") == {}
        assert main._parse_bot_steamids("garbage") == {}
        assert main._parse_bot_steamids("=76561198000000001") == {}
        assert main._parse_bot_steamids("name=") == {}

    def test_partial_mapping_keeps_valid_entries(self):
        import main

        parsed = main._parse_bot_steamids(
            "Good=76561198000000001,bad,Other=76561198000000002"
        )
        assert parsed == {
            "Good": "76561198000000001",
            "Other": "76561198000000002",
        }


if __name__ == "__main__":
    pytest.main([__file__, "-v"])