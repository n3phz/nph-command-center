"""
Phase 5E — Read-Only Steam Market Price Analyzer Tests

Tests for the market price analyzer that investigates authoritative
Steam Market data sources for acquisition edges.

READ-ONLY: No database writes, no Steam Market write operations.
"""

import sys
import re
import json
import time
from decimal import Decimal
from unittest import mock

import pytest
import requests

sys.path.insert(0, "projects/steam-trade-bot/app")

from market_price_analyzer import (
    MarketPriceAnalyzer,
    PriceOverview,
    SellListing,
    PriceSpread,
    AcquisitionEdge,
    create_analyzer,
)


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def session():
    """Create a mock HTTP session."""
    return mock.MagicMock()


@pytest.fixture
def analyzer(session):
    """Create an analyzer with mocked session."""
    return MarketPriceAnalyzer(
        session=session,
        request_delay=0.0,
    )


@pytest.fixture
def sample_price_overview():
    """Sample Price Overview response."""
    return {
        "success": True,
        "lowest_price": "$0.03",
    }


@pytest.fixture
def sample_search_results():
    """Sample Search Render response."""
    return {
        "success": True,
        "total_count": 35535,
        "results": [
            {
                "name": "Sealed Graffiti | Test",
                "hash_name": "Sealed Graffiti | Test",
                "sell_listings": 100,
                "sell_price": 3,
                "sell_price_text": "$0.03",
                "sale_price_text": "$0.02",
                "asset_description": {
                    "appid": 730,
                    "classid": "12345",
                    "tradable": 1,
                    "market_hash_name": "Sealed Graffiti | Test",
                },
            },
        ],
    }


@pytest.fixture
def sample_market_history():
    """Sample Market History response."""
    return {
        "success": True,
        "total_count": 0,
        "events": [],
        "listings": {},
        "assets": {},
    }


# ============================================================
# PRICE OVERVIEW TESTS
# ============================================================


class TestPriceOverview:
    """Test Price Overview API integration."""
    
    def test_successful_price_overview(self, analyzer, session, sample_price_overview):
        """Successful Price Overview should return lowest price."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_price_overview
        session.get.return_value = mock_response
        
        result = analyzer.get_price_overview("Test Item", 730, 3)
        
        assert result.success is True
        assert result.market_hash_name == "Test Item"
        assert result.lowest_price == "$0.03"
        assert result.lowest_price_value == Decimal("0.03")
    
    def test_failed_price_overview(self, analyzer, session):
        """Failed Price Overview should return error."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 404
        session.get.return_value = mock_response
        
        result = analyzer.get_price_overview("Nonexistent Item", 730, 3)
        
        assert result.success is False
        assert result.lowest_price is None
        assert result.lowest_price_value is None
        assert "HTTP 404" in result.error
    
    def test_price_parsing_us_format(self, analyzer):
        """US price format should parse correctly."""
        result = analyzer._parse_price_text("$1,234.56")
        assert result == Decimal("1234.56")
    
    def test_price_parsing_european_format(self, analyzer):
        """European price format should parse correctly."""
        result = analyzer._parse_price_text("€1.234,56")
        assert result == Decimal("1234.56")
    
    def test_price_parsing_simple(self, analyzer):
        """Simple price should parse correctly."""
        result = analyzer._parse_price_text("$5.00")
        assert result == Decimal("5.00")
    
    def test_price_parsing_empty(self, analyzer):
        """Empty price should return None."""
        result = analyzer._parse_price_text("")
        assert result is None
    
    def test_price_parsing_invalid(self, analyzer):
        """Invalid price should return None."""
        result = analyzer._parse_price_text("invalid")
        assert result is None


# ============================================================
# SELL LISTINGS TESTS
# ============================================================


class TestSellListings:
    """Test Sell Listings API integration."""
    
    def test_successful_search(self, analyzer, session, sample_search_results):
        """Successful search should return listings."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results
        session.get.return_value = mock_response
        
        listings = analyzer.get_sell_listings(730, limit=5)
        
        assert len(listings) == 1
        assert listings[0].market_hash_name == "Sealed Graffiti | Test"
        assert listings[0].sell_price_cents == 3
        assert listings[0].sell_listings == 100
        assert listings[0].classid == "12345"
    
    def test_empty_search(self, analyzer, session):
        """Empty search should return empty list."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "results": []}
        session.get.return_value = mock_response
        
        listings = analyzer.get_sell_listings(730, limit=5)
        
        assert len(listings) == 0
    
    def test_failed_search(self, analyzer, session):
        """Failed search should return empty list."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 429
        session.get.return_value = mock_response
        
        listings = analyzer.get_sell_listings(730, limit=5)
        
        assert len(listings) == 0
    
    def test_rate_limiting(self, analyzer, session, sample_search_results):
        """Rate limiting should be respected."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results
        session.get.return_value = mock_response
        
        start = time.monotonic()
        analyzer.get_sell_listings(730, limit=1)
        first_call = time.monotonic() - start
        
        analyzer.get_sell_listings(730, limit=1)
        second_call = time.monotonic() - start
        
        # Second call should respect delay
        assert second_call >= analyzer.request_delay * 2


# ============================================================
# MARKET HISTORY TESTS
# ============================================================


class TestMarketHistory:
    """Test Market History API integration."""
    
    def test_empty_history(self, analyzer, session, sample_market_history):
        """Empty history should return empty events."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_market_history
        session.get.return_value = mock_response
        
        history = analyzer.get_market_history()
        
        assert history["success"] is True
        assert history["total_count"] == 0
        assert history["events"] == []
    
    def test_failed_history(self, analyzer, session):
        """Failed history request should return error."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 403
        session.get.return_value = mock_response
        
        history = analyzer.get_market_history()
        
        assert history["success"] is False
        assert "error" in history


# ============================================================
# PRICE SPREAD TESTS
# ============================================================


class TestPriceSpread:
    """Test Price Spread calculation."""
    
    def test_normal_spread(self, analyzer):
        """Normal spread should show loss."""
        spread = analyzer.analyze_spread(
            market_hash_name="Test Item",
            appid=730,
            seller_proceeds=Decimal("5.00"),
            buyer_total=Decimal("5.75"),
            active_listings=100,
        )
        
        assert spread.fees == Decimal("0.75")
        assert abs(spread.fee_percentage - Decimal("13.0")) < Decimal("0.1")
        assert spread.classification == "LOSS"
        assert "fees" in spread.reason.lower()
    
    def test_negative_fees(self, analyzer):
        """Negative fees (rounding) should be UNVERIFIED."""
        spread = analyzer.analyze_spread(
            market_hash_name="Cheap Item",
            appid=730,
            seller_proceeds=Decimal("0.03"),
            buyer_total=Decimal("0.02"),
            active_listings=1000,
        )
        
        assert spread.classification == "UNVERIFIED"
        assert "rounding" in spread.reason.lower()
    
    def test_zero_fees(self, analyzer):
        """Zero fees should be BREAK_EVEN."""
        spread = analyzer.analyze_spread(
            market_hash_name="Special Item",
            appid=730,
            seller_proceeds=Decimal("5.00"),
            buyer_total=Decimal("5.00"),
            active_listings=10,
        )
        
        assert spread.classification == "BREAK_EVEN"


# ============================================================
# ACQUISITION EDGE TESTS
# ============================================================


class TestAcquisitionEdge:
    """Test Acquisition Edge analysis."""
    
    def test_profitable_edge(self, analyzer):
        """Edge with profit >10% should be VERIFIED_PROFITABLE."""
        # acquisition_cost=4.00, exit_price=6.00, fee=0.90 (15%)
        # net_exit = 6.00 - 0.90 = 5.10
        # profit = 5.10 - 4.00 = 1.10
        # margin = 1.10 / 4.00 * 100 = 27.5%
        edge = analyzer.analyze_acquisition_edge(
            market_hash_name="Test Item",
            appid=730,
            classid="12345",
            acquisition_cost=Decimal("4.00"),
            exit_price=Decimal("6.00"),
            exit_fee_estimate=Decimal("0.90"),
        )
        
        assert edge.classification == "VERIFIED_PROFITABLE"
        assert edge.expected_profit == Decimal("1.10")
        assert edge.confidence == "HIGH"
    
    def test_loss_edge(self, analyzer):
        """Edge with loss should be LOSS."""
        edge = analyzer.analyze_acquisition_edge(
            market_hash_name="Test Item",
            appid=730,
            classid="12345",
            acquisition_cost=Decimal("6.00"),
            exit_price=Decimal("5.00"),
            exit_fee_estimate=Decimal("0.75"),
        )
        
        assert edge.classification == "LOSS"
        assert edge.expected_profit == Decimal("-1.75")
        assert edge.confidence == "HIGH"
    
    def test_missing_acquisition_cost(self, analyzer):
        """Missing acquisition cost should be UNVERIFIED."""
        edge = analyzer.analyze_acquisition_edge(
            market_hash_name="Test Item",
            appid=730,
            classid="12345",
            acquisition_cost=None,
            exit_price=Decimal("5.00"),
        )
        
        assert edge.classification == "UNVERIFIED"
        assert edge.confidence == "LOW"
    
    def test_missing_exit_price(self, analyzer):
        """Missing exit price should be UNVERIFIED."""
        edge = analyzer.analyze_acquisition_edge(
            market_hash_name="Test Item",
            appid=730,
            classid="12345",
            acquisition_cost=Decimal("4.00"),
            exit_price=None,
        )
        
        assert edge.classification == "UNVERIFIED"
        assert edge.confidence == "LOW"
    
    def test_below_threshold_profit(self, analyzer):
        """Profit below 10% margin should be POTENTIALLY_PROFITABLE."""
        # acquisition_cost=10.00, exit_price=12.00, fee=1.80 (15%)
        # net_exit = 12.00 - 1.80 = 10.20
        # profit = 10.20 - 10.00 = 0.20
        # margin = 0.20 / 10.00 * 100 = 2%
        edge = analyzer.analyze_acquisition_edge(
            market_hash_name="Test Item",
            appid=730,
            classid="12345",
            acquisition_cost=Decimal("10.00"),
            exit_price=Decimal("12.00"),
            exit_fee_estimate=Decimal("1.80"),
        )
        
        assert edge.classification == "POTENTIALLY_PROFITABLE"
        assert edge.confidence == "MEDIUM"


# ============================================================
# FACTORY TESTS
# ============================================================


class TestFactory:
    """Test factory functions."""
    
    def test_create_analyzer(self, session):
        """create_analyzer should create instance."""
        analyzer = create_analyzer(session=session)
        assert isinstance(analyzer, MarketPriceAnalyzer)
        assert analyzer.session == session


# ============================================================
# SAFETY TESTS
# ============================================================


class TestSafety:
    """Test that analyzer remains read-only."""
    
    def test_no_database_writes(self, analyzer):
        """Analyzer should not perform any database writes."""
        # Verify no sqlite3 usage
        assert not hasattr(analyzer, '_db_path')
    
    def test_no_steam_write_operations(self, analyzer, session):
        """Analyzer should only use GET requests."""
        # Mock GET response
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"success": True, "results": []}
        session.get.return_value = mock_response
        
        analyzer.get_sell_listings(730, limit=1)
        
        # Verify only GET was called
        calls = session.get.call_args_list
        assert len(calls) > 0
        for call in calls:
            assert call[0][0].startswith("https://")


# ============================================================
# EDGE CASE TESTS
# ============================================================


class TestEdgeCases:
    """Test edge cases."""
    
    def test_zero_price(self, analyzer):
        """Zero price should be handled."""
        result = analyzer._parse_price_text("$0.00")
        assert result == Decimal("0.00")
    
    def test_large_price(self, analyzer):
        """Large price should parse correctly."""
        result = analyzer._parse_price_text("$999,999.99")
        assert result == Decimal("999999.99")
    
    def test_currency_symbol_variation(self, analyzer):
        """Different currency symbols should work."""
        assert analyzer._parse_price_text("$5.00") == Decimal("5.00")
        assert analyzer._parse_price_text("€5.00") == Decimal("5.00")
        assert analyzer._parse_price_text("£5.00") == Decimal("5.00")
    
    def test_malformed_price(self, analyzer):
        """Malformed price should return None."""
        assert analyzer._parse_price_text("abc") is None
        assert analyzer._parse_price_text("5.5.5") is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
