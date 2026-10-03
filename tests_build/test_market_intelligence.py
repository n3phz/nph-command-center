import sys
sys.path.insert(0, "/workspace/projects/steam-trade-bot")

from decimal import Decimal
from unittest import mock

import market_intelligence as mi


SAMPLE_RECORD = {
    "market_hash_name": "Test Item",
    "app_id": 730,
    "currency": 1,
    "currency_name": "USD",
    "lowest_price": "$1.50",
    "median_price": "$2.00",
    "volume": 123,
    "lowest_price_value": 1.50,
    "median_price_value": 2.00,
    "fetched_at": "2024-01-01T00:00:00+00:00",
    "fetched_at_unix": 1700000000,
    "success": True,
    "error": None,
    "source": "steam_community",
    "cached": True,
}


def _patch_data(record):
    return mock.patch(
        "app.market_intelligence._get_market_data",
        return_value=record,
    )


def test_active_listing_count_returns_exactly_volume():
    """
    active_listing_count must equal the volume field only.
    Prices must NOT be included in the result.
    """
    with _patch_data(SAMPLE_RECORD) as patched:
        result = mi.get_active_listing_count("Test Item")
    assert result == 123
    assert patched.call_count == 1


def test_active_listing_count_missing_volume():
    record = dict(SAMPLE_RECORD)
    del record["volume"]
    with _patch_data(record):
        result = mi.get_active_listing_count("Test Item")
    assert result is None


def test_freshness_from_fetched_at_unix():
    record = dict(SAMPLE_RECORD)
    record["fetched_at_unix"] = 1700000000
    with mock.patch("app.market_intelligence.time") as t:
        t.time.return_value = 1700001000.0
        t.int = int
        with _patch_data(record):
            result = mi.get_market_freshness("Test Item")
    assert result == 1000


def test_freshness_missing_fetched_at_unix():
    record = dict(SAMPLE_RECORD)
    del record["fetched_at_unix"]
    with _patch_data(record):
        result = mi.get_market_freshness("Test Item")
    assert result is None


def test_freshness_invalid_fetched_at_unix():
    record = dict(SAMPLE_RECORD)
    record["fetched_at_unix"] = "not-a-number"
    with _patch_data(record):
        result = mi.get_market_freshness("Test Item")
    assert result is None


def test_lowest_price_value_returns_decimal():
    with _patch_data(SAMPLE_RECORD):
        result = mi.get_lowest_price_value("Test Item")
    assert result == Decimal("1.50")


def test_median_price_value_returns_decimal():
    with _patch_data(SAMPLE_RECORD):
        result = mi.get_median_price_value("Test Item")
    assert result == Decimal("2.00")


def test_missing_prices_return_none():
    record = dict(SAMPLE_RECORD)
    record["lowest_price_value"] = None
    record["median_price_value"] = None
    with _patch_data(record):
        assert mi.get_lowest_price_value("Test Item") is None
        assert mi.get_median_price_value("Test Item") is None


def test_no_fabricated_fields():
    with mock.patch(
        "app.market_intelligence._get_market_data",
        return_value=SAMPLE_RECORD,
    ):
        result = mi.get_market_price_info("Test Item")

    forbidden_fields = {
        "daily_volume",
        "liquidity",
        "volatility",
        "price_history",
        "history",
        "score",
        "arbitrary_score",
    }
    assert not (set(result) & forbidden_fields)
    assert set(result) == {
        "lowest_price",
        "median_price",
        "active_listing_count",
        "lowest_price_value",
        "median_price_value",
        "freshness_seconds",
    }


def test_get_market_price_info_single_retrieval():
    with mock.patch(
        "app.market_intelligence._get_market_data",
        return_value=SAMPLE_RECORD,
    ) as patched:
        result = mi.get_market_price_info("Test Item")
    assert patched.call_count == 1
    assert result["active_listing_count"] == 123
    assert result["lowest_price_value"] == Decimal("1.50")
    assert result["median_price_value"] == Decimal("2.00")
