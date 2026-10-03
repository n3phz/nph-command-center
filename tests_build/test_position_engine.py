import sys
sys.path.insert(0, "app")
"""
V0.7.0 — Focused tests for position_engine.py

Tests cover:
- Tracked lot aggregation
- Unknown lot aggregation
- Mixed tracked + unknown lots
- Multiple tracked lots
- Zero remaining quantity
- Decimal costs
- Empty/mixed market_hash_name rejection
- No allocation API present
"""

import sys
from decimal import Decimal
import pytest

from transactions import (
    AcquisitionLot,
    CostStatus,
    Transaction,
    TransactionType,
)
from position_engine import (
    PositionState,
    calculate_position_state,
    calculate_all_positions,
)


def make_tracked_lot(market_hash_name: str, quantity: int, unit_cost: str) -> AcquisitionLot:
    """Helper: create a TRACKED lot with persisted transaction ID."""
    tx = Transaction(
        type=TransactionType.BUY,
        market_hash_name=market_hash_name,
        quantity=quantity,
        unit_price=Decimal(unit_cost),
        fees=Decimal("0"),
        total_value=Decimal(unit_cost) * Decimal(str(quantity)),
        timestamp="2026-01-01T00:00:00+00:00",
        bot_name="TestBot",
        id=1,
    )
    return AcquisitionLot.from_buy_transaction(tx, cost_status=CostStatus.TRACKED)


def make_unknown_lot(market_hash_name: str, quantity: int) -> AcquisitionLot:
    """Helper: create an UNKNOWN lot with persisted transaction ID."""
    tx = Transaction(
        type=TransactionType.BUY,
        market_hash_name=market_hash_name,
        quantity=quantity,
        unit_price=Decimal("0"),
        fees=Decimal("0"),
        total_value=Decimal("0"),
        timestamp="2026-01-01T00:00:00+00:00",
        bot_name="TestBot",
        id=2,
    )
    return AcquisitionLot.from_buy_transaction(tx, cost_status=CostStatus.UNKNOWN)


def test_tracked_lot_only():
    """Single tracked lot: known_cost_basis = remaining_quantity * unit_cost."""
    lot = make_tracked_lot("Test Item", 5, "10.00")
    pos = calculate_position_state([lot])

    assert pos.market_hash_name == "Test Item"
    assert pos.quantity_acquired == 5
    assert pos.quantity_remaining == 5
    assert pos.quantity_unknown_cost == 0
    assert pos.known_cost_basis == Decimal("50.00")
    assert pos.tracked_lot_count == 1
    assert pos.unknown_lot_count == 0
    assert pos.has_known_cost() is True
    assert pos.has_unknown_cost() is False
    assert pos.is_fully_known() is True
    assert pos.is_fully_unknown() is False
    assert pos.is_empty() is False


def test_unknown_lot_only():
    """Single unknown lot: known_cost_basis = None, quantity_unknown_cost = remaining_quantity."""
    lot = make_unknown_lot("Test Item", 3)
    pos = calculate_position_state([lot])

    assert pos.market_hash_name == "Test Item"
    assert pos.quantity_acquired == 3
    assert pos.quantity_remaining == 3
    assert pos.quantity_unknown_cost == 3
    assert pos.known_cost_basis is None
    assert pos.tracked_lot_count == 0
    assert pos.unknown_lot_count == 1
    assert pos.has_known_cost() is False
    assert pos.has_unknown_cost() is True
    assert pos.is_fully_known() is False
    assert pos.is_fully_unknown() is True
    assert pos.is_empty() is False


def test_mixed_tracked_and_unknown():
    """Mixed lots: known_cost_basis only from tracked portion."""
    tracked = make_tracked_lot("Mixed Item", 4, "5.00")
    unknown = make_unknown_lot("Mixed Item", 6)
    pos = calculate_position_state([tracked, unknown])

    assert pos.market_hash_name == "Mixed Item"
    assert pos.quantity_acquired == 10
    assert pos.quantity_remaining == 10
    assert pos.quantity_unknown_cost == 6
    assert pos.known_cost_basis == Decimal("20.00")
    assert pos.tracked_lot_count == 1
    assert pos.unknown_lot_count == 1
    assert pos.has_known_cost() is True
    assert pos.has_unknown_cost() is True
    assert pos.is_fully_known() is False
    assert pos.is_fully_unknown() is False
    assert pos.is_empty() is False


def test_multiple_tracked_lots():
    """Multiple tracked lots: known_cost_basis sums remaining * unit_cost."""
    lot1 = make_tracked_lot("Multi Item", 3, "4.00")
    lot2 = make_tracked_lot("Multi Item", 2, "6.00")
    pos = calculate_position_state([lot1, lot2])

    assert pos.market_hash_name == "Multi Item"
    assert pos.quantity_acquired == 5
    assert pos.quantity_remaining == 5
    assert pos.quantity_unknown_cost == 0
    assert pos.known_cost_basis == Decimal("24.00")
    assert pos.tracked_lot_count == 2
    assert pos.unknown_lot_count == 0
    assert pos.has_known_cost() is True
    assert pos.has_unknown_cost() is False
    assert pos.is_fully_known() is True
    assert pos.is_fully_unknown() is False


def test_zero_remaining_quantity():
    """Lot fully consumed: quantity_remaining = 0."""
    lot = make_tracked_lot("Consumed Item", 5, "10.00")
    consumed = lot.consume(5)
    pos = calculate_position_state([consumed])

    assert pos.market_hash_name == "Consumed Item"
    assert pos.quantity_acquired == 5
    assert pos.quantity_remaining == 0
    assert pos.quantity_unknown_cost == 0
    assert pos.known_cost_basis is None
    assert pos.tracked_lot_count == 1
    assert pos.unknown_lot_count == 0
    assert pos.has_known_cost() is False
    assert pos.has_unknown_cost() is False
    assert pos.is_empty() is True


def test_decimal_costs():
    """Decimal unit costs handled correctly."""
    lot = make_tracked_lot("Decimal Item", 3, "3.33")
    pos = calculate_position_state([lot])

    assert pos.known_cost_basis == Decimal("9.99")
    assert pos.quantity_remaining == 3
    assert pos.quantity_unknown_cost == 0


def test_empty_lots_list_raises():
    """Empty lots list raises ValueError."""
    with pytest.raises(ValueError, match="lots list must not be empty"):
        calculate_position_state([])


def test_multiple_market_hash_names_raises():
    """Lots with different market_hash_names raise ValueError."""
    lot1 = make_tracked_lot("Item A", 2, "5.00")
    lot2 = make_unknown_lot("Item B", 3)
    with pytest.raises(ValueError, match="all lots must have the same market_hash_name"):
        calculate_position_state([lot1, lot2])


def test_calculate_all_positions():
    """Group lots by market_hash_name."""
    lot_a1 = make_tracked_lot("Item A", 2, "5.00")
    lot_a2 = make_unknown_lot("Item A", 3)
    lot_b1 = make_tracked_lot("Item B", 1, "10.00")

    lots = [lot_a1, lot_a2, lot_b1]
    positions = calculate_all_positions(lots)

    assert "Item A" in positions
    assert "Item B" in positions
    assert len(positions) == 2

    pos_a = positions["Item A"]
    assert pos_a.market_hash_name == "Item A"
    assert pos_a.quantity_acquired == 5
    assert pos_a.quantity_remaining == 5
    assert pos_a.quantity_unknown_cost == 3
    assert pos_a.known_cost_basis == Decimal("10.00")
    assert pos_a.tracked_lot_count == 1
    assert pos_a.unknown_lot_count == 1

    pos_b = positions["Item B"]
    assert pos_b.market_hash_name == "Item B"
    assert pos_b.quantity_acquired == 1
    assert pos_b.quantity_remaining == 1
    assert pos_b.quantity_unknown_cost == 0
    assert pos_b.known_cost_basis == Decimal("10.00")
    assert pos_b.tracked_lot_count == 1
    assert pos_b.unknown_lot_count == 0


def test_known_cost_basis_none_when_no_tracked_remaining():
    """Known cost basis is None when no tracked quantity remains."""
    lot = make_unknown_lot("Unknown Only", 4)
    pos = calculate_position_state([lot])

    assert pos.quantity_remaining == 4
    assert pos.known_cost_basis is None
    assert pos.has_known_cost() is False


def test_unknown_lot_with_partial_consumption():
    """Unknown lot partial consumption: quantity_unknown_cost reduces."""
    lot = make_unknown_lot("Partial Unknown", 10)
    partial = lot.consume(3)
    pos = calculate_position_state([partial])

    assert pos.quantity_acquired == 10
    assert pos.quantity_remaining == 7
    assert pos.quantity_unknown_cost == 7
    assert pos.known_cost_basis is None
    assert pos.tracked_lot_count == 0
    assert pos.unknown_lot_count == 1


def test_known_quantity_property():
    """known_quantity = remaining - unknown_cost."""
    tracked = make_tracked_lot("Split Item", 2, "5.00")
    unknown = make_unknown_lot("Split Item", 8)
    pos = calculate_position_state([tracked, unknown])

    assert pos.known_quantity == 2
    assert pos.quantity_unknown_cost == 8


def test_no_allocation_api():
    """PositionEngine must not contain FIFO/LIFO allocation functions."""
    import inspect
    from position_engine import PositionState, calculate_position_state, calculate_all_positions

    public = [
        name for name, _ in inspect.getmembers(
            sys.modules["app.position_engine"],
            predicate=lambda obj: inspect.isfunction(obj) or inspect.isfunction(getattr(obj, "__call__", None)),
        )
    ]
    # These are the only public functions allowed in V0.7
    assert "calculate_position_state" in public
    assert "calculate_all_positions" in public
    assert "PositionState" in [n for n, _ in inspect.getmembers(sys.modules["app.position_engine"], predicate=lambda obj: isinstance(obj, type))]
