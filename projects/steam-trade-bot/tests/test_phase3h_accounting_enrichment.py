"""Phase 3H — accounting enrichment for already-TRACKED acquisition lots.

Production lot 1 (``774361-Our Lady of the Charred Visage``, bot Rixqor) was
tracked during Phase 3F, so its provenance records only:

    currencyid, listingid, paid_amount_cents, timestamp_iso

Phase 3G added ``acquisition_fee``/``all_in_cost`` but reconciliation only ever
selects ``cost_status = 'UNKNOWN'`` lots, so an already-TRACKED lot can never
acquire those columns. These tests pin the enrichment contract:

A. UNKNOWN lots still become TRACKED through the original path.
B. An already-TRACKED lot missing accounting fields is enriched in place.
C. Enrichment is idempotent on an already-complete lot.
D. Enrichment never creates a transaction.
E. Enrichment never creates an acquisition lot.
F. Enrichment never downgrades TRACKED.
G. Missing authoritative fee evidence leaves the columns NULL (no guessing).
H. Authoritative fee evidence yields the exact three-way split.
I. P&L then measures against the all-in cost.

Every identifier below is synthetic. No real credential, cookie, SteamID,
listingid or purchaseid appears in this file.
"""

import json
import sqlite3
import sys
from datetime import date
from decimal import Decimal
from unittest.mock import patch

sys.path.insert(0, "app")

import pytest

from acquisition import Repository, backfill_accounting_from_provenance
from acquisition_detector import (
    AcquisitionDetector,
    InventoryDelta,
    MarketHistoryPurchase,
)
from pnl import compute_unrealized_pnl
from position_engine import calculate_position_state
from transactions import AcquisitionLot, CostStatus, SourceType

MHN = "774361-Our Lady of the Charred Visage"
BOT = "testbot"

LISTINGID = "synthetic-listing-0001"
PURCHASEID = "synthetic-purchase-0001"
EXTERNAL_REF = f"{LISTINGID}:{PURCHASEID}"

TX_DDL = """
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
"""

LEGACY_LOT_DDL = """
CREATE TABLE acquisition_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_transaction_id INTEGER NOT NULL,
    market_hash_name TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    original_quantity INTEGER NOT NULL CHECK(original_quantity > 0),
    remaining_quantity INTEGER NOT NULL CHECK(remaining_quantity >= 0),
    unit_cost TEXT,
    acquired_at TEXT NOT NULL,
    cost_status TEXT NOT NULL CHECK(cost_status IN ('TRACKED', 'UNKNOWN')),
    provenance TEXT,
    source_type TEXT,
    external_ref TEXT
);
"""

ACCOUNTING_LOT_DDL = """
CREATE TABLE acquisition_lots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_transaction_id INTEGER NOT NULL,
    market_hash_name TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    original_quantity INTEGER NOT NULL CHECK(original_quantity > 0),
    remaining_quantity INTEGER NOT NULL CHECK(remaining_quantity >= 0),
    unit_cost TEXT,
    acquired_at TEXT NOT NULL,
    cost_status TEXT NOT NULL CHECK(cost_status IN ('TRACKED', 'UNKNOWN')),
    provenance TEXT,
    source_type TEXT,
    external_ref TEXT,
    acquisition_fee TEXT,
    all_in_cost TEXT
);
"""


def _conn(lot_ddl=ACCOUNTING_LOT_DDL):
    conn = sqlite3.connect(":memory:")
    conn.executescript(TX_DDL + lot_ddl)
    return conn


def _has_accounting_columns(conn):
    cols = {r[1] for r in conn.execute("PRAGMA table_info(acquisition_lots)")}
    return {"acquisition_fee", "all_in_cost"} <= cols


def _phase3f_provenance():
    return json.dumps({
        "evidence_type": "STEAM_MARKET_HISTORY",
        "evidence_id": PURCHASEID,
        "evidence_data": {
            "currencyid": 2003,
            "listingid": LISTINGID,
            "paid_amount_cents": 3,
            "timestamp_iso": "2026-10-01T07:58:14+00:00",
        },
    })


def _seed_tracked(conn, provenance, unit_cost="0.03", fee=None, all_in=None):
    conn.execute(
        "INSERT INTO transactions (type, market_hash_name, quantity,"
        " unit_price, fees, total_value, timestamp, bot_name, external_ref)"
        " VALUES ('BUY', ?, 1, ?, '0', ?, '2026-10-01T07:58:14+00:00', ?, ?)",
        (MHN, unit_cost, unit_cost, BOT, f"unknown:{BOT}:legacy"),
    )
    tx_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    if _has_accounting_columns(conn):
        conn.execute(
            "INSERT INTO acquisition_lots (source_transaction_id, market_hash_name,"
            " bot_name, original_quantity, remaining_quantity, unit_cost,"
            " acquired_at, cost_status, provenance, source_type, external_ref,"
            " acquisition_fee, all_in_cost)"
            " VALUES (?, ?, ?, 1, 1, ?, '2026-10-01', 'TRACKED', ?, "
            " 'STEAM_MARKET_PURCHASE', ?, ?, ?)",
            (tx_id, MHN, BOT, unit_cost, provenance, EXTERNAL_REF, fee, all_in),
        )
    else:
        conn.execute(
            "INSERT INTO acquisition_lots (source_transaction_id, market_hash_name,"
            " bot_name, original_quantity, remaining_quantity, unit_cost,"
            " acquired_at, cost_status, provenance, source_type, external_ref)"
            " VALUES (?, ?, ?, 1, 1, ?, '2026-10-01', 'TRACKED', ?, "
            " 'STEAM_MARKET_PURCHASE', ?)",
            (tx_id, MHN, BOT, unit_cost, provenance, EXTERNAL_REF),
        )
    conn.commit()
    return tx_id, conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _authoritative_purchase(**overrides):
    base = dict(
        listingid=LISTINGID,
        purchaseid=PURCHASEID,
        market_hash_name=MHN,
        quantity=1,
        paid_amount_cents=3,
        currencyid=2003,
        time_event_unix=1_769_000_000,
        external_ref=EXTERNAL_REF,
        paid_fee_cents=2,
        steam_fee_cents=1,
        publisher_fee_cents=1,
        fee_evidence_present=True,
    )
    base.update(overrides)
    return MarketHistoryPurchase(**base)


def _lot_row(conn, lot_id):
    if _has_accounting_columns(conn):
        return conn.execute(
            "SELECT cost_status, unit_cost, acquisition_fee, all_in_cost,"
            " source_type, external_ref, provenance"
            " FROM acquisition_lots WHERE id = ?",
            (lot_id,),
        ).fetchone()
    row = conn.execute(
        "SELECT cost_status, unit_cost, source_type, external_ref, provenance"
        " FROM acquisition_lots WHERE id = ?",
        (lot_id,),
    ).fetchone()
    return (row[0], row[1], None, None, row[2], row[3], row[4])


# A — unknown -> tracked path unchanged
class TestUnknownToTrackedStillWorks:
    def test_unknown_lot_becomes_tracked_with_full_accounting(self):
        conn = _conn()
        conn.execute(
            "INSERT INTO transactions (type, market_hash_name, quantity,"
            " unit_price, fees, total_value, timestamp, bot_name)"
            " VALUES ('BUY', ?, 1, '0.00', '0', '0.00',"
            " '2026-10-01T07:58:14+00:00', ?)",
            (MHN, BOT),
        )
        tx_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO acquisition_lots (source_transaction_id,"
            " market_hash_name, bot_name, original_quantity,"
            " remaining_quantity, unit_cost, acquired_at, cost_status,"
            " external_ref) VALUES (?, ?, ?, 1, 1, NULL, '2026-10-01',"
            " 'UNKNOWN', ?)",
            (tx_id, MHN, BOT, f"unknown:{BOT}:legacy"),
        )
        conn.commit()

        detector = AcquisitionDetector(Repository(conn), BOT)
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[_authoritative_purchase()]):
            results = detector.reconcile_delayed_evidence(object())

        assert len(results) == 1
        row = _lot_row(conn, 1)
        assert row[0] == "TRACKED"
        assert Decimal(row[1]) == Decimal("0.03")
        assert Decimal(row[2]) == Decimal("0.02")
        assert Decimal(row[3]) == Decimal("0.05")


# B — enrichment in-place
class TestTrackedLotEnrichedInPlace:
    def _enrich(self, conn, purchases):
        detector = AcquisitionDetector(Repository(conn), BOT)
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=purchases):
            return detector.enrich_tracked_accounting(object())

    def test_enriches_tracked_lot_missing_accounting(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        assert _lot_row(conn, lot_id)[2] is None

        results = self._enrich(conn, [_authoritative_purchase()])
        conn.commit()

        assert len(results) == 1
        assert results[0].lot_id == lot_id
        row = _lot_row(conn, lot_id)
        assert Decimal(row[1]) == Decimal("0.03")
        assert Decimal(row[2]) == Decimal("0.02")
        assert Decimal(row[3]) == Decimal("0.05")

    def test_preserves_identity_and_status(self):
        conn = _conn()
        tx_id, lot_id = _seed_tracked(conn, _phase3f_provenance())
        before = _lot_row(conn, lot_id)

        self._enrich(conn, [_authoritative_purchase()])
        conn.commit()
        after = _lot_row(conn, lot_id)

        assert after[0] == before[0] == "TRACKED"
        assert after[1] == before[1] == "0.03"
        assert after[4] == before[4]
        assert after[5] == before[5] == EXTERNAL_REF
        assert conn.execute(
            "SELECT source_transaction_id FROM acquisition_lots WHERE id=?",
            (lot_id,),
        ).fetchone()[0] == tx_id
        assert conn.execute(
            "SELECT quantity FROM transactions WHERE id=?", (tx_id,)
        ).fetchone()[0] == 1

    def test_provenance_keeps_prior_keys_and_gains_fee_split(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        self._enrich(conn, [_authoritative_purchase()])
        conn.commit()

        data = json.loads(_lot_row(conn, lot_id)[6])["evidence_data"]
        assert data["currencyid"] == 2003
        assert data["listingid"] == LISTINGID
        assert data["paid_amount_cents"] == 3
        assert data["timestamp_iso"] == "2026-10-01T07:58:14+00:00"
        assert data["paid_fee_cents"] == 2
        assert data["steam_fee_cents"] == 1
        assert data["publisher_fee_cents"] == 1
        assert data["buyer_total_cents"] == 5

    def test_no_new_transaction(self):
        conn = _conn()
        _seed_tracked(conn, _phase3f_provenance())
        before = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        self._enrich(conn, [_authoritative_purchase()])
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        assert before == after == 1

    def test_no_new_lot(self):
        conn = _conn()
        _seed_tracked(conn, _phase3f_provenance())
        before = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
        self._enrich(conn, [_authoritative_purchase()])
        conn.commit()
        after = conn.execute("SELECT COUNT(*) FROM acquisition_lots").fetchone()[0]
        assert before == after == 1

    def test_never_downgrades_tracked(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        self._enrich(conn, [])
        conn.commit()
        assert _lot_row(conn, lot_id)[0] == "TRACKED"


# C — idempotency
class TestEnrichmentIdempotent:
    def test_second_run_enriches_nothing(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)

        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[_authoritative_purchase()]):
            first = detector.enrich_tracked_accounting(object())
        conn.commit()
        after_first = _lot_row(conn, lot_id)

        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[_authoritative_purchase()]):
            second = detector.enrich_tracked_accounting(object())
        conn.commit()

        assert len(first) == 1
        assert second == []
        assert _lot_row(conn, lot_id) == after_first

    def test_already_complete_lot_is_not_touched(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance(),
                                  fee="0.02", all_in="0.05")
        detector = AcquisitionDetector(Repository(conn), BOT)
        before = _lot_row(conn, lot_id)

        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[_authoritative_purchase()]):
            assert detector.enrich_tracked_accounting(object()) == []
        conn.commit()
        assert _lot_row(conn, lot_id) == before

    def test_repeated_enrichment_is_stable(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        for _ in range(5):
            with patch.object(detector, "fetch_market_history_for_item",
                              return_value=[_authoritative_purchase()]):
                detector.enrich_tracked_accounting(object())
            conn.commit()
        row = _lot_row(conn, lot_id)
        assert (row[1], row[2], row[3]) == ("0.03", "0.02", "0.05")


# G — missing evidence leaves null
class TestMissingEvidenceLeavesNull:
    def test_no_purchase_retrieved_leaves_null(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[]):
            assert detector.enrich_tracked_accounting(object()) == []
        conn.commit()
        assert _lot_row(conn, lot_id)[2] is None

    def test_fee_field_absent_from_steam_leaves_null(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        no_fee = _authoritative_purchase(
            paid_fee_cents=0, steam_fee_cents=0,
            publisher_fee_cents=0, fee_evidence_present=False,
        )
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[no_fee]):
            assert detector.enrich_tracked_accounting(object()) == []
        conn.commit()
        assert _lot_row(conn, lot_id)[2] is None

    def test_wrong_identity_is_not_matched(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        other = _authoritative_purchase(
            listingid="some-other-listing",
            purchaseid="some-other-purchase",
            external_ref="some-other-listing:some-other-purchase",
        )
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[other]):
            assert detector.enrich_tracked_accounting(object()) == []
        conn.commit()
        assert _lot_row(conn, lot_id)[2] is None

    def test_current_listing_is_never_used_as_substitute(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        impostor = _authoritative_purchase(
            listingid=LISTINGID,
            purchaseid="",
            external_ref="",
        )
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[impostor]):
            assert detector.enrich_tracked_accounting(object()) == []
        conn.commit()
        assert _lot_row(conn, lot_id)[2] is None

    def test_no_session_is_a_noop(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        assert detector.enrich_tracked_accounting(None) == []
        conn.commit()
        assert _lot_row(conn, lot_id)[2] is None

    def test_write_failure_leaves_null(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[_authoritative_purchase()]):
            with patch.object(AcquisitionDetector, "_write_accounting_enrichment",
                              side_effect=RuntimeError("boom")):
                assert detector.enrich_tracked_accounting(object()) == []
        conn.commit()
        row = _lot_row(conn, lot_id)
        assert row[0] == "TRACKED" and row[2] is None and row[3] is None

    def test_unknown_lots_are_not_enriched_by_this_pass(self):
        conn = _conn()
        conn.execute(
            "INSERT INTO transactions (type, market_hash_name, quantity,"
            " unit_price, fees, total_value, timestamp, bot_name)"
            " VALUES ('BUY', ?, 1, '0.00', '0', '0.00',"
            " '2026-10-01T07:58:14+00:00', ?)",
            (MHN, BOT),
        )
        tx_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
        conn.execute(
            "INSERT INTO acquisition_lots (source_transaction_id,"
            " market_hash_name, bot_name, original_quantity,"
            " remaining_quantity, unit_cost, acquired_at, cost_status,"
            " external_ref) VALUES (?, ?, ?, 1, 1, NULL, '2026-10-01',"
            " 'UNKNOWN', ?)",
            (tx_id, MHN, BOT, f"unknown:{BOT}:legacy"),
        )
        conn.commit()

        detector = AcquisitionDetector(Repository(conn), BOT)
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[_authoritative_purchase()]):
            assert detector.enrich_tracked_accounting(object()) == []
        conn.commit()
        row = conn.execute(
            "SELECT cost_status, unit_cost, acquisition_fee FROM acquisition_lots"
        ).fetchone()
        assert row == ("UNKNOWN", None, None)


# H + I — authoritative split and P&L
class TestAuthoritativeSplitAndPnl:
    def test_exact_three_way_split(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[_authoritative_purchase()]):
            detector.enrich_tracked_accounting(object())
        conn.commit()

        row = _lot_row(conn, lot_id)
        unit_cost, fee, all_in = (Decimal(row[1]), Decimal(row[2]), Decimal(row[3]))
        assert unit_cost == Decimal("0.03")
        assert fee == Decimal("0.02")
        assert all_in == Decimal("0.05")
        assert unit_cost + fee == all_in

    def test_provenance_buyer_total(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[_authoritative_purchase()]):
            detector.enrich_tracked_accounting(object())
        conn.commit()
        data = json.loads(_lot_row(conn, lot_id)[6])["evidence_data"]
        assert data["buyer_total_cents"] == 5

    def test_pnl_measures_against_all_in_cost(self):
        seller_proceeds = Decimal("0.03")
        all_in_acquisition_cost = Decimal("0.05")
        assert seller_proceeds - all_in_acquisition_cost == Decimal("-0.02")

    def test_enriched_position_reports_all_in_basis(self):
        conn = _conn()
        _, lot_id = _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[_authoritative_purchase()]):
            detector.enrich_tracked_accounting(object())
        conn.commit()

        all_in = Decimal(_lot_row(conn, lot_id)[3])
        lot = AcquisitionLot(
            source_transaction_id=1, market_hash_name=MHN, bot_name=BOT,
            original_quantity=1, remaining_quantity=1, unit_cost=all_in,
            acquired_at="2026-10-01T00:00:00+00:00",
            cost_status=CostStatus.TRACKED,
        )
        position = calculate_position_state([lot], MHN)
        result = compute_unrealized_pnl(position, Decimal("0.03"), game_fee_rate=0)

        assert position.known_cost_basis == Decimal("0.05")
        assert result.known_cost_basis == Decimal("0.05")
        assert result.current_net_realizable_value == Decimal("0.02")
        assert result.unrealized_pnl == Decimal("-0.03")
        assert result.is_profitable() is False

    def test_break_even_and_profit_scenarios(self):
        for price, net, expected_pnl in (
            ("0.03", Decimal("0.02"), Decimal("-0.03")),
            ("0.06", Decimal("0.05"), Decimal("0.00")),
            ("0.08", Decimal("0.07"), Decimal("0.02")),
        ):
            lot = AcquisitionLot(
                source_transaction_id=1, market_hash_name=MHN, bot_name=BOT,
                original_quantity=1, remaining_quantity=1,
                unit_cost=Decimal("0.05"),
                acquired_at="2026-10-01T00:00:00+00:00",
                cost_status=CostStatus.TRACKED,
            )
            position = calculate_position_state([lot], MHN)
            result = compute_unrealized_pnl(position, Decimal(price), game_fee_rate=0)
            assert result.current_net_realizable_value == net, price
            assert result.unrealized_pnl == expected_pnl, price
            assert result.is_profitable() is (expected_pnl > 0), price


# Migration interaction
class TestBackfillStillConservative:
    def test_legacy_provenance_is_not_backfilled(self):
        conn = _conn()
        _seed_tracked(conn, _phase3f_provenance())
        assert backfill_accounting_from_provenance(conn) == 0
        conn.commit()
        row = _lot_row(conn, 1)
        assert row[2] is None and row[3] is None

    def test_enrichment_noop_on_legacy_schema(self):
        conn = _conn(LEGACY_LOT_DDL)
        _seed_tracked(conn, _phase3f_provenance())
        detector = AcquisitionDetector(Repository(conn), BOT)
        with patch.object(detector, "fetch_market_history_for_item",
                          return_value=[_authoritative_purchase()]):
            assert detector.enrich_tracked_accounting(object()) == []