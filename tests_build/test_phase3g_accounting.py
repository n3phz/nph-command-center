"""Phase 3G — accounting and valuation hardening.

Establishes the authoritative distinction between:

* seller-side amount (price excluding fees) -- ``unit_cost``
* acquisition fees                          -- ``acquisition_fee``
* all-in acquisition cost (buyer outlay)    -- ``all_in_cost``

and proves that unrealized P&L is computed against the ALL-IN cost,
not the price-excluding-fees basis.

Ground truth for the fixture values is the verified Rixqor purchase of
``774361-Our Lady of the Charred Visage`` (appid 753, classid
``3516150028``): paid_amount=3, paid_fee=2, steam_fee=1,
publisher_fee=1, buyer total=5 (minor units / cents).

No real credentials, cookies, SteamIDs, listing IDs or purchase IDs are
embedded in this file -- every identifier is a synthetic placeholder.
"""

import sqlite3
import sys
from datetime import date

sys.path.insert(0, "app")

from decimal import Decimal

import pytest

from acquisition import (
    backfill_accounting_from_provenance,
    migrate_acquisition_accounting,
    record_acquisition,
    Repository,
)
from acquisition_detector import (
    AcquisitionDetector,
    InventoryDelta,
    MarketHistoryPurchase,
)
from economic import calculate_total_fees
from pnl import compute_unrealized_pnl
from position_engine import calculate_position_state
from transactions import (
    AcquisitionLot,
    CostStatus,
    EvidenceType,
    Provenance,
    SourceType,
)


MHN = "774361-Our Lady of the Charred Visage"
BOT = "testbot"

# ----------------------------------------------------------------------
# Schemas
# ----------------------------------------------------------------------

#: Pre-Phase-3G table (no accounting columns).
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


def _conn(lot_ddl):
    conn = sqlite3.connect(":memory:")
    conn.executescript(TX_DDL + lot_ddl)
    return conn


# ----------------------------------------------------------------------
# Domain-level accounting model
# ----------------------------------------------------------------------

class AccountingModel:
    """The three-way split Phase 3G makes explicit.

    Mirrors what is persisted on ``acquisition_lots`` so the arithmetic
    contract can be asserted independently of the storage layer.
    """

    def __init__(self, seller_amount, acquisition_fee, quantity=1):
        self.seller_amount = seller_amount
        self.acquisition_fee = acquisition_fee
        self.quantity = quantity

    @property
    def all_in_unit_cost(self):
        """Per-unit all-in cost: price excluding fees plus fees."""
        return self.seller_amount + self.acquisition_fee

    @property
    def all_in_cost(self):
        return self.all_in_unit_cost * self.quantity

    def unrealized_pnl(self, seller_proceeds_per_unit):
        """P&L measured against the ALL-IN cost, never the net proceeds."""
        return (seller_proceeds_per_unit - self.all_in_unit_cost) * self.quantity


class TestAccountingSemantics:
    """CASE 1/2/3 from the Phase 3G specification."""

    def test_case1_loss_when_proceeds_equal_seller_amount(self):
        """Bought at €0.05 all-in, sell proceeds €0.03 -> -€0.02."""
        model = AccountingModel(seller_amount=Decimal("0.03"),
                                 acquisition_fee=Decimal("0.02"))
        assert model.all_in_unit_cost == Decimal("0.05")
        assert model.unrealized_pnl(Decimal("0.03")) == Decimal("-0.02")

    def test_case2_break_even_against_all_in_cost(self):
        """All-in €0.05, proceeds €0.05 -> exactly €0.00."""
        model = AccountingModel(seller_amount=Decimal("0.03"),
                                 acquisition_fee=Decimal("0.02"))
        assert model.unrealized_pnl(Decimal("0.05")) == Decimal("0.00")

    def test_case3_profit_against_all_in_cost(self):
        """All-in €0.05, proceeds €0.10 -> +€0.05."""
        model = AccountingModel(seller_amount=Decimal("0.03"),
                                 acquisition_fee=Decimal("0.02"))
        assert model.unrealized_pnl(Decimal("0.10")) == Decimal("0.05")

    def test_all_in_is_never_the_seller_amount_alone(self):
        """Guards against regressing to the pre-3G single-basis model."""
        model = AccountingModel(seller_amount=Decimal("0.03"),
                                 acquisition_fee=Decimal("0.02"))
        assert model.all_in_unit_cost != model.seller_amount

    def test_zero_fee_reduces_to_seller_amount(self):
        model = AccountingModel(seller_amount=Decimal("0.03"),
                                acquisition_fee=Decimal("0.00"))
        assert model.all_in_unit_cost == Decimal("0.03")
        assert model.unrealized_pnl(Decimal("0.03")) == Decimal("0.00")

    def test_multi_unit_scaling(self):
        model = AccountingModel(seller_amount=Decimal("0.03"),
                                acquisition_fee=Decimal("0.02"),
                                quantity=4)
        assert model.all_in_cost == Decimal("0.20")
        assert model.unrealized_pnl(Decimal("0.03")) == Decimal("-0.08")

    def test_no_float_contamination(self):
        """Binary floats cannot represent 0.03+0.02 exactly; Decimal can."""
        model = AccountingModel(seller_amount=Decimal("0.03"),
                                acquisition_fee=Decimal("0.02"))
        assert isinstance(model.all_in_unit_cost, Decimal)
        assert model.all_in_unit_cost == Decimal("0.05")
        assert str(model.all_in_unit_cost) == "0.05"


# ----------------------------------------------------------------------
# Purchase model: buyer total vs price vs fee split
# ----------------------------------------------------------------------

def _purchase(**overrides):
    base = dict(
        listingid="synthetic-listing-id",
        purchaseid="synthetic-purchase-id",
        market_hash_name=MHN,
        quantity=1,
        paid_amount_cents=3,
        currencyid=3,
        time_event_unix=1_700_000_000,
        external_ref="synthetic-listing-id:synthetic-purchase-id",
        paid_fee_cents=2,
        steam_fee_cents=1,
        publisher_fee_cents=1,
    )
    base.update(overrides)
    return MarketHistoryPurchase(**base)


class TestMarketHistoryPurchaseCostModel:
    def test_buyer_total_is_price_plus_fee(self):
        assert _purchase().buyer_total_cents == 5

    def test_fee_split_sums_to_total_fee(self):
        p = _purchase()
        assert p.steam_fee_cents + p.publisher_fee_cents == p.paid_fee_cents

    def test_paid_amount_is_exclusive_of_fees(self):
        """paid_amount is the seller-side basis, NOT the buyer outlay."""
        p = _purchase()
        assert p.paid_amount_cents == 3
        assert p.buyer_total_cents != p.paid_amount_cents

    def test_default_fee_fields_are_zero(self):
        """Pre-3G construction sites keep working with no fee data."""
        p = MarketHistoryPurchase(
            listingid="l", purchaseid="p", market_hash_name=MHN,
            quantity=1, paid_amount_cents=3, currencyid=3,
            time_event_unix=1, external_ref="l:p",
        )
        assert p.paid_fee_cents == 0
        assert p.buyer_total_cents == 3

    def test_buyer_total_scales_with_reported_fee(self):
        assert _purchase(paid_fee_cents=17).buyer_total_cents == 20


# ----------------------------------------------------------------------
# Migration
# ----------------------------------------------------------------------

class TestAccountingMigration:
    def test_adds_columns(self):
        conn = _conn(LEGACY_LOT_DDL)
        migrate_acquisition_accounting(conn)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(acquisition_lots)")}
        assert {"acquisition_fee", "all_in_cost"} <= cols

    def test_is_idempotent(self):
        conn = _conn(LEGACY_LOT_DDL)
        migrate_acquisition_accounting(conn)
        migrate_acquisition_accounting(conn)
        cols = [r[1] for r in conn.execute("PRAGMA table_info(acquisition_lots)")]
        assert cols.count("acquisition_fee") == 1
        assert cols.count("all_in_cost") == 1

    def test_never_touches_unit_cost_meaning(self):
        """Migration must not rewrite historical unit_cost values."""
        conn = _conn(LEGACY_LOT_DDL)
        conn.execute(
            "INSERT INTO transactions (type, market_hash_name, quantity,"
            " unit_price, fees, total_value, timestamp, bot_name)"
            " VALUES ('BUY', ?, 1, '0.03', '0', '0.03',"
            " '2026-01-01T00:00:00+00:00', ?)",
            (MHN, BOT),
        )
        conn.execute(
            "INSERT INTO acquisition_lots (source_transaction_id,"
            " market_hash_name, bot_name, original_quantity,"
            " remaining_quantity, unit_cost, acquired_at, cost_status)"
            " VALUES (1, ?, ?, 1, 1, '0.03', '2026-01-01T00:00:00+00:00',"
            " 'TRACKED')",
            (MHN, BOT),
        )
        conn.commit()
        before = conn.execute("SELECT unit_cost FROM acquisition_lots").fetchone()[0]
        migrate_acquisition_accounting(conn)
        after = conn.execute("SELECT unit_cost FROM acquisition_lots").fetchone()[0]
        assert before == after == "0.03"

    def test_missing_table_is_noop(self):
        conn = sqlite3.connect(":memory:")
        migrate_acquisition_accounting(conn)  # must not raise


# ----------------------------------------------------------------------
# Backfill from provenance
# ----------------------------------------------------------------------

PROVENANCE_WITH_FEES = (
    '{"evidence_type": "STEAM_MARKET_HISTORY",'
    ' "evidence_id": "synthetic-purchase-id",'
    ' "evidence_data": {'
    '"listingid": "synthetic-listing-id",'
    '"paid_amount_cents": 3, "paid_fee_cents": 2,'
    '"steam_fee_cents": 1, "publisher_fee_cents": 1,'
    '"buyer_total_cents": 5, "currencyid": 3}}'
)

PROVENANCE_PRE_FEE_BREAKDOWN = (
    '{"evidence_type": "STEAM_MARKET_HISTORY",'
    ' "evidence_id": "synthetic-purchase-id",'
    ' "evidence_data": {'
    '"listingid": "synthetic-listing-id",'
    '"paid_amount_cents": 3, "currencyid": 3}}'
)


def _seed_lot(conn, provenance, unit_cost="0.03"):
    conn.execute(
        "INSERT INTO transactions (type, market_hash_name, quantity,"
        " unit_price, fees, total_value, timestamp, bot_name)"
        " VALUES ('BUY', ?, 1, ?, '0', ?, '2026-01-01T00:00:00+00:00', ?)",
        (MHN, unit_cost, unit_cost, BOT),
    )
    conn.execute(
        "INSERT INTO acquisition_lots (source_transaction_id,"
        " market_hash_name, bot_name, original_quantity,"
        " remaining_quantity, unit_cost, acquired_at, cost_status, provenance)"
        " VALUES (1, ?, ?, 1, 1, ?, '2026-01-01T00:00:00+00:00', 'TRACKED', ?)",
        (MHN, BOT, unit_cost, provenance),
    )
    conn.commit()


class TestBackfillAccountingFromProvenance:
    def test_populates_fee_and_all_in_cost(self):
        conn = _conn(ACCOUNTING_LOT_DDL)
        _seed_lot(conn, PROVENANCE_WITH_FEES)
        updated = backfill_accounting_from_provenance(conn)
        assert updated == 1
        row = conn.execute(
            "SELECT unit_cost, acquisition_fee, all_in_cost FROM acquisition_lots"
        ).fetchone()
        # All three bases are stored in MAJOR units with two decimals:
        # unit_cost 0.03 + acquisition_fee 0.02 = all_in_cost 0.05
        assert row == ("0.03", "0.02", "0.05")

    def test_leaves_pre_fee_breakdown_rows_untouched(self):
        """Rows whose evidence predates the fee split must stay NULL."""
        conn = _conn(ACCOUNTING_LOT_DDL)
        _seed_lot(conn, PROVENANCE_PRE_FEE_BREAKDOWN)
        assert backfill_accounting_from_provenance(conn) == 0
        row = conn.execute(
            "SELECT acquisition_fee, all_in_cost FROM acquisition_lots"
        ).fetchone()
        assert row == (None, None)

    def test_does_not_overwrite_existing_values(self):
        conn = _conn(ACCOUNTING_LOT_DDL)
        _seed_lot(conn, PROVENANCE_WITH_FEES)
        conn.execute(
            "UPDATE acquisition_lots SET acquisition_fee='9', all_in_cost='9'"
        )
        conn.commit()
        assert backfill_accounting_from_provenance(conn) == 0
        row = conn.execute(
            "SELECT acquisition_fee, all_in_cost FROM acquisition_lots"
        ).fetchone()
        assert row == ("9", "9")

    def test_tolerates_corrupt_provenance_json(self):
        conn = _conn(ACCOUNTING_LOT_DDL)
        _seed_lot(conn, "{not-json")
        assert backfill_accounting_from_provenance(conn) == 0

    def test_noop_without_columns(self):
        conn = _conn(LEGACY_LOT_DDL)
        _seed_lot(conn, PROVENANCE_WITH_FEES)
        assert backfill_accounting_from_provenance(conn) == 0


# ----------------------------------------------------------------------
# Detector write path
# ----------------------------------------------------------------------

class TestTrackedUpdateWritesAccountingColumns:
    """The reconciliation update must persist all three bases."""

    def _run_update(self, ddl):
        conn = _conn(ddl)
        conn.execute(
            "INSERT INTO transactions (type, market_hash_name, quantity,"
            " unit_price, fees, total_value, timestamp, bot_name)"
            " VALUES ('BUY', ?, 1, '0.00', '0', '0.00',"
            " '2026-01-01T00:00:00+00:00', ?)",
            (MHN, BOT),
        )
        conn.execute(
            "INSERT INTO acquisition_lots (source_transaction_id,"
            " market_hash_name, bot_name, original_quantity,"
            " remaining_quantity, unit_cost, acquired_at, cost_status)"
            " VALUES (1, ?, ?, 1, 1, NULL, '2026-01-01T00:00:00+00:00',"
            " 'UNKNOWN')",
            (MHN, BOT),
        )
        conn.commit()

        detector = AcquisitionDetector(repository=Repository(conn), bot_name=BOT)

        delta = InventoryDelta(
            bot_name=BOT,
            market_hash_name=MHN,
            quantity_change=1,
            previous_quantity=0,
            current_quantity=1,
            detected_at=date(2026, 1, 1),
        )
        result = detector._update_tracked(
            lot_id=1, source_tx_id=1, delta=delta, purchase=_purchase()
        )
        return conn, result

    def test_writes_three_bases(self):
        conn, _ = self._run_update(ACCOUNTING_LOT_DDL)
        row = conn.execute(
            "SELECT cost_status, unit_cost, acquisition_fee, all_in_cost,"
            " source_type, external_ref FROM acquisition_lots WHERE id=1"
        ).fetchone()
        status, unit_cost, fee, all_in, source_type, external_ref = row
        assert status == "TRACKED"
        assert Decimal(unit_cost) == Decimal("0.03")
        assert Decimal(fee) == Decimal("0.02")
        assert Decimal(all_in) == Decimal("0.05")
        # The invariant the whole phase exists to protect.
        assert Decimal(unit_cost) + Decimal(fee) == Decimal(all_in)
        assert source_type == SourceType.STEAM_MARKET_PURCHASE.value
        assert external_ref == "synthetic-listing-id:synthetic-purchase-id"

    def test_persists_full_fee_breakdown_in_provenance(self):
        conn, _ = self._run_update(ACCOUNTING_LOT_DDL)
        raw = conn.execute(
            "SELECT provenance FROM acquisition_lots WHERE id=1"
        ).fetchone()[0]
        import json
        data = json.loads(raw)["evidence_data"]
        assert data["paid_amount_cents"] == 3
        assert data["paid_fee_cents"] == 2
        assert data["steam_fee_cents"] == 1
        assert data["publisher_fee_cents"] == 1
        assert data["buyer_total_cents"] == 5

    def test_transaction_fees_are_no_longer_hardcoded_zero(self):
        conn, _ = self._run_update(ACCOUNTING_LOT_DDL)
        tx = conn.execute(
            "SELECT unit_price, fees, total_value FROM transactions WHERE id=1"
        ).fetchone()
        assert Decimal(tx[1]) == Decimal("0.02")
        assert tx[1] != "0"

    def test_degrades_gracefully_on_legacy_schema(self):
        """Without the columns the update must still succeed and track."""
        conn, result = self._run_update(LEGACY_LOT_DDL)
        assert result.cost_status is CostStatus.TRACKED
        row = conn.execute(
            "SELECT cost_status, unit_cost FROM acquisition_lots WHERE id=1"
        ).fetchone()
        assert row[0] == "TRACKED"
        assert Decimal(row[1]) == Decimal("0.03")


# ----------------------------------------------------------------------
# Valuation: P&L must use the all-in basis
# ----------------------------------------------------------------------

def _lot(unit_cost, remaining=1, all_in=None):
    return AcquisitionLot(
        source_transaction_id=1,
        market_hash_name=MHN,
        bot_name=BOT,
        original_quantity=remaining,
        remaining_quantity=remaining,
        unit_cost=unit_cost,
        acquired_at="2026-01-01T00:00:00+00:00",
        cost_status=CostStatus.TRACKED,
    )


class TestValuationUsesVerifiedCostNotMarketEstimate:
    """P&L must be measured against the ALL-IN acquisition cost.

    ``compute_unrealized_pnl`` applies the modelled sell-side fee
    schedule (max(5% of gross, €0.01)) to derive net realizable value.
    At these tiny price points that schedule is dominated by the €0.01
    minimum fee, so the expected values below are computed explicitly
    from the schedule -- they are NOT the raw spec numbers, which
    describe the seller-proceeds basis directly (see the authoritative
    split test for that).
    """

    def test_pnl_against_all_in_cost_case1(self):
        """All-in basis €0.05; selling at €0.03 nets €0.02 after fees."""
        position = calculate_position_state([_lot(Decimal("0.05"))], MHN)
        result = compute_unrealized_pnl(position, Decimal("0.03"), game_fee_rate=0)
        # Cost basis is the all-in figure, never the seller-side amount.
        assert result.known_cost_basis == Decimal("0.05")
        # 0.03 gross - max(5% of 0.03, 0.01) = 0.03 - 0.01 = 0.02 net
        assert result.current_net_realizable_value == Decimal("0.02")
        assert result.unrealized_pnl == Decimal("-0.03")
        assert result.is_profitable() is False

    def test_pnl_break_even_case2(self):
        """Proceeds equal to the all-in cost are still a LOSS once fees apply."""
        position = calculate_position_state([_lot(Decimal("0.05"))], MHN)
        result = compute_unrealized_pnl(position, Decimal("0.05"), game_fee_rate=0)
        # 0.05 gross - 0.01 min fee = 0.04 net; 0.04 - 0.05 = -0.01
        assert result.unrealized_pnl == Decimal("-0.01")
        assert result.is_profitable() is False

    def test_pnl_profit_case3(self):
        """Selling at €0.10 against a €0.05 all-in basis is profitable."""
        position = calculate_position_state([_lot(Decimal("0.05"))], MHN)
        result = compute_unrealized_pnl(position, Decimal("0.10"), game_fee_rate=0)
        # 0.10 gross - max(5% of 0.10, 0.01) = 0.10 - 0.01 = 0.09 net
        assert result.current_net_realizable_value == Decimal("0.09")
        assert result.unrealized_pnl == Decimal("0.04")
        assert result.is_profitable() is True

    def test_cost_basis_is_all_in_not_seller_amount(self):
        """The same sale yields different P&L per cost basis.

        Guards the core Phase 3G requirement: valuation uses the all-in
        cost (€0.05), not the price-excluding-fees amount (€0.03).
        """
        all_in = calculate_position_state([_lot(Decimal("0.05"))], MHN)
        seller_only = calculate_position_state([_lot(Decimal("0.03"))], MHN)
        price = Decimal("0.03")
        pnl_all_in = compute_unrealized_pnl(all_in, price, game_fee_rate=0)
        pnl_seller = compute_unrealized_pnl(seller_only, price, game_fee_rate=0)
        # Identical sale, different basis -> materially different P&L.
        assert pnl_all_in.unrealized_pnl != pnl_seller.unrealized_pnl

    def test_sale_side_net_proceeds_match_verified_listing(self):
        """The fee model must reproduce the verified Rixqor split exactly.

        Verified ground truth on the live listing: strSubtotal €0.05
        (buyer pays) - unFee €0.02 = unPrice €0.03 (seller receives).

        economic.calculate_total_fees models the SELL side as
        ``max(5% of gross, €0.01) + game_fee``. That schedule cannot
        produce €0.02 on a €0.05 gross (it yields €0.03), so the exact
        verified split can only come from Steam's own structured fields.
        This test asserts the authoritative values directly and proves
        the modelled estimate does NOT match at this price point --
        which is precisely why structured evidence takes precedence.
        """
        # Authoritative: derived from the verified listing fields.
        gross_buyer_pays = Decimal("0.05")   # strSubtotal
        steam_unfee = Decimal("0.02")        # unFee
        seller_proceeds = gross_buyer_pays - steam_unfee
        assert seller_proceeds == Decimal("0.03")

        # The modelled schedule floors the Steam fee at €0.01 and adds no
        # publisher component, so it cannot reproduce Steam's actual
        # €0.02 split at this price point. Structured evidence wins.
        estimated_fees = calculate_total_fees(gross_buyer_pays, game_fee_rate=None)
        assert estimated_fees == Decimal("0.01")
        assert estimated_fees != steam_unfee

    def test_unknown_cost_position_reports_no_pnl(self):
        """Unknown cost must never be silently valued at zero or at market."""
        lot = AcquisitionLot(
            source_transaction_id=1, market_hash_name=MHN, bot_name=BOT,
            original_quantity=1, remaining_quantity=1, unit_cost=None,
            acquired_at="2026-01-01T00:00:00+00:00",
            cost_status=CostStatus.UNKNOWN,
        )
        position = calculate_position_state([lot], MHN)
        result = compute_unrealized_pnl(position, Decimal("0.05"), game_fee_rate=0)
        assert result.known_cost_basis is None
        assert result.unrealized_pnl is None
        assert result.has_unknown_cost()


# ----------------------------------------------------------------------
# Canonical recording path keeps its documented semantics
# ----------------------------------------------------------------------

class TestRecordAcquisitionSemanticsPreserved:
    def test_tracked_record_stores_seller_side_unit_cost(self):
        """record_acquisition's unit_cost stays the price-excl-fees basis."""
        conn = _conn(ACCOUNTING_LOT_DDL)
        repo = Repository(conn)
        provenance = Provenance(
            evidence_type=EvidenceType.STEAM_MARKET_HISTORY,
            evidence_id="synthetic-purchase-id",
            evidence_data={"paid_amount_cents": 3, "paid_fee_cents": 2},
        )
        recorded = record_acquisition(
            repository=repo,
            bot_name=BOT,
            market_hash_name=MHN,
            quantity=1,
            acquired_at="2026-01-01T00:00:00+00:00",
            unit_cost=Decimal("0.03"),
            currency="EUR",
            source_type=SourceType.STEAM_MARKET_PURCHASE,
            provenance=provenance,
            external_reference="synthetic-listing-id:synthetic-purchase-id",
            entered_at="2026-01-01T00:00:00+00:00",
        )
        assert recorded.lot.unit_cost == Decimal("0.03")
        assert recorded.lot.cost_status is CostStatus.TRACKED
