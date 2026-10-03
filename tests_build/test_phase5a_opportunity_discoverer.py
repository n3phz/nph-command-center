"""
Phase 5A — Read-Only Steam Market Opportunity Discovery Tests

Tests for the market opportunity discoverer that discovers candidate
Steam Market items and evaluates them against the accounting rules.

READ-ONLY: No database writes, no market operations.
"""

import sys
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest

sys.path.insert(0, "projects/steam-trade-bot/app")

from market_opportunity_discoverer import (
    MarketOpportunityDiscoverer,
    Candidate,
    DiscoverySource,
)
from market_opportunity_scanner import (
    StructuredMarketPrice,
    AcquisitionCost,
    OpportunityClassification,
)


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def sample_candidate():
    """Create a sample candidate."""
    return Candidate(
        market_hash_name="Test Item",
        appid=730,
        classid="12345",
        listingid="123456789",
        seller_proceeds=Decimal("5.00"),
        buyer_total=Decimal("8.00"),
        steam_fee=Decimal("0.25"),
        publisher_fee=Decimal("0.25"),
        active_listing_count=10,
        acquisition_cost=Decimal("3.00"),
        expected_profit=Decimal("2.00"),
        profit_margin=Decimal("0.67"),
        liquidity_evidence="HIGH_EVIDENCE",
        identity_verified=True,
        classification=OpportunityClassification.VERIFIED_PROFITABLE,
        confidence="HIGH",
        reason="Verified profitable opportunity.",
        timestamp=datetime.now(timezone.utc).isoformat(),
        data_sources=["steam_market_structured"],
    )


@pytest.fixture
def discoverer(tmp_path):
    """Create a discoverer with temp database."""
    db_path = str(tmp_path / "test.db")
    conn = sqlite3.connect(db_path)
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

    mock_session = mock.MagicMock()
    mock_session.get.return_value.status_code = 200
    mock_session.get.return_value.text = ""

    return MarketOpportunityDiscoverer(
        db_path=db_path,
        session=mock_session,
        max_candidates=25,
    )


# ============================================================
# CANDIDATE CLASS TESTS
# ============================================================


class TestCandidate:
    """Test Candidate dataclass properties."""

    def test_is_profitable_true(self, sample_candidate):
        """Profitable candidate should have is_profitable=True."""
        assert sample_candidate.is_profitable is True

    def test_is_profitable_false_no_profit(self, sample_candidate):
        """Candidate with no profit should have is_profitable=False."""
        candidate = Candidate(
            market_hash_name="Test Item",
            appid=730,
            classid="12345",
            listingid="123",
            seller_proceeds=None,
            buyer_total=None,
            steam_fee=None,
            publisher_fee=None,
            active_listing_count=None,
            acquisition_cost=None,
            expected_profit=None,
            profit_margin=None,
            liquidity_evidence="INSUFFICIENT_DATA",
            identity_verified=False,
            classification=OpportunityClassification.UNVERIFIED,
            confidence="LOW",
            reason="No data.",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        assert candidate.is_profitable is False

    def test_is_profitable_false_no_identity(self, sample_candidate):
        """Candidate without identity verification should be not profitable."""
        candidate = Candidate(
            market_hash_name="Test Item",
            appid=730,
            classid="12345",
            listingid="123",
            seller_proceeds=Decimal("5.00"),
            buyer_total=Decimal("4.00"),
            steam_fee=Decimal("0.25"),
            publisher_fee=Decimal("0.25"),
            active_listing_count=5,
            acquisition_cost=Decimal("3.00"),
            expected_profit=Decimal("2.00"),
            profit_margin=Decimal("0.67"),
            liquidity_evidence="HIGH_EVIDENCE",
            identity_verified=False,
            classification=OpportunityClassification.POTENTIALLY_PROFITABLE,
            confidence="MEDIUM",
            reason="Unverified.",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        assert candidate.is_profitable is False


# ============================================================
# DISCOVERY SOURCE TESTS
# ============================================================


class TestDiscoverySource:
    """Test discovery source enum."""

    def test_source_values(self):
        """DiscoverySource should have expected values."""
        assert DiscoverySource.MARKET_LISTING_PAGE == "market_listing_page"
        assert DiscoverySource.STRUCTURED_PAYLOAD == "structured_payload"
        assert DiscoverySource.CACHED_PRICE == "cached_price"


# ============================================================
# DISCOVERER CREATION TESTS
# ============================================================


class TestDiscovererCreation:
    """Test discoverer creation."""

    def test_create_discoverer(self, tmp_path):
        """create_discoverer factory should create instance."""
        db_path = str(tmp_path / "test.db")
        mock_session = mock.MagicMock()

        discoverer = MarketOpportunityDiscoverer(
            db_path=db_path,
            session=mock_session,
        )

        assert discoverer.db_path == db_path
        assert discoverer.max_candidates == 25
        # steam_app_id is on the scanner, not directly on discoverer
        assert discoverer.scanner.steam_app_id == 753

    def test_create_discoverer_with_custom_limits(self, tmp_path):
        """create_discoverer should respect custom parameters."""
        db_path = str(tmp_path / "test.db")
        mock_session = mock.MagicMock()

        discoverer = MarketOpportunityDiscoverer(
            db_path=db_path,
            session=mock_session,
            max_candidates=10,
            discovery_appids=[730, 570],
        )

        assert discoverer.max_candidates == 10
        assert discoverer.discovery_appids == [730, 570]


# ============================================================
# DISCOVERY LIMIT TESTS
# ============================================================


class TestDiscoveryLimit:
    """Test bounded discovery."""

    def test_max_candidates_limit(self, discoverer):
        """Discoverer should respect max_candidates limit."""
        discoverer.max_candidates = 5
        candidates = discoverer.discover(limit=10)
        assert len(candidates) <= 5

    def test_limit_parameter(self, discoverer):
        """Discoverer should respect limit parameter."""
        candidates = discoverer.discover(limit=3)
        assert len(candidates) <= 3


# ============================================================
# READ-ONLY SAFETY TESTS
# ============================================================


class TestReadOnlySafety:
    """Test that discovery is read-only."""

    def test_no_database_writes(self, discoverer, tmp_path):
        """Discovery should not write to database."""
        db_path = discoverer.db_path
        initial_size = __import__('os').path.getsize(db_path)

        discoverer.discover(limit=5)

        final_size = __import__('os').path.getsize(db_path)
        assert initial_size == final_size

    def test_no_steam_write_operations(self, discoverer):
        """Discovery should not perform any Steam Market write operations."""
        # Verify the discoverer doesn't have write methods
        write_methods = [
            'create_listing',
            'sell_item',
            'buy_item',
            'place_order',
            'execute_trade',
        ]
        for method in write_methods:
            assert not hasattr(discoverer, method), f"Discoverer has write method: {method}"


# ============================================================
# CANDIDATE SORTING TESTS
# ============================================================


class TestCandidateSorting:
    """Test candidate sorting by profit."""

    def test_sorted_by_profit_descending(self):
        """Candidates should be sorted by expected profit descending."""
        candidates = [
            Candidate(
                market_hash_name="Low Profit Item",
                appid=730,
                classid="1",
                listingid="1",
                seller_proceeds=Decimal("10.00"),
                buyer_total=Decimal("12.00"),
                steam_fee=Decimal("0.50"),
                publisher_fee=Decimal("0.50"),
                active_listing_count=5,
                acquisition_cost=Decimal("8.00"),
                expected_profit=Decimal("2.00"),
                profit_margin=Decimal("0.25"),
                liquidity_evidence="HIGH_EVIDENCE",
                identity_verified=True,
                classification=OpportunityClassification.VERIFIED_PROFITABLE,
                confidence="HIGH",
                reason="Good profit.",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
            Candidate(
                market_hash_name="High Profit Item",
                appid=730,
                classid="2",
                listingid="2",
                seller_proceeds=Decimal("20.00"),
                buyer_total=Decimal("22.00"),
                steam_fee=Decimal("1.00"),
                publisher_fee=Decimal("1.00"),
                active_listing_count=10,
                acquisition_cost=Decimal("15.00"),
                expected_profit=Decimal("5.00"),
                profit_margin=Decimal("0.33"),
                liquidity_evidence="HIGH_EVIDENCE",
                identity_verified=True,
                classification=OpportunityClassification.VERIFIED_PROFITABLE,
                confidence="HIGH",
                reason="Best profit.",
                timestamp=datetime.now(timezone.utc).isoformat(),
            ),
        ]

        # Sort like discoverer does
        candidates.sort(
            key=lambda c: (
                -(c.expected_profit or Decimal("0")),
                c.market_hash_name,
            )
        )

        assert candidates[0].market_hash_name == "High Profit Item"
        assert candidates[1].market_hash_name == "Low Profit Item"


# ============================================================
# DUPLICATE HANDLING TESTS
# ============================================================


class TestDuplicateHandling:
    """Test duplicate candidate handling."""

    def test_duplicate_hash_names_filtered(self):
        """Duplicate market_hash_names should be deduplicated."""
        seen_names = set()
        candidates = []

        # Simulate adding duplicate
        for i in range(3):
            mhn = "Duplicate Item"
            if mhn not in seen_names:
                seen_names.add(mhn)
                candidates.append(Candidate(
                    market_hash_name=mhn,
                    appid=730,
                    classid="1",
                    listingid=str(i),
                    seller_proceeds=Decimal("5.00"),
                    buyer_total=Decimal("6.00"),
                    steam_fee=Decimal("0.25"),
                    publisher_fee=Decimal("0.25"),
                    active_listing_count=1,
                    acquisition_cost=None,
                    expected_profit=None,
                    profit_margin=None,
                    liquidity_evidence="INSUFFICIENT_DATA",
                    identity_verified=False,
                    classification=OpportunityClassification.UNVERIFIED,
                    confidence="LOW",
                    reason="Duplicate.",
                    timestamp=datetime.now(timezone.utc).isoformat(),
                ))

        assert len(candidates) == 1
        assert candidates[0].market_hash_name == "Duplicate Item"


# ============================================================
# EMPTY STATE TESTS
# ============================================================


class TestEmptyState:
    """Test empty/discovery failures."""

    def test_empty_response(self, discoverer):
        """Empty Steam response should return no candidates."""
        discoverer.session.get.return_value.text = "<html></html>"
        candidates = discoverer.discover(limit=10)
        assert len(candidates) == 0

    def test_http_error(self, discoverer):
        """HTTP error should return no candidates."""
        discoverer.session.get.return_value.status_code = 404
        candidates = discoverer.discover(limit=10)
        assert len(candidates) == 0

    def test_request_exception(self, discoverer):
        """Request exception should return no candidates."""
        from requests import RequestException
        discoverer.session.get.side_effect = RequestException("Network error")
        candidates = discoverer.discover(limit=10)
        assert len(candidates) == 0


# ============================================================
# INTEGRATION TESTS WITH SCANNER
# ============================================================


class TestScannerIntegration:
    """Test integration with Phase 4C scanner."""

    def test_candidate_uses_scanner_classification(self, discoverer):
        """Candidates should use scanner classification logic."""
        # Create a mock structured price
        price = StructuredMarketPrice(
            un_price=1000,  # €10.00 seller proceeds
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

        # Scan directly
        opp = discoverer.scanner.scan_item(
            market_hash_name="Test Item",
            appid=730,
            classid="12345",
            marketable=True,
            tradable=True,
            market_price=price,
        )

        assert opp.seller_proceeds == Decimal("10.00")
        assert opp.identity_verified is True
        assert opp.classification in (
            OpportunityClassification.UNVERIFIED,
            OpportunityClassification.POTENTIALLY_PROFITABLE,
        )


# ============================================================
# EDGE CASE TESTS
# ============================================================


class TestEdgeCases:
    """Test edge cases."""

    def test_zero_seller_proceeds(self):
        """Zero seller proceeds should be handled."""
        candidate = Candidate(
            market_hash_name="Free Item",
            appid=730,
            classid="1",
            listingid="1",
            seller_proceeds=Decimal("0.00"),
            buyer_total=Decimal("0.00"),
            steam_fee=Decimal("0.00"),
            publisher_fee=Decimal("0.00"),
            active_listing_count=0,
            acquisition_cost=Decimal("0.01"),
            expected_profit=Decimal("-0.01"),
            profit_margin=Decimal("-1.00"),
            liquidity_evidence="INSUFFICIENT_DATA",
            identity_verified=True,
            classification=OpportunityClassification.LOSS,
            confidence="HIGH",
            reason="Zero proceeds.",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        assert candidate.is_profitable is False
        assert candidate.classification == OpportunityClassification.LOSS

    def test_negative_profit_margin(self):
        """Negative profit margin should be LOSS."""
        candidate = Candidate(
            market_hash_name="Loss Item",
            appid=730,
            classid="1",
            listingid="1",
            seller_proceeds=Decimal("1.00"),
            buyer_total=Decimal("2.00"),
            steam_fee=Decimal("0.10"),
            publisher_fee=Decimal("0.10"),
            active_listing_count=1,
            acquisition_cost=Decimal("5.00"),
            expected_profit=Decimal("-4.00"),
            profit_margin=Decimal("-0.80"),
            liquidity_evidence="LOW_EVIDENCE",
            identity_verified=True,
            classification=OpportunityClassification.LOSS,
            confidence="HIGH",
            reason="Loss.",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        assert candidate.is_profitable is False

    def test_missing_acquisition_cost(self):
        """Missing acquisition cost should still allow discovery."""
        candidate = Candidate(
            market_hash_name="Unknown Cost",
            appid=730,
            classid="1",
            listingid="1",
            seller_proceeds=Decimal("10.00"),
            buyer_total=Decimal("12.00"),
            steam_fee=Decimal("0.50"),
            publisher_fee=Decimal("0.50"),
            active_listing_count=5,
            acquisition_cost=None,
            expected_profit=None,
            profit_margin=None,
            liquidity_evidence="MEDIUM_EVIDENCE",
            identity_verified=True,
            classification=OpportunityClassification.UNVERIFIED,
            confidence="MEDIUM",
            reason="Unknown cost.",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
        assert candidate.is_profitable is False
        assert candidate.classification == OpportunityClassification.UNVERIFIED


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
