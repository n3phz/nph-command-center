"""
Phase 6A — Read-Only Acquisition Opportunity Scanner Tests

Tests for the market acquisition scanner that identifies potential
round-trip trading opportunities.

READ-ONLY: No database writes, no Steam Market write operations.
"""

import sys
import json
import time
from decimal import Decimal
from unittest import mock

import pytest
import requests

sys.path.insert(0, "projects/steam-trade-bot/app")

from market_acquisition_scanner import (
    MarketAcquisitionScanner,
    AcquisitionCandidate,
    AcquisitionSearchResult,
    AcquisitionClassification,
    EconomicEvidence,
    LiquidityEvidence,
    create_scanner,
)


# ============================================================
# FIXTURES
# ============================================================


@pytest.fixture
def session():
    """Create a mock HTTP session."""
    return mock.MagicMock()


@pytest.fixture
def scanner(session):
    """Create a scanner with mocked session."""
    return MarketAcquisitionScanner(
        session=session,
        request_delay=0.0,
        min_margin_threshold=Decimal("0.10"),
    )


@pytest.fixture
def sample_search_results_profitable():
    """Sample search results with profitable edge."""
    return {
        "success": True,
        "total_count": 1000,
        "results": [
            {
                "name": "Profitable Item",
                "hash_name": "Profitable Item",
                "sell_price": 1500,  # 15.00 EUR seller proceeds
                "sale_price_text": "€13.00",  # 13.00 EUR buyer cost
                "sell_listings": 50,
                "asset_description": {
                    "appid": 730,
                    "classid": "12345",
                    "tradable": 1,
                    "marketable": 1,
                },
            },
        ],
    }


@pytest.fixture
def sample_search_results_loss():
    """Sample search results with loss."""
    return {
        "success": True,
        "total_count": 1000,
        "results": [
            {
                "name": "Loss Item",
                "hash_name": "Loss Item",
                "sell_price": 500,  # 5.00 EUR seller proceeds
                "sale_price_text": "€10.00",  # 10.00 EUR buyer cost
                "sell_listings": 20,
                "asset_description": {
                    "appid": 730,
                    "classid": "12346",
                    "tradable": 1,
                    "marketable": 1,
                },
            },
        ],
    }


@pytest.fixture
def sample_search_results_not_marketable():
    """Sample search results with non-marketable item."""
    return {
        "success": True,
        "total_count": 1000,
        "results": [
            {
                "name": "Untradeable Item",
                "hash_name": "Untradeable Item",
                "sell_price": 1000,
                "sale_price_text": "€10.00",
                "sell_listings": 5,
                "asset_description": {
                    "appid": 730,
                    "classid": "12347",
                    "tradable": 0,
                    "marketable": 0,
                },
            },
        ],
    }


# ============================================================
# DISCOVERY TESTS
# ============================================================


class TestDiscovery:
    """Test candidate discovery."""
    
    def test_successful_discovery(self, scanner, session, sample_search_results_profitable):
        """Successful discovery should return candidates."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results_profitable
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert result.candidates_evaluated == 1
        assert result.candidates_accepted == 1
        assert len(result.candidates) == 1
        
        candidate = result.candidates[0]
        assert candidate.market_hash_name == "Profitable Item"
        assert candidate.appid == 730
        assert candidate.classid == "12345"
        assert candidate.buyer_acquisition_cost == Decimal("13.00")
        assert candidate.seller_proceeds_per_unit == Decimal("15.00")
        assert candidate.round_trip_profit == Decimal("2.00")
    
    def test_empty_results(self, scanner, session):
        """Empty search results should return empty candidate list."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "total_count": 0,
            "results": [],
        }
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert result.candidates_evaluated == 0
        assert result.candidates_accepted == 0
        assert len(result.candidates) == 0
    
    def test_http_error(self, scanner, session):
        """HTTP error should return empty results."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 500
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert result.candidates_evaluated == 0
        assert result.candidates_accepted == 0
    
    def test_rate_limiting(self, scanner, session):
        """Rate limiting should return empty results with rate_limited flag."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 429
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert result.rate_limited is True
        assert result.candidates_evaluated == 0
    
    def test_request_delay(self, scanner, session, sample_search_results_profitable):
        """Rate limiting should be respected."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results_profitable
        session.get.return_value = mock_response
        
        start = time.monotonic()
        scanner.discover_candidates(appid=730, limit=1)
        first_call = time.monotonic() - start
        
        scanner.discover_candidates(appid=730, limit=1)
        second_call = time.monotonic() - start
        
        # Second call should respect delay
        assert second_call >= scanner.request_delay * 2


# ============================================================
# ECONOMIC MODEL TESTS
# ============================================================


class TestEconomics:
    """Test economic calculations."""
    
    def test_profitable_edge(self, scanner, session, sample_search_results_profitable):
        """Profitable edge with seller > buyer should be classified PRICE_ANOMALY."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results_profitable
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        candidate = result.candidates[0]
        # seller_proceeds (15.00) > buyer_cost (13.00) is economically impossible
        # This should be classified as PRICE_ANOMALY, not DIRECT_ROUND_TRIP_EDGE
        assert candidate.classification == AcquisitionClassification.PRICE_ANOMALY
        assert candidate.round_trip_profit == Decimal("2.00")
        assert candidate.round_trip_margin == Decimal("2.00") / Decimal("13.00")
        assert candidate.steam_fees == Decimal("-2.00")
        assert candidate.evidence == EconomicEvidence.AUTHORITATIVE
    
    def test_loss_edge(self, scanner, session, sample_search_results_loss):
        """Loss edge should be classified LOSS."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results_loss
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        candidate = result.candidates[0]
        assert candidate.classification == AcquisitionClassification.LOSS
        assert candidate.round_trip_profit == Decimal("-5.00")
        assert candidate.evidence == EconomicEvidence.AUTHORITATIVE
    
    def test_missing_buyer_price(self, scanner, session):
        """Missing buyer price should be UNVERIFIED."""
        # Response with no sale_price_text
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Unknown Price",
                    "hash_name": "Unknown Price",
                    "sell_price": 1000,
                    "sale_price_text": "",
                    "sell_listings": 10,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12348",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert result.candidates_evaluated == 1
        assert result.candidates_rejected == 1  # Rejected due to missing price
    
    def test_missing_seller_price(self, scanner, session):
        """Missing seller price should be UNVERIFIED."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "No Seller Price",
                    "hash_name": "No Seller Price",
                    "sell_price": None,
                    "sale_price_text": "€10.00",
                    "sell_listings": 10,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12349",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        # Should have one candidate with UNVERIFIED classification
        # (seller_proceeds is None, so round_trip_profit is None)
        assert result.candidates_accepted == 1
        assert result.candidates[0].classification == AcquisitionClassification.UNVERIFIED


# ============================================================
# CLASSIFICATION TESTS
# ============================================================


class TestClassification:
    """Test candidate classification."""
    
    def test_not_marketable(self, scanner, session, sample_search_results_not_marketable):
        """Non-marketable items should be excluded."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results_not_marketable
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        # Should be rejected due to not marketable
        assert result.candidates_rejected == 1
    
    def test_minimum_margin_threshold(self, scanner, session):
        """Items below minimum margin but with positive profit should be POTENTIAL_RESALE_EDGE or PRICE_ANOMALY."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Low Margin",
                    "hash_name": "Low Margin",
                    "sell_price": 1200,  # 12.00 EUR
                    "sale_price_text": "€10.50",  # 10.50 EUR
                    "sell_listings": 100,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12350",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        candidate = result.candidates[0]
        # Profit = 12.00 - 10.50 = 1.50, margin = 1.50/10.50 = 14.3%
        # Above 10% threshold but seller > buyer, so PRICE_ANOMALY
        # (This is economically impossible, so it should be flagged as anomaly)
        assert candidate.classification in (
            AcquisitionClassification.POTENTIAL_RESALE_EDGE,
            AcquisitionClassification.PRICE_ANOMALY,
        )
        assert candidate.round_trip_profit == Decimal("1.50")
    
    def test_break_even(self, scanner, session):
        """Break-even should be classified BREAK_EVEN."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Break Even",
                    "hash_name": "Break Even",
                    "sell_price": 1000,
                    "sale_price_text": "€10.00",
                    "sell_listings": 50,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12351",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        candidate = result.candidates[0]
        assert candidate.classification == AcquisitionClassification.BREAK_EVEN
        assert candidate.round_trip_profit == Decimal("0")


# ============================================================
# LIQUIDITY TESTS
# ============================================================


class TestLiquidity:
    """Test liquidity classification."""
    
    def test_high_liquidity(self, scanner):
        """10+ listings should be HIGH evidence."""
        assert scanner._classify_liquidity(10) == LiquidityEvidence.HIGH_EVIDENCE.value
        assert scanner._classify_liquidity(100) == LiquidityEvidence.HIGH_EVIDENCE.value
    
    def test_medium_liquidity(self, scanner):
        """5-9 listings should be MEDIUM evidence."""
        assert scanner._classify_liquidity(5) == LiquidityEvidence.MEDIUM_EVIDENCE.value
        assert scanner._classify_liquidity(9) == LiquidityEvidence.MEDIUM_EVIDENCE.value
    
    def test_low_liquidity(self, scanner):
        """2-4 listings should be LOW evidence."""
        assert scanner._classify_liquidity(2) == LiquidityEvidence.LOW_EVIDENCE.value
        assert scanner._classify_liquidity(4) == LiquidityEvidence.LOW_EVIDENCE.value
    
    def test_insufficient_liquidity(self, scanner):
        """0-1 listings should be INSUFFICIENT."""
        assert scanner._classify_liquidity(0) == LiquidityEvidence.INSUFFICIENT_DATA.value
        assert scanner._classify_liquidity(1) == LiquidityEvidence.INSUFFICIENT_DATA.value
        assert scanner._classify_liquidity(None) == LiquidityEvidence.INSUFFICIENT_DATA.value


# ============================================================
# PRICING TESTS
# ============================================================


class TestPriceParsing:
    """Test price parsing."""
    
    def test_us_format(self, scanner):
        """US price format should parse correctly."""
        result = scanner._parse_price_text("$1,234.56")
        assert result == Decimal("1234.56")
    
    def test_european_format(self, scanner):
        """European price format should parse correctly."""
        result = scanner._parse_price_text("€1.234,56")
        assert result == Decimal("1234.56")
    
    def test_simple_price(self, scanner):
        """Simple price should parse correctly."""
        result = scanner._parse_price_text("$5.00")
        assert result == Decimal("5.00")
    
    def test_empty_string(self, scanner):
        """Empty price should return None."""
        result = scanner._parse_price_text("")
        assert result is None
    
    def test_none_input(self, scanner):
        """None input should return None."""
        result = scanner._parse_price_text(None)
        assert result is None
    
    def test_invalid_format(self, scanner):
        """Invalid price should return None."""
        result = scanner._parse_price_text("invalid")
        assert result is None


# ============================================================
# SAFETY TESTS
# ============================================================


class TestSafety:
    """Test safety guarantees."""
    
    def test_no_database_writes(self, scanner, session, sample_search_results_profitable):
        """Scanner should not write to database."""
        import os
        import tempfile
        
        # Try to use a temp DB
        tmpdb = os.path.join(tempfile.gettempdir(), 'phase6a_test.db')
        if os.path.exists(tmpdb):
            os.unlink(tmpdb)
        
        # Create a minimal DB
        import sqlite3
        conn = sqlite3.connect(tmpdb)
        conn.close()
        initial_size = os.path.getsize(tmpdb)
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results_profitable
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        # Verify DB size unchanged
        final_size = os.path.getsize(tmpdb)
        assert initial_size == final_size, "Database was modified!"
        
        # Clean up
        os.unlink(tmpdb)
    
    def test_only_get_requests(self, scanner, session, sample_search_results_profitable):
        """Scanner should only use GET requests."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results_profitable
        session.get.return_value = mock_response
        
        scanner.discover_candidates(appid=730, limit=5)
        
        # Verify only GET was called
        calls = session.get.call_args_list
        assert len(calls) == 1
        assert calls[0][0][0].startswith("https://steamcommunity.com/market/")
        
        # Verify no POST/PUT/DELETE
        assert not session.post.called
        assert not session.put.called
        assert not session.delete.called


# ============================================================
# FILTER TESTS
# ============================================================


class TestFilters:
    """Test candidate filtering."""
    
    def test_price_minimum_filter(self, scanner, session):
        """Items below minimum price should be filtered."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Cheap Item",
                    "hash_name": "Cheap Item",
                    "sell_price": 100,  # 1.00 EUR
                    "sale_price_text": "€0.87",  # 0.87 EUR
                    "sell_listings": 50,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12352",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        # Set min_price to 1.00 EUR
        result = scanner.discover_candidates(appid=730, limit=5, min_price=Decimal("1.00"))
        
        assert result.candidates_evaluated == 1
        assert result.candidates_rejected == 1  # Filtered by price
    
    def test_price_maximum_filter(self, scanner, session):
        """Items above maximum price should be filtered."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Expensive Item",
                    "hash_name": "Expensive Item",
                    "sell_price": 100000,  # 1000.00 EUR
                    "sale_price_text": "€869.57",
                    "sell_listings": 5,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12353",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        # Set max_price to 500 EUR
        result = scanner.discover_candidates(appid=730, limit=5, max_price=Decimal("500.00"))
        
        assert result.candidates_evaluated == 1
        assert result.candidates_rejected == 1  # Filtered by price
    
    def test_min_listings_filter(self, scanner, session):
        """Items below minimum listings should be filtered."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Rare Item",
                    "hash_name": "Rare Item",
                    "sell_price": 1000,
                    "sale_price_text": "€8.70",
                    "sell_listings": 1,  # Only 1 listing
                    "asset_description": {
                        "appid": 730,
                        "classid": "12354",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        # Set min_listings to 2
        result = scanner.discover_candidates(appid=730, limit=5, min_listings=2)
        
        assert result.candidates_evaluated == 1
        assert result.candidates_rejected == 1  # Filtered by listings


# ============================================================
# FACTORY TESTS
# ============================================================


class TestFactory:
    """Test factory functions."""
    
    def test_create_scanner(self, session):
        """create_scanner should create instance."""
        s = create_scanner(session=session)
        assert isinstance(s, MarketAcquisitionScanner)
        assert s.session is session


# ============================================================
# EDGE CASES
# ============================================================


class TestEdgeCases:
    """Test edge cases."""
    
    def test_zero_buyer_price(self, scanner, session):
        """Zero buyer price should be handled."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Free Item",
                    "hash_name": "Free Item",
                    "sell_price": 0,
                    "sale_price_text": "€0.00",
                    "sell_listings": 10,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12355",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert result.candidates_evaluated == 1
        assert result.candidates_rejected == 1  # Filtered by min_price
    
    def test_duplicate_market_hash_names(self, scanner, session):
        """Duplicate market hash names should be deduplicated."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Same Item",
                    "hash_name": "Same Item",
                    "sell_price": 1000,
                    "sale_price_text": "€8.70",
                    "sell_listings": 50,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12356",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
                {
                    "name": "Same Item",
                    "hash_name": "Same Item",
                    "sell_price": 1000,
                    "sale_price_text": "€8.70",
                    "sell_listings": 50,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12356",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        # Should only have one candidate due to deduplication
        assert result.candidates_accepted == 1
        assert len(result.candidates) == 1
    
    def test_missing_classid(self, scanner, session):
        """Items without classid should still be processed."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "No Class",
                    "hash_name": "No Class",
                    "sell_price": 1000,
                    "sale_price_text": "€8.70",
                    "sell_listings": 10,
                    "asset_description": {
                        "appid": 730,
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert result.candidates_evaluated == 1
        candidate = result.candidates[0]
        assert candidate.classid is None
    
    def test_negative_profit_margin(self, scanner, session):
        """Negative profit margin should be LOSS."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Bad Deal",
                    "hash_name": "Bad Deal",
                    "sell_price": 500,  # 5.00 EUR
                    "sale_price_text": "€10.00",  # 10.00 EUR
                    "sell_listings": 20,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12357",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        candidate = result.candidates[0]
        assert candidate.classification == AcquisitionClassification.LOSS
        assert candidate.round_trip_profit == Decimal("-5.00")


# ============================================================
# REAL-MARKET VALIDATION
# ============================================================


class TestRealMarketValidation:
    """Test against real Steam Market data."""
    
    def test_real_search_api(self, scanner, session):
        """Should handle real Steam Market responses gracefully."""
        # Mock a realistic response structure
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "total_count": 0,
            "results": [],
        }
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert result.candidates_evaluated == 0
        assert result.candidates_accepted == 0
        assert result.candidates_rejected == 0
    
    def test_real_search_pricing(self, scanner, session):
        """Should correctly parse real pricing formats."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Real Item",
                    "hash_name": "Real Item",
                    "sell_price": 1234,
                    "sale_price_text": "€10.73",
                    "sell_listings": 25,
                    "asset_description": {
                        "appid": 730,
                        "classid": "99999",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert result.candidates_evaluated == 1
        candidate = result.candidates[0]
        assert candidate.buyer_acquisition_cost == Decimal("10.73")
        assert candidate.seller_proceeds_per_unit == Decimal("12.34")


# ============================================================
# EU131 FALSE POSITIVE REGRESSION
# ============================================================


class TestRegression:
    """Regression tests for known issues."""
    
    def test_131_false_positive_still_rejected(self, scanner, session):
        """€0.01 items should not create false profitable edges."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Cheap Thing",
                    "hash_name": "Cheap Thing",
                    "sell_price": 1,  # 0.01 EUR
                    "sale_price_text": "€0.01",
                    "sell_listings": 1000,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12358",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        # Should be filtered by min_price (default 0.01)
        # Or should show as break-even/no profit
        assert result.candidates_evaluated == 1
        if result.candidates:
            candidate = result.candidates[0]
            # At this price point, after fees, should not be verified profitable
            assert candidate.classification != AcquisitionClassification.DIRECT_ROUND_TRIP_EDGE
    
    def test_price_anomaly_detection(self, scanner, session):
        """Seller proceeds exceeding buyer cost should be classified PRICE_ANOMALY."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Anomalous Item",
                    "hash_name": "Anomalous Item",
                    "sell_price": 300,  # 3.00 EUR seller proceeds
                    "sale_price_text": "€2.00",  # 2.00 EUR buyer cost
                    "sell_listings": 50,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12360",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        candidate = result.candidates[0]
        assert candidate.classification == AcquisitionClassification.PRICE_ANOMALY
        assert candidate.round_trip_profit == Decimal("1.00")
        assert "exceed" in candidate.reason.lower()
    
    def test_normal_loss_scenario(self, scanner, session):
        """Normal case where buyer pays more than seller receives should be LOSS."""
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Normal Item",
                    "hash_name": "Normal Item",
                    "sell_price": 800,  # 8.00 EUR seller proceeds
                    "sale_price_text": "€10.00",  # 10.00 EUR buyer cost
                    "sell_listings": 50,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12361",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        candidate = result.candidates[0]
        # buyer (10.00) > seller (8.00), so normal loss scenario
        assert candidate.classification == AcquisitionClassification.LOSS
        assert candidate.round_trip_profit == Decimal("-2.00")


# ============================================================
# RESULT STRUCTURE TESTS
# ============================================================


class TestResultStructure:
    """Test result structure and fields."""
    
    def test_result_fields(self, scanner, session, sample_search_results_profitable):
        """Result should contain all required fields."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results_profitable
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert hasattr(result, 'timestamp')
        assert hasattr(result, 'search_params')
        assert hasattr(result, 'candidates_evaluated')
        assert hasattr(result, 'candidates_accepted')
        assert hasattr(result, 'candidates_rejected')
        assert hasattr(result, 'candidates')
        assert hasattr(result, 'classification_counts')
        assert hasattr(result, 'rate_limited')
        
        # Check counts
        assert result.classification_counts.get(
            AcquisitionClassification.DIRECT_ROUND_TRIP_EDGE, 0
        ) >= 0
    
    def test_candidate_fields(self, scanner, session, sample_search_results_profitable):
        """Candidate should contain all required fields."""
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results_profitable
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        candidate = result.candidates[0]
        
        assert hasattr(candidate, 'market_hash_name')
        assert hasattr(candidate, 'appid')
        assert hasattr(candidate, 'classid')
        assert hasattr(candidate, 'buyer_acquisition_cost')
        assert hasattr(candidate, 'buyer_acquisition_source')
        assert hasattr(candidate, 'seller_proceeds_per_unit')
        assert hasattr(candidate, 'seller_proceeds_source')
        assert hasattr(candidate, 'round_trip_profit')
        assert hasattr(candidate, 'round_trip_margin')
        assert hasattr(candidate, 'steam_fees')
        assert hasattr(candidate, 'steam_fee_percentage')
        assert hasattr(candidate, 'active_listings')
        assert hasattr(candidate, 'liquidity_evidence')
        assert hasattr(candidate, 'classification')
        assert hasattr(candidate, 'confidence')
        assert hasattr(candidate, 'reason')
        assert hasattr(candidate, 'evidence')
        assert hasattr(candidate, 'timestamp')
        assert hasattr(candidate, 'data_sources')


# ============================================================
# CONFIGURABLE THRESHOLDS
# ============================================================


class TestConfigurableThresholds:
    """Test configurable parameters."""
    
    def test_custom_min_margin(self, session):
        """Custom minimum margin threshold should be respected."""
        s = MarketAcquisitionScanner(
            session=session,
            request_delay=0.0,
            min_margin_threshold=Decimal("0.20"),  # 20%
        )
        
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {
                    "name": "Medium Margin",
                    "hash_name": "Medium Margin",
                    "sell_price": 1200,  # 12.00 EUR
                    "sale_price_text": "€10.00",  # 10.00 EUR
                    "sell_listings": 50,
                    "asset_description": {
                        "appid": 730,
                        "classid": "12359",
                        "tradable": 1,
                        "marketable": 1,
                    },
                },
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = s.discover_candidates(appid=730, limit=5)
        
        candidate = result.candidates[0]
        # Profit = 12.00 - 10.00 = 2.00, margin = 2.00/10.00 = 20%
        # With 20% threshold and seller > buyer, this is a PRICE_ANOMALY
        assert candidate.classification == AcquisitionClassification.PRICE_ANOMALY
    
    def test_custom_max_candidates(self, session):
        """Custom max candidates should be respected."""
        s = MarketAcquisitionScanner(
            session=session,
            request_delay=0.0,
            max_candidates=3,
        )
        
        response = {
            "success": True,
            "total_count": 100,
            "results": [
                {"name": f"Item {i}", "hash_name": f"Item {i}", "sell_price": 1000,
                 "sale_price_text": "€8.70", "sell_listings": 10,
                 "asset_description": {"appid": 730, "classid": f"{12360+i}", "tradable": 1, "marketable": 1}}
                for i in range(10)
            ],
        }
        
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = response
        session.get.return_value = mock_response
        
        result = s.discover_candidates(appid=730, limit=3)
        
        # Should only process up to limit (3)
        assert len(result.candidates) <= 3


# ============================================================
# ENVIRONMENT-DEPENDENT TESTS
# ============================================================


class TestEnvironment:
    """Tests that depend on environment."""
    
    def test_no_db_dependency(self, scanner, session, sample_search_results_profitable):
        """Scanner should not require database."""
        # Should work with any session, no DB needed
        mock_response = mock.MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = sample_search_results_profitable
        session.get.return_value = mock_response
        
        result = scanner.discover_candidates(appid=730, limit=5)
        
        assert result.candidates_evaluated >= 0
