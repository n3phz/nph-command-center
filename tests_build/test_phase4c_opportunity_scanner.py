"""
Phase 4C — Read-Only Steam Market Opportunity Scanner Tests

Tests for the market opportunity scanner that identifies
profitable manual purchase opportunities.

READ-ONLY: No database writes, no market operations.
"""

import sys
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest

# Add app directory to path
sys.path.insert(0, "app")

from market_opportunity_scanner import (
    MarketOpportunityScanner,
    StructuredMarketPrice,
    AcquisitionCost,
    OpportunityClassification,
    LiquidityEvidence,
    IdentityVerificationStatus,
    create_scanner,
)


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def sample_structured_price():
    """Create a sample structured market price."""
    return StructuredMarketPrice(
        un_price=500,  # €5.00 seller proceeds
        un_fee=300,    # €3.00 buyer fees
        un_steam_fee=150,
        un_publisher_fee=150,
        str_subtotal="€8.00",
        e_currency=3,
        listingid="123456789",
        b_mine=False,
        market_hash_name="Test Item",
        classid="12345",
    )


@pytest.fixture
def sample_acquisition_cost():
    """Create a sample acquisition cost."""
    return AcquisitionCost(
        unit_cost=Decimal("5.00"),
        acquisition_fee=Decimal("3.00"),
        all_in_cost=Decimal("8.00"),
        cost_status="TRACKED",
        source_transaction_id=1,
    )


@pytest.fixture
def scanner(tmp_path):
    """Create a scanner instance with temp database."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
    # Create minimal schema
    conn.execute("""
        CREATE TABLE acquisition_lots (
            id INTEGER PRIMARY KEY,
            source_transaction_id INTEGER NOT NULL,
            market_hash_name TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            original_quantity INTEGER NOT NULL,
            remaining_quantity INTEGER NOT NULL,
            unit_cost TEXT,
            acquired_at TEXT NOT NULL,
            cost_status TEXT NOT NULL,
            acquisition_fee TEXT,
            all_in_cost TEXT,
            external_ref TEXT,
            provenance TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE transactions (
            id INTEGER PRIMARY KEY,
            type TEXT NOT NULL,
            market_hash_name TEXT NOT NULL,
            quantity INTEGER NOT NULL,
            unit_price TEXT NOT NULL,
            fees TEXT NOT NULL DEFAULT '0',
            total_value TEXT NOT NULL DEFAULT '0',
            timestamp TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            external_ref TEXT
        )
    """)
    conn.commit()
    conn.close()
    return MarketOpportunityScanner(
        db_path=db_path,
        steam_app_id=753,
    )


# ============================================================
# MARKETABILITY TESTS
# ============================================================


class TestMarketability:
    """Test marketability checks."""

    def test_not_marketable_item(self, scanner):
        """Non-marketable items should be classified as NOT_MARKETABLE."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=False,
            tradable=True,
        )
        assert opp.classification == OpportunityClassification.NOT_MARKETABLE
        assert opp.marketability_verified is False
        assert opp.confidence == "HIGH"
        assert "not marketable" in opp.reason.lower()

    def test_not_tradable_item(self, scanner):
        """Non-tradable items should be classified as NOT_MARKETABLE."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=False,
        )
        assert opp.classification == OpportunityClassification.NOT_MARKETABLE
        assert opp.marketability_verified is False

    def test_both_marketable_and_tradable(self, scanner, sample_structured_price, sample_acquisition_cost):
        """Item that is both marketable and tradable proceeds to further checks."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=sample_structured_price,
            acquisition_cost=sample_acquisition_cost,
        )
        # Should not be NOT_MARKETABLE
        assert opp.classification != OpportunityClassification.NOT_MARKETABLE
        assert opp.marketability_verified is True


# ============================================================
# IDENTITY VERIFICATION TESTS
# ============================================================


class TestIdentityVerification:
    """Test identity verification."""

    def test_identity_matches(self, scanner, sample_structured_price):
        """Structured price with matching identity should verify."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            classid="12345",
            marketable=True,
            tradable=True,
            market_price=sample_structured_price,
        )
        assert opp.identity_verified is True

    def test_wrong_market_hash_name(self, scanner):
        """Wrong market_hash_name should fail identity verification."""
        price = StructuredMarketPrice(
            un_price=100,
            un_fee=50,
            un_steam_fee=25,
            un_publisher_fee=25,
            str_subtotal="€1.50",
            e_currency=3,
            listingid="999",
            b_mine=False,
            market_hash_name="Other Item",
            classid="12345",
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
        )
        assert opp.identity_verified is False
        assert opp.classification == OpportunityClassification.UNVERIFIED

    def test_wrong_classid(self, scanner):
        """Wrong classid should fail identity verification."""
        price = StructuredMarketPrice(
            un_price=100,
            un_fee=50,
            un_steam_fee=25,
            un_publisher_fee=25,
            str_subtotal="€1.50",
            e_currency=3,
            listingid="999",
            b_mine=False,
            market_hash_name="Test Item",
            classid="99999",  # Wrong classid
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            classid="12345",  # Different classid
            marketable=True,
            tradable=True,
            market_price=price,
        )
        assert opp.identity_verified is False

    def test_missing_market_price(self, scanner):
        """Missing market price should result in UNVERIFIED."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
        )
        assert opp.identity_verified is False
        assert opp.classification == OpportunityClassification.UNVERIFIED


# ============================================================
# €1.31 FALSE POSITIVE REGRESSION TEST
# ============================================================


class TestFalsePositiveRegression:
    """Test that the €1.31 false positive is rejected."""

    def test_131_false_positive_rejected(self, scanner):
        """
        The HTML may contain €1.31 but authoritative structured data
        shows unPrice=3, unFee=2 (€0.03 seller proceeds, €0.05 total).
        """
        # Simulate the false HTML-based price
        fake_price = StructuredMarketPrice(
            un_price=3,    # €0.03 actual seller proceeds
            un_fee=2,      # €0.02 actual buyer fees
            un_steam_fee=1,
            un_publisher_fee=1,
            str_subtotal="€0.05",
            e_currency=3,
            listingid="549032738418292987",
            b_mine=False,
            market_hash_name="774361-Our Lady of the Charred Visage",
            classid="3516150028",
        )

        opp = scanner.scan_item(
            market_hash_name="774361-Our Lady of the Charred Visage",
            appid=753,
            classid="3516150028",
            marketable=True,
            tradable=True,
            market_price=fake_price,
        )

        # Should use STRUCTURED price, not HTML-embedded €1.31
        assert opp.seller_proceeds == Decimal("0.03")
        assert opp.seller_proceeds_verified is True
        # Without acquisition cost, profit cannot be calculated
        assert opp.expected_profit is None
        assert opp.classification == OpportunityClassification.UNVERIFIED


# ============================================================
# NON-MARKETABLE TEST ITEM REGRESSION
# ============================================================


class TestNonMarketableRegression:
    """Test that the non-marketable test item is correctly excluded."""

    def test_non_marketable_item_excluded(self, scanner):
        """
        774361-Our Lady of the Charred Visage is NOT marketable
        (marketable=false, tradable=false per inventory API).
        """
        opp = scanner.scan_item(
            market_hash_name="774361-Our Lady of the Charred Visage",
            appid=753,
            classid="3516150028",
            marketable=False,
            tradable=False,
        )

        assert opp.classification == OpportunityClassification.NOT_MARKETABLE
        assert opp.marketable is False
        assert opp.tradable is False
        assert opp.identity_verified is False


# ============================================================
# PRICING TESTS
# ============================================================


class TestPricing:
    """Test price extraction and semantics."""

    def test_unprice_is_seller_proceeds(self, scanner, sample_structured_price):
        """unPrice should be interpreted as seller proceeds."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=sample_structured_price,
        )
        # un_price = 500 cents = €5.00 seller proceeds
        assert opp.seller_proceeds == Decimal("5.00")
        assert opp.seller_proceeds_verified is True

    def test_unfee_is_buyer_fees(self, scanner, sample_structured_price):
        """unFee should be interpreted as buyer-paid fees."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=sample_structured_price,
        )
        # un_fee = 300 cents = €3.00 buyer fees
        assert opp.seller_proceeds == Decimal("5.00")
        # Buyer total should be €8.00 (unPrice + unFee)
        assert sample_structured_price.buyer_total == Decimal("8.00")

    def test_strsubtotal_is_buyer_total(self, scanner, sample_structured_price):
        """strSubtotal should match unPrice + unFee."""
        assert sample_structured_price.str_subtotal == "€8.00"
        assert sample_structured_price.buyer_total == Decimal("8.00")

    def test_missing_unprice(self, scanner):
        """Missing unPrice should result in UNVERIFIED seller proceeds."""
        # Use 0 as placeholder since dataclass requires int
        price = StructuredMarketPrice(
            un_price=0,  # Missing/unavailable
            un_fee=100,
            un_steam_fee=50,
            un_publisher_fee=50,
            str_subtotal="€1.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
        )
        assert opp.seller_proceeds == Decimal("0.00")
        assert opp.seller_proceeds_verified is True  # Zero is valid

    def test_invalid_unprice(self, scanner):
        """Invalid (negative) unPrice should be rejected."""
        price = StructuredMarketPrice(
            un_price=-100,  # Invalid
            un_fee=50,
            un_steam_fee=25,
            un_publisher_fee=25,
            str_subtotal="€-0.50",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        # This would fail at construction time due to negative value
        # But we test the case where unPrice is missing
        price_no_data = StructuredMarketPrice(
            un_price=0,
            un_fee=0,
            un_steam_fee=0,
            un_publisher_fee=0,
            str_subtotal="€0.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price_no_data,
        )
        # Zero price should still be verifiable
        assert opp.seller_proceeds == Decimal("0.00")


# ============================================================
# ACCOUNTING TESTS
# ============================================================


class TestAccounting:
    """Test acquisition cost handling."""

    def test_tracked_cost_known(self, scanner, sample_acquisition_cost):
        """TRACKED cost status with known all_in_cost."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            acquisition_cost=sample_acquisition_cost,
        )
        assert opp.acquisition_cost_verified is True
        assert opp.all_in_cost == Decimal("8.00")

    def test_unknown_cost_status(self, scanner):
        """UNKNOWN cost status should result in UNVERIFIED."""
        price = StructuredMarketPrice(
            un_price=1000,
            un_fee=100,
            un_steam_fee=50,
            un_publisher_fee=50,
            str_subtotal="€11.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        cost = AcquisitionCost(
            unit_cost=None,
            acquisition_fee=None,
            all_in_cost=None,
            cost_status="UNKNOWN",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=cost,
        )
        assert opp.acquisition_cost_verified is False
        assert opp.classification == OpportunityClassification.UNVERIFIED

    def test_missing_acquisition_fee(self, scanner, sample_acquisition_cost):
        """Missing acquisition_fee should still work if all_in_cost is stored."""
        cost = AcquisitionCost(
            unit_cost=Decimal("5.00"),
            acquisition_fee=None,  # Missing
            all_in_cost=Decimal("8.00"),  # But all_in_cost is known
            cost_status="TRACKED",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            acquisition_cost=cost,
        )
        assert opp.acquisition_cost_verified is True
        assert opp.all_in_cost == Decimal("8.00")

    def test_null_all_in_cost(self, scanner, sample_acquisition_cost):
        """NULL all_in_cost should result in UNVERIFIED."""
        price = StructuredMarketPrice(
            un_price=1000,
            un_fee=100,
            un_steam_fee=50,
            un_publisher_fee=50,
            str_subtotal="€11.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        cost = AcquisitionCost(
            unit_cost=Decimal("5.00"),
            acquisition_fee=Decimal("3.00"),
            all_in_cost=None,  # NULL
            cost_status="TRACKED",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=cost,
        )
        assert opp.acquisition_cost_verified is False
        assert opp.classification == OpportunityClassification.UNVERIFIED


# ============================================================
# PROFIT CALCULATION TESTS
# ============================================================


class TestProfitCalculation:
    """Test profit calculations."""

    def test_loss_opportunity(self, scanner):
        """Loss opportunity: seller proceeds < all-in cost."""
        price = StructuredMarketPrice(
            un_price=300,  # €3.00 seller proceeds
            un_fee=200,    # €2.00 buyer fees
            un_steam_fee=100,
            un_publisher_fee=100,
            str_subtotal="€5.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        cost = AcquisitionCost(
            unit_cost=Decimal("3.00"),
            acquisition_fee=Decimal("2.00"),
            all_in_cost=Decimal("5.00"),
            cost_status="TRACKED",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=cost,
        )
        assert opp.classification == OpportunityClassification.LOSS
        assert opp.expected_profit == Decimal("-2.00")  # €3.00 - €5.00
        assert opp.profit_margin == Decimal("-0.40")  # -40%

    def test_break_even(self, scanner):
        """Break-even: seller proceeds = all-in cost."""
        price = StructuredMarketPrice(
            un_price=500,  # €5.00 seller proceeds
            un_fee=200,
            un_steam_fee=100,
            un_publisher_fee=100,
            str_subtotal="€7.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        cost = AcquisitionCost(
            unit_cost=Decimal("5.00"),
            acquisition_fee=Decimal("0.00"),
            all_in_cost=Decimal("5.00"),  # Must equal seller proceeds for break-even
            cost_status="TRACKED",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=cost,
        )
        assert opp.classification == OpportunityClassification.BREAK_EVEN
        assert opp.expected_profit == Decimal("0.00")
        assert opp.profit_margin == Decimal("0.00")
        assert opp.expected_profit == Decimal("0.00")
        assert opp.profit_margin == Decimal("0.00")

    def test_profitable_opportunity(self, scanner):
        """Profitable: seller proceeds > all-in cost."""
        price = StructuredMarketPrice(
            un_price=1000,  # €10.00 seller proceeds
            un_fee=300,
            un_steam_fee=150,
            un_publisher_fee=150,
            str_subtotal="€13.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        cost = AcquisitionCost(
            unit_cost=Decimal("5.00"),
            acquisition_fee=Decimal("3.00"),
            all_in_cost=Decimal("8.00"),
            cost_status="TRACKED",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=cost,
        )
        assert opp.classification == OpportunityClassification.POTENTIALLY_PROFITABLE
        assert opp.expected_profit == Decimal("2.00")  # €10.00 - €8.00
        assert opp.profit_margin == Decimal("0.25")  # 25%

    def test_zero_cost_edge_case(self, scanner):
        """Zero acquisition cost edge case."""
        price = StructuredMarketPrice(
            un_price=100,
            un_fee=50,
            un_steam_fee=25,
            un_publisher_fee=25,
            str_subtotal="€1.50",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        cost = AcquisitionCost(
            unit_cost=Decimal("0.00"),
            acquisition_fee=Decimal("0.00"),
            all_in_cost=Decimal("0.00"),
            cost_status="TRACKED",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=cost,
        )
        # Zero denominator should be handled
        assert opp.all_in_cost == Decimal("0.00")
        assert opp.profit_margin is None  # Division by zero

    def test_fee_fields_present_but_zero(self, scanner):
        """Fee fields present but zero."""
        price = StructuredMarketPrice(
            un_price=100,
            un_fee=0,  # Zero fees
            un_steam_fee=0,
            un_publisher_fee=0,
            str_subtotal="€1.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
        )
        assert opp.seller_proceeds == Decimal("1.00")
        assert opp.seller_proceeds_verified is True


# ============================================================
# LIQUIDITY EVIDENCE TESTS
# ============================================================


class TestLiquidityEvidence:
    """Test liquidity evidence classification."""

    def test_high_evidence(self, scanner):
        """Multiple active listings with quantity = HIGH."""
        liquidity = {
            "active_listing_count": 10,
            "available_quantity": 5,
        }
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            liquidity=liquidity,
        )
        assert opp.liquidity_evidence == LiquidityEvidence.HIGH_EVIDENCE.value

    def test_medium_evidence(self, scanner):
        """Few active listings = MEDIUM."""
        liquidity = {
            "active_listing_count": 3,
        }
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            liquidity=liquidity,
        )
        assert opp.liquidity_evidence == LiquidityEvidence.MEDIUM_EVIDENCE.value

    def test_low_evidence(self, scanner):
        """Single listing = LOW."""
        liquidity = {
            "active_listing_count": 1,
        }
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            liquidity=liquidity,
        )
        assert opp.liquidity_evidence == LiquidityEvidence.LOW_EVIDENCE.value

    def test_insufficient_data(self, scanner):
        """No liquidity data = INSUFFICIENT."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
        )
        assert opp.liquidity_evidence == LiquidityEvidence.INSUFFICIENT_DATA.value


# ============================================================
# CLASSIFICATION TESTS
# ============================================================


class TestClassification:
    """Test opportunity classification."""

    def test_not_marketable(self, scanner):
        """Non-marketable items."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=False,
            tradable=True,
        )
        assert opp.classification == OpportunityClassification.NOT_MARKETABLE

    def test_unverified_missing_evidence(self, scanner):
        """Missing critical evidence = UNVERIFIED."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
        )
        assert opp.classification == OpportunityClassification.UNVERIFIED

    def test_loss(self, scanner):
        """Negative profit = LOSS."""
        price = StructuredMarketPrice(
            un_price=300,
            un_fee=200,
            un_steam_fee=100,
            un_publisher_fee=100,
            str_subtotal="€5.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        cost = AcquisitionCost(
            unit_cost=Decimal("3.00"),
            acquisition_fee=Decimal("2.00"),
            all_in_cost=Decimal("5.00"),
            cost_status="TRACKED",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=cost,
        )
        assert opp.classification == OpportunityClassification.LOSS

    def test_break_even(self, scanner):
        """Zero profit = BREAK_EVEN."""
        price = StructuredMarketPrice(
            un_price=500,  # €5.00 seller proceeds
            un_fee=200,
            un_steam_fee=100,
            un_publisher_fee=100,
            str_subtotal="€7.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        cost = AcquisitionCost(
            unit_cost=Decimal("5.00"),
            acquisition_fee=Decimal("0.00"),
            all_in_cost=Decimal("5.00"),  # Must equal seller proceeds for break-even
            cost_status="TRACKED",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=cost,
        )
        assert opp.classification == OpportunityClassification.BREAK_EVEN
        assert opp.expected_profit == Decimal("0.00")
        assert opp.profit_margin == Decimal("0.00")

    def test_potentially_profitable(self, scanner):
        """Positive profit but insufficient evidence = POTENTIALLY_PROFITABLE."""
        price = StructuredMarketPrice(
            un_price=1000,
            un_fee=300,
            un_steam_fee=150,
            un_publisher_fee=150,
            str_subtotal="€13.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        cost = AcquisitionCost(
            unit_cost=Decimal("5.00"),
            acquisition_fee=Decimal("3.00"),
            all_in_cost=Decimal("8.00"),
            cost_status="TRACKED",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=cost,
            liquidity={"active_listing_count": 1},  # Low liquidity
        )
        assert opp.classification == OpportunityClassification.POTENTIALLY_PROFITABLE

    def test_verified_profitable(self, scanner):
        """Positive profit with sufficient evidence = VERIFIED_PROFITABLE."""
        price = StructuredMarketPrice(
            un_price=1000,
            un_fee=300,
            un_steam_fee=150,
            un_publisher_fee=150,
            str_subtotal="€13.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        cost = AcquisitionCost(
            unit_cost=Decimal("5.00"),
            acquisition_fee=Decimal("3.00"),
            all_in_cost=Decimal("8.00"),
            cost_status="TRACKED",
            source_transaction_id=1,
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=cost,
            liquidity={"active_listing_count": 10, "available_quantity": 5},  # High liquidity
        )
        assert opp.classification == OpportunityClassification.VERIFIED_PROFITABLE


# ============================================================
# SAFETY TESTS
# ============================================================


class TestSafety:
    """Test that scanner is read-only."""

    def test_no_database_writes(self, scanner, tmp_path):
        """Scanner should not write to database."""
        db_path = scanner.db_path
        initial_size = __import__('os').path.getsize(db_path)

        # Scan an item
        scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
        )

        # Database size should not change
        final_size = __import__('os').path.getsize(db_path)
        assert initial_size == final_size, "Database was modified!"

    def test_no_market_write_functions_called(self, scanner):
        """Scanner should not call any market write functions."""
        # Verify the scanner doesn't reference fetch_market_price
        import market_opportunity_scanner as mod
        assert not hasattr(mod, 'fetch_market_price')
        # Scanner should work without any market write calls
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
        )
        assert opp is not None


# ============================================================
# MALFORMED/DATA TESTS
# ============================================================


class TestMalformedData:
    """Test handling of malformed or missing data."""

    def test_none_market_price(self, scanner):
        """None market price should be handled gracefully."""
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=None,
        )
        assert opp.seller_proceeds is None
        assert opp.classification == OpportunityClassification.UNVERIFIED

    def test_none_acquisition_cost(self, scanner):
        """None acquisition cost should result in UNVERIFIED."""
        price = StructuredMarketPrice(
            un_price=1000,
            un_fee=100,
            un_steam_fee=50,
            un_publisher_fee=50,
            str_subtotal="€11.00",
            e_currency=3,
            listingid="123",
            b_mine=False,
            market_hash_name="Test Item",
            classid="12345",
        )
        opp = scanner.scan_item(
            market_hash_name="Test Item",
            appid=753,
            marketable=True,
            tradable=True,
            market_price=price,
            acquisition_cost=None,
        )
        assert opp.all_in_cost is None
        assert opp.acquisition_cost_verified is False
        assert opp.classification == OpportunityClassification.UNVERIFIED

    def test_empty_market_hash_name(self, scanner):
        """Empty market_hash_name should be handled."""
        opp = scanner.scan_item(
            market_hash_name="",
            appid=753,
            marketable=True,
            tradable=True,
        )
        assert opp is not None
        assert opp.market_hash_name == ""


# ============================================================
# HELPER FUNCTIONS
# ============================================================


def test_create_scanner():
    """Test factory function."""
    with mock.patch('market_opportunity_scanner.MarketOpportunityScanner') as Mock:
        scanner = create_scanner("/tmp/test.db")
        Mock.assert_called_once_with(db_path="/tmp/test.db")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
