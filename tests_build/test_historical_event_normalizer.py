import sys
sys.path.insert(0, "app")
"""Tests for the V0.5.4 historical event normalizer."""

from dataclasses import FrozenInstanceError, fields
from decimal import Decimal

import pytest

from market_history_adapter import MarketHistoryEvent
from historical_event_normalizer import (
    HistoricalEventNormalizationError,
    NormalizedHistoricalEvent,
    normalize_market_history_event,
    normalize_market_history_events,
)


def _make_event(**overrides):
    base = dict(
        type="BUY",
        market_hash_name="Example Card",
        quantity=3,
        unit_price=Decimal("0.42"),
        fees=Decimal("0.06"),
        total_value=Decimal("1.26"),
        timestamp="2026-09-14T19:00:00Z",
        external_ref="steam-buy-001",
    )
    base.update(overrides)
    return MarketHistoryEvent(**base)


# --- Basic normalization ----------------------------------------------------


def test_valid_buy():
    event = _make_event(type="BUY")
    normalized = normalize_market_history_event(event)

    assert normalized.type == "BUY"
    assert normalized.market_hash_name == "Example Card"
    assert normalized.quantity == 3
    assert normalized.unit_price == Decimal("0.42")
    assert normalized.fees == Decimal("0.06")
    assert normalized.total_value == Decimal("1.26")
    assert normalized.timestamp == "2026-09-14T19:00:00Z"
    assert normalized.external_ref == "steam-buy-001"
    assert normalized.cost_status == "UNKNOWN"


def test_valid_sell():
    event = _make_event(
        type="SELL",
        unit_price=Decimal("1.10"),
        total_value=Decimal("1.10"),
        external_ref="steam-sell-001",
    )
    normalized = normalize_market_history_event(event)

    assert normalized.type == "SELL"
    assert normalized.external_ref == "steam-sell-001"
    assert normalized.unit_price == Decimal("1.10")
    assert normalized.total_value == Decimal("1.10")


# --- Decimal preservation ---------------------------------------------------


def test_decimal_unit_price_preserved():
    event = _make_event(unit_price=Decimal("2.50"))
    normalized = normalize_market_history_event(event)

    assert normalized.unit_price == Decimal("2.50")
    assert isinstance(normalized.unit_price, Decimal)


def test_decimal_total_value_preserved():
    event = _make_event(total_value=Decimal("15.00"))
    normalized = normalize_market_history_event(event)

    assert normalized.total_value == Decimal("15.00")
    assert isinstance(normalized.total_value, Decimal)


# --- None preservation ------------------------------------------------------


def test_fees_none_remains_none():
    event = _make_event(fees=None)
    normalized = normalize_market_history_event(event)

    assert normalized.fees is None


def test_explicit_fees_preserved():
    event = _make_event(fees=Decimal("0.10"))
    normalized = normalize_market_history_event(event)

    assert normalized.fees == Decimal("0.10")


def test_timestamp_none_remains_none():
    event = _make_event(timestamp=None)
    normalized = normalize_market_history_event(event)

    assert normalized.timestamp is None


def test_explicit_timestamp_preserved():
    event = _make_event(timestamp="2025-01-02T03:04:05Z")
    normalized = normalize_market_history_event(event)

    assert normalized.timestamp == "2025-01-02T03:04:05Z"


# --- cost_status ------------------------------------------------------------


def test_cost_status_is_unknown():
    event = _make_event()
    normalized = normalize_market_history_event(event)

    assert normalized.cost_status == "UNKNOWN"


def test_no_acquisition_cost_field():
    field_names = {f.name for f in fields(NormalizedHistoricalEvent)}

    assert "acquisition_cost" not in field_names


# --- external_ref -----------------------------------------------------------


def test_external_ref_preserved_exact():
    event = _make_event(external_ref="history_row_abc_123")
    normalized = normalize_market_history_event(event)

    assert normalized.external_ref == "history_row_abc_123"


# --- Rejection cases --------------------------------------------------------


def test_empty_market_hash_name_rejected():
    event = _make_event(market_hash_name="")
    with pytest.raises(HistoricalEventNormalizationError, match="market_hash_name"):
        normalize_market_history_event(event)


def test_quantity_zero_rejected():
    event = _make_event(quantity=0)
    with pytest.raises(HistoricalEventNormalizationError, match="quantity"):
        normalize_market_history_event(event)


def test_quantity_negative_rejected():
    event = _make_event(quantity=-1)
    with pytest.raises(HistoricalEventNormalizationError, match="quantity"):
        normalize_market_history_event(event)


def test_negative_unit_price_rejected():
    event = _make_event(unit_price=Decimal("-0.01"))
    with pytest.raises(HistoricalEventNormalizationError, match="unit_price"):
        normalize_market_history_event(event)


def test_negative_fees_rejected():
    event = _make_event(fees=Decimal("-0.01"))
    with pytest.raises(HistoricalEventNormalizationError, match="fees"):
        normalize_market_history_event(event)


def test_empty_external_ref_rejected():
    event = _make_event(external_ref="")
    with pytest.raises(HistoricalEventNormalizationError, match="external_ref"):
        normalize_market_history_event(event)


def test_invalid_event_type_rejected():
    event = _make_event(type="TRADE")  # type: ignore[arg-type]
    with pytest.raises(HistoricalEventNormalizationError, match="type"):
        normalize_market_history_event(event)


# --- Sequence normalization -------------------------------------------------


def test_multiple_events_normalized():
    events = [
        _make_event(type="BUY", external_ref="ref-1"),
        _make_event(type="SELL", unit_price=Decimal("1.00"), total_value=Decimal("1.00"), external_ref="ref-2"),
    ]

    normalized = normalize_market_history_events(events)

    assert len(normalized) == 2
    assert normalized[0].type == "BUY"
    assert normalized[0].external_ref == "ref-1"
    assert normalized[1].type == "SELL"
    assert normalized[1].external_ref == "ref-2"


# --- Source immutability ----------------------------------------------------


def test_source_event_not_mutated():
    event = _make_event()
    original_fees = event.fees
    original_ts = event.timestamp

    normalize_market_history_event(event)

    assert event.fees is original_fees
    assert event.timestamp is original_ts
    assert event == _make_event()


# --- Immutability of output -------------------------------------------------


def test_normalized_event_is_immutable():
    event = _make_event()
    normalized = normalize_market_history_event(event)

    with pytest.raises(FrozenInstanceError):
        normalized.quantity = 99
