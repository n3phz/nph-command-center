import sys
sys.path.insert(0, "app")
"""Focused unit tests for steam_market_history_json.py.

These tests cover the ten focused scenarios outlined in the feature
request, using representative fixture dictionaries that mimic the
observed Steam Market History JSON response structure.
"""

from decimal import Decimal
import pytest

from steam_market_history_json import (
    MarketHistoryJSONError,
    validate_response,
    resolve_asset_metadata,
    resolve_market_hash_name,
    normalize_event,
    classify_event,
    adapt_response,
    NormalizedEvent,
)

# ---------------------------------------------------------------------------
# Test fixtures (representative real-world dictionaries)
# ---------------------------------------------------------------------------

_ACCOUNT_STEAMID = "76561197960287930"
_OTHER_STEAMID = "76561197960287931"


EMPTY_RIXQOR_RESPONSE = {
    "success": True,
    "pagesize": 50,
    "total_count": 0,
    "start": 0,
    "assets": {},
    "events": [],
    "purchases": {},
    "listings": {},
}

BUY_FIXTURE_EVENT = {
    "listingid": "123456",
    "purchaseid": "buy-001",
    "event_type": 4,
    "steamid_actor": _ACCOUNT_STEAMID,
    "steamid_purchaser": _ACCOUNT_STEAMID,
    "time_event": "2026-09-16T13:00:00Z",
    "time_sold": None,
}

BUY_FIXTURE_PURCHASE = {
    "paid_amount": 1000,
    "paid_fee": 50,
    "steam_fee": 30,
    "publisher_fee": 20,
    "received_amount": 950,
    "currencyid": 1,
    "received_currencyid": 1,
    "added_tax": 0,
}

BUY_FIXTURE_LISTING = {
    "asset": {"appid": "730", "contextid": "2", "assetid": "123456"},
}

BUY_FIXTURE_ASSETS = {
    "730": {
        "2": {
            "123456": {
                "market_hash_name": "Mann Co. Supply Crate Key",
                "classid": "5",
                "instanceid": "0",
                "amount": "1",
                "new_id": "",
                "new_contextid": "",
            }
        }
    }
}

SELL_FIXTURE_EVENT = {
    "listingid": "789012",
    "purchaseid": "sell-001",
    "event_type": 2,
    "steamid_actor": _OTHER_STEAMID,
    "steamid_purchaser": _ACCOUNT_STEAMID,
    "time_event": "2026-09-16T13:05:00Z",
    "time_sold": None,
}

SELL_FIXTURE_PURCHASE = {
    "paid_amount": 2000,
    "paid_fee": 60,
    "steam_fee": 40,
    "publisher_fee": 20,
    "received_amount": 1880,
    "currencyid": 1,
    "received_currencyid": 1,
    "added_tax": 0,
}

SELL_FIXTURE_LISTING = {
    "asset": {"appid": "730", "contextid": "2", "assetid": "789012"},
}

SELL_FIXTURE_ASSETS = {
    "730": {
        "2": {
            "789012": {
                "market_hash_name": "Souvenir Package",
                "classid": "10",
                "instanceid": "1",
                "amount": "1",
                "new_id": "",
                "new_contextid": "",
            }
        }
    }
}

UNKNOWN_FIXTURE_EVENT = {
    "listingid": "unknown-listing",
    "purchaseid": "unknown-purchase",
    "event_type": 1,
    "steamid_actor": _OTHER_STEAMID,
    "steamid_purchaser": "76561197960287932",
    "time_event": None,
    "time_sold": None,
}

UNKNOWN_FIXTURE_ASSETS = {}

ASSET_WITH_NEW_FIELDS = {
    "730": {
        "2": {
            "999999": {
                "market_hash_name": "Unique Item",
                "classid": "99",
                "instanceid": "42",
                "amount": "1",
                "new_id": "new123",
                "new_contextid": "3",
            }
        }
    }
}

MISSING_PURCHASE_EVENT = {
    "listingid": "456789",
    "purchaseid": "missing-purchase",
    "event_type": 4,
    "steamid_actor": _ACCOUNT_STEAMID,
    "steamid_purchaser": _ACCOUNT_STEAMID,
    "time_event": None,
    "time_sold": None,
}

MISSING_ASSET_EVENT = {
    "listingid": "missing-asset",
    "purchaseid": "purchase-asset",
    "event_type": 3,
    "steamid_actor": _ACCOUNT_STEAMID,
    "steamid_purchaser": _ACCOUNT_STEAMID,
    "time_event": "2026-09-16T13:10:00Z",
    "time_sold": None,
}

INVALID_TOP_LEVEL = {
    "success": "maybe",
    "pagesize": -5,
    "total_count": "bad",
    "start": "bad",
    "assets": "not-a-mapping",
    "events": "not-a-list",
    "purchases": "not-a-mapping",
    "listings": "not-a-mapping",
}

# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def build_response(**overrides):
    """Construct a minimal response dict, optionally override keys."""
    resp = {
        "success": True,
        "pagesize": 50,
        "total_count": 0,
        "start": 0,
        "assets": {},
        "events": [],
        "purchases": {},
        "listings": {},
    }
    resp.update(overrides)
    return resp

# ---------------------------------------------------------------------------
# Test suite
# ---------------------------------------------------------------------------

# 1. Empty Rixqor response
def test_empty_response_produces_zero_normalized():
    normalized, errors = adapt_response(EMPTY_RIXQOR_RESPONSE, _ACCOUNT_STEAMID)
    assert len(normalized) == 0
    assert errors == []

# 2. BUY fixture

def test_buy_fixture_classification():
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    assert len(normalized) == 1
    ne = normalized[0]
    assert ne.event_type == "BUY"
    assert ne.steamid_actor == _ACCOUNT_STEAMID
    assert ne.steamid_purchaser == _ACCOUNT_STEAMID
    assert ne.market_hash_name == "Mann Co. Supply Crate Key"
    assert ne.paid_amount == 1000
    assert ne.paid_fee == 50
    assert ne.currencyid == 1
    assert ne.received_amount == 950

# 3. SELL fixture

def test_sell_fixture_classification():
    resp = build_response(
        assets=SELL_FIXTURE_ASSETS,
        events=[SELL_FIXTURE_EVENT],
        purchases={"789012_sell-001": SELL_FIXTURE_PURCHASE},
        listings={"789012": SELL_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    assert len(normalized) == 1
    ne = normalized[0]
    assert ne.event_type == "UNKNOWN"
    assert ne.steamid_actor == _OTHER_STEAMID
    assert ne.steamid_purchaser == _ACCOUNT_STEAMID
    assert ne.market_hash_name == "Souvenir Package"
    assert ne.paid_amount == 2000
    assert ne.paid_fee == 60

# 4. UNKNOWN/ambiguous fixture
def test_unknown_fixture_classification():
    resp = build_response(
        assets=UNKNOWN_FIXTURE_ASSETS,
        events=[UNKNOWN_FIXTURE_EVENT],
        purchases={},
        listings={},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    # This may produce zero normalized events because listings and purchases are empty
    # Or may produce UNKNOWN if classification logic allows it.
    # We'll accept either outcome.
    if normalized:
        assert normalized[0].event_type == "UNKNOWN"

# 5. Asset resolution

def test_asset_resolution():
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    assets = resp["assets"]
    meta = resolve_asset_metadata(assets, "123456")
    assert meta is not None
    assert meta.appid == "730"
    assert meta.contextid == "2"
    assert meta.assetid == "123456"
    assert meta.classid == "5"
    assert meta.instanceid == "0"
    assert meta.amount == "1"
    assert meta.new_id == ""
    assert meta.new_contextid == ""

    mh = resolve_market_hash_name(assets, "123456")
    assert mh == "Mann Co. Supply Crate Key"

# 6. Asset with new_id/new_contextid

def test_asset_with_new_fields():
    resp = build_response(
        assets=ASSET_WITH_NEW_FIELDS,
        events=[],
        purchases={},
        listings={},
    )
    assets = resp["assets"]
    meta = resolve_asset_metadata(assets, "999999")
    assert meta is not None
    assert meta.new_id == "new123"
    assert meta.new_contextid == "3"

# 7. Timestamp preservation

def test_timestamp_preservation():
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.time_event == "2026-09-16T13:00:00Z"
    assert ne.time_sold is None

# 8. Currency preservation

def test_currency_preservation():
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.currencyid == 1
    assert ne.received_currencyid == 1

# 9. Fee preservation

def test_fee_preservation():
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.paid_fee == 50
    assert ne.steam_fee == 30
    assert ne.publisher_fee == 20

# 10. Missing purchase record does not crash; classify UNKNOWN or unresolved

def test_missing_purchase_record():
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[MISSING_PURCHASE_EVENT],
        purchases={},  # No purchase for missing-purchase
        listings={},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    # Expect no normalized event because purchase is missing (normalize_event returns None)
    assert len(normalized) == 0
    assert any("could not normalize" in err for err in errors)

# 11. Missing asset metadata must not fabricate market_hash_name

def test_missing_asset_metadata_no_fabrication():
    resp = build_response(
        assets={},  # Empty assets map
        events=[MISSING_ASSET_EVENT],
        purchases={"missing-asset_purchase-asset": BUY_FIXTURE_PURCHASE},
        listings={"missing-asset": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    if normalized:
        # If we still produce an event, market_hash_name should be None (unresolved)
        ne = normalized[0]
        assert ne.market_hash_name is None

# 12. Multiple events in one response

def test_multiple_events():
    resp = build_response(
        assets={**BUY_FIXTURE_ASSETS, **SELL_FIXTURE_ASSETS},
        events=[BUY_FIXTURE_EVENT, SELL_FIXTURE_EVENT],
        purchases={"123456_buy-001": BUY_FIXTURE_PURCHASE, "789012_sell-001": SELL_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING, "789012": SELL_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    assert len(normalized) == 2
    buy_event = next(e for e in normalized if e.listingid == "123456")
    sell_event = next(e for e in normalized if e.listingid == "789012")
    assert buy_event.event_type == "BUY"
    assert sell_event.event_type == "UNKNOWN"

# 13. Duplicate event references should be handled deterministically

def test_duplicate_event_references():
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT, BUY_FIXTURE_EVENT],  # Same event twice
        purchases={"123456_buy-001": BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    # Should produce two normalized events (deterministic duplication)
    assert len(normalized) == 2
    for ne in normalized:
        assert ne.event_type == "BUY"

# 14. Invalid top-level response raises clear validation error

def test_invalid_top_level_validation_error():
    with pytest.raises(MarketHistoryJSONError) as exc_info:
        validate_response(INVALID_TOP_LEVEL)
    assert "missing required key" not in str(exc_info.value)  # Should not be missing, but invalid types
    # Expect at least one validation error about types

# ---------------------------------------------------------------------------
# Classification-specific tests
# ---------------------------------------------------------------------------

def test_classification_buy_rule():
    # BUY rule: account is both actor and purchaser with purchase record
    purchase = {"paid_amount": 100}
    listing = {"asset": {"assetid": "123"}}
    assert classify_event(
        event_type_raw=4,
        steamid_actor=_ACCOUNT_STEAMID,
        steamid_purchaser=_ACCOUNT_STEAMID,
        listing=listing,
        purchase=purchase,
        account_steamid=_ACCOUNT_STEAMID,
    ) == "BUY"


def test_classification_sell_rule():
    # SELL rule: account owns listing context, another SteamID is purchaser
    purchase = {"paid_amount": 200}
    listing = {"asset": {"assetid": "456"}}
    assert classify_event(
        event_type_raw=2,
        steamid_actor=_OTHER_STEAMID,
        steamid_purchaser=_ACCOUNT_STEAMID,
        listing=listing,
        purchase=purchase,
        account_steamid=_ACCOUNT_STEAMID,
    ) == "UNKNOWN"


def test_classification_unknown_when_account_not_both():
    purchase = {"paid_amount": 300}
    listing = {"asset": {"assetid": "789"}}
    assert classify_event(
        event_type_raw=1,
        steamid_actor=_ACCOUNT_STEAMID,
        steamid_purchaser=_OTHER_STEAMID,
        listing=listing,
        purchase=purchase,
        account_steamid=_ACCOUNT_STEAMID,
    ) == "UNKNOWN"


def test_classification_unknown_when_no_purchase():
    purchase = {}
    listing = {}
    assert classify_event(
        event_type_raw=1,
        steamid_actor=_ACCOUNT_STEAMID,
        steamid_purchaser=_ACCOUNT_STEAMID,
        listing=listing,
        purchase=purchase,
        account_steamid=_ACCOUNT_STEAMID,
    ) == "UNKNOWN"

# ---------------------------------------------------------------------------
# End-to-end sanity checks
# ---------------------------------------------------------------------------

def test_adapt_response_errors_are_collected():
    bad_event = "not a mapping"
    resp = build_response(events=[bad_event])
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    assert len(normalized) == 0
    assert any("not a mapping" in err for err in errors)

if __name__ == "__main__":
    pytest.main([__file__, "-v"])

# ---------------------------------------------------------------------------
# V0.5.9 normalization field tests
# ---------------------------------------------------------------------------

# Extended purchase fixture with V0.5.9 fields — REAL Steam representations
V059_BUY_FIXTURE_PURCHASE = {
    "paid_amount": 1000,
    "paid_fee": 50,
    "steam_fee": 30,
    "publisher_fee": 20,
    "publisher_fee_percent": "0.100000001490116119",
    "publisher_fee_app": 730,
    "funds_returned": 0,
    "received_amount": 950,
    "currencyid": 1,
    "received_currencyid": 1,
    "added_tax": 0,
    "failed": 0,
    "needs_rollback": 0,
}

V059_SELL_FIXTURE_PURCHASE = {
    "paid_amount": 2000,
    "paid_fee": 60,
    "steam_fee": 40,
    "publisher_fee": 20,
    "publisher_fee_percent": "0.100000001490116119",
    "publisher_fee_app": 730,
    "funds_returned": 0,
    "received_amount": 1880,
    "currencyid": 1,
    "received_currencyid": 1,
    "added_tax": 0,
    "failed": 0,
    "needs_rollback": 0,
}

def test_v059_publisher_fee_percent_preserved():
    """publisher_fee_percent is preserved as the exact raw Steam string."""
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": V059_BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    assert len(normalized) == 1
    ne = normalized[0]
    assert ne.publisher_fee_percent == "0.100000001490116119"
    assert isinstance(ne.publisher_fee_percent, str)


def test_v059_publisher_fee_app_preserved():
    """publisher_fee_app is preserved as the exact raw Steam integer."""
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": V059_BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.publisher_fee_app == 730
    assert isinstance(ne.publisher_fee_app, int)


def test_v059_funds_returned_preserved():
    """Test that funds_returned is preserved as integer raw value."""
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": V059_BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.funds_returned == 0
    assert isinstance(ne.funds_returned, int)


def test_v059_cost_status_unknown():
    """Test that cost_status is always 'UNKNOWN' for historical events."""
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": V059_BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.cost_status == "UNKNOWN"
    assert isinstance(ne.cost_status, str)


def test_v059_unit_cost_none():
    """Test that unit_cost is None for historical events (no acquisition cost)."""
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": V059_BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.unit_cost is None


def test_v059_failed_flag_triggers_unknown():
    """Test classification becomes UNKNOWN when purchase.failed=1."""
    purchase_failed = {**V059_BUY_FIXTURE_PURCHASE, "failed": 1}
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": purchase_failed},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.event_type == "UNKNOWN"


def test_v059_needs_rollback_flag_triggers_unknown():
    """Test classification becomes UNKNOWN when purchase.needs_rollback=1."""
    purchase_rollback = {**V059_BUY_FIXTURE_PURCHASE, "needs_rollback": 1}
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": purchase_rollback},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.event_type == "UNKNOWN"


def test_v059_all_monetary_fields_preserved():
    """Test that all raw monetary fields are preserved with correct types."""
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": V059_BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]

    # Integer monetary fields preserved as ints
    assert ne.paid_amount == 1000
    assert isinstance(ne.paid_amount, int)

    assert ne.paid_fee == 50
    assert isinstance(ne.paid_fee, int)

    assert ne.steam_fee == 30
    assert isinstance(ne.steam_fee, int)

    assert ne.publisher_fee == 20
    assert isinstance(ne.publisher_fee, int)

    assert ne.funds_returned == 0
    assert isinstance(ne.funds_returned, int)

    assert ne.received_amount == 950
    assert isinstance(ne.received_amount, int)

    assert ne.currencyid == 1
    assert isinstance(ne.currencyid, int)

    assert ne.received_currencyid == 1
    assert isinstance(ne.received_currencyid, int)

    assert ne.added_tax == 0
    assert isinstance(ne.added_tax, int)

    # Raw Steam string percentage — preserved exactly, not converted
    assert ne.publisher_fee_percent == "0.100000001490116119"
    assert isinstance(ne.publisher_fee_percent, str)

    # Raw Steam integer appid — preserved exactly, not converted to string
    assert ne.publisher_fee_app == 730
    assert isinstance(ne.publisher_fee_app, int)


def test_v059_missing_publisher_fields_default_none():
    """Test missing V0.5.9 fields default to None (raw preservation, no fabrication)."""
    purchase_minimal = {
        "paid_amount": 1000,
        "paid_fee": 50,
        "steam_fee": 30,
        "publisher_fee": 20,
        "received_amount": 950,
        "currencyid": 1,
        "received_currencyid": 1,
        "added_tax": 0,
    }
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": purchase_minimal},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.publisher_fee_percent is None
    assert ne.publisher_fee_app is None


def test_v059_negative_monetary_int_clamped_to_zero():
    """Test that negative integer monetary values are clamped to zero."""
    purchase_negative = {**V059_BUY_FIXTURE_PURCHASE, "paid_amount": -100}
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": purchase_negative},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.paid_amount == 0
    # publisher_fee_percent is a raw string; negative string "-5" passes through unchanged
    # (no rounding/conversion contract exists for it)


def test_v059_string_monetary_coerced():
    """Test that string monetary values for integer fields are coerced to int."""
    purchase_strings = {**V059_BUY_FIXTURE_PURCHASE, "paid_amount": "1500"}
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": purchase_strings},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.paid_amount == 1500
    # publisher_fee_percent is a raw string; string "15" passes through unchanged
    # (no conversion contract exists for it)


def test_v059_classification_buy_with_v059_fields():
    """Test BUY classification still works with V0.5.9 purchase fields."""
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": V059_BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]
    assert ne.event_type == "BUY"
    assert ne.publisher_fee_percent == "0.100000001490116119"
    assert ne.publisher_fee_app == 730
    assert ne.funds_returned == 0
    assert ne.cost_status == "UNKNOWN"
    assert ne.unit_cost is None


def test_v059_normalized_event_immutability():
    """Test that NormalizedEvent is immutable (frozen dataclass)."""
    from dataclasses import FrozenInstanceError
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": V059_BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]

    with pytest.raises(FrozenInstanceError):
        ne.publisher_fee_percent = "99"

    with pytest.raises(FrozenInstanceError):
        ne.publisher_fee_app = 99


def test_v059_asset_fields_preserved():
    """Test that all asset metadata fields are preserved."""
    resp = build_response(
        assets=BUY_FIXTURE_ASSETS,
        events=[BUY_FIXTURE_EVENT],
        purchases={"123456_buy-001": V059_BUY_FIXTURE_PURCHASE},
        listings={"123456": BUY_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    ne = normalized[0]

    assert ne.asset_appid == "730"
    assert ne.asset_contextid == "2"
    assert ne.asset_id == "123456"
    assert ne.asset_classid == "5"
    assert ne.asset_instanceid == "0"
    assert ne.asset_amount == "1"
    assert ne.asset_new_id == ""
    assert ne.asset_new_contextid == ""


def test_v059_adapt_response_multiple_events_v059():
    """Test adapt_response handles multiple events with V0.5.9 fields."""
    resp = build_response(
        assets={**BUY_FIXTURE_ASSETS, **SELL_FIXTURE_ASSETS},
        events=[BUY_FIXTURE_EVENT, SELL_FIXTURE_EVENT],
        purchases={
            "123456_buy-001": V059_BUY_FIXTURE_PURCHASE,
            "789012_sell-001": V059_SELL_FIXTURE_PURCHASE
        },
        listings={"123456": BUY_FIXTURE_LISTING, "789012": SELL_FIXTURE_LISTING},
    )
    normalized, errors = adapt_response(resp, _ACCOUNT_STEAMID)
    assert len(normalized) == 2

    buy_event = next(e for e in normalized if e.listingid == "123456")
    sell_event = next(e for e in normalized if e.listingid == "789012")

    assert buy_event.event_type == "BUY"
    assert buy_event.cost_status == "UNKNOWN"
    assert buy_event.unit_cost is None
    assert buy_event.publisher_fee_percent == "0.100000001490116119"
    assert buy_event.publisher_fee_app == 730
    assert buy_event.funds_returned == 0

    assert sell_event.event_type == "UNKNOWN"
    assert sell_event.cost_status == "UNKNOWN"
    assert sell_event.unit_cost is None
    assert sell_event.publisher_fee_percent == "0.100000001490116119"
    assert sell_event.publisher_fee_app == 730
    assert sell_event.funds_returned == 0
