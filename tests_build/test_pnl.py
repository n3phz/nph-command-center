import sys
sys.path.insert(0, "app")
"""
V0.7.0 — Focused tests for pnl.py

Tests cover:
- known remaining cost basis
- current net realizable value
- unrealized P&L for known-cost quantity
- explicit unknown-cost exposure
- Decimal-only arithmetic
- rejection of float accounting
- no fabricated historical costs
- no SELL inference
"""

from decimal import Decimal
import pytest

from transactions import (
    AcquisitionLot,
    CostStatus,
    Transaction,
    TransactionType,
)
from position_engine import compute_position, PositionState
from pnl import (
    UnrealizedPnL,
    compute_unrealized_pnl,
    compute_unrealized_pnl_for_all_positions,
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


def test_known_cost_basis():
    """Known cost basis from tracked lots only."""
    lot = make_tracked_lot("Test Item", 5, "10.00")
    pos = compute_position([lot])

    assert pos.known_cost_basis == Decimal("50.00")
    assert pos.quantity_unknown_cost == 0


def test_current_net_realizable_value():
    """Net realizable value includes Steam fee deduction."""
    lot = make_tracked_lot("Test Item", 2, "10.00")
    pos = compute_position([lot])

    # current price = 12.00, quantity = 2, gross = 24.00
    # Steam fee = max(5% of 24.00, 0.01) = 1.20
    # net = 24.00 - 1.20 = 22.80
    pnl = compute_unrealized_pnl(pos, Decimal("12.00"))

    assert pnl.current_net_realizable_value == Decimal("22.80")
    # Cost basis is remaining_quantity * unit_cost = 2 * 10.00 = 20.00.
    # (The previous 50.00 here was copied from the five-unit fixture in
    # test_known_cost_basis and never matched this two-unit lot.)
    assert pnl.known_cost_basis == Decimal("20.00")


def test_unrealized_pnl_positive():
    """Unrealized P&L positive when net realizable value exceeds cost basis."""
    lot = make_tracked_lot("Test Item", 1, "10.00")
    pos = compute_position([lot])

    # current price = 15.00, gross = 15.00
    # Steam fee = max(5% of 15.00, 0.01) = 0.75
    # net = 15.00 - 0.75 = 14.25
    # unrealized = 14.25 - 10.00 = 4.25
    pnl = compute_unrealized_pnl(pos, Decimal("15.00"))

    assert pnl.unrealized_pnl == Decimal("4.25")
    assert pnl.is_profitable() is True


def test_unrealized_pnl_negative():
    """Unrealized P&L negative when cost basis exceeds net realizable value."""
    lot = make_tracked_lot("Test Item", 1, "10.00")
    pos = compute_position([lot])

    # current price = 5.00, gross = 5.00
    # Steam fee = max(5% of 5.00, 0.01) = 0.25
    # net = 5.00 - 0.25 = 4.75
    # unrealized = 4.75 - 10.00 = -5.25
    pnl = compute_unrealized_pnl(pos, Decimal("5.00"))

    assert pnl.unrealized_pnl == Decimal("-5.25")
    assert pnl.is_profitable() is False


def test_unknown_cost_exposure():
    """Unknown-cost exposure is reported separately from known cost."""
    tracked = make_tracked_lot("Mixed Item", 3, "8.00")
    unknown = make_unknown_lot("Mixed Item", 7)
    pos = compute_position([tracked, unknown])

    assert pos.quantity_unknown_cost == 7
    assert pos.known_cost_basis == Decimal("24.00")

    pnl = compute_unrealized_pnl(pos, Decimal("10.00"))

    assert pnl.known_quantity == 3
    assert pnl.unknown_quantity == 7
    assert pnl.has_unknown_cost() is True
    assert pnl.has_known_cost() is True


def test_mixed_preserves_distinction():
    """Mixed position: known cost basis is never claimed as entire position."""
    tracked = make_tracked_lot("Split Item", 2, "5.00")
    unknown = make_unknown_lot("Split Item", 8)
    pos = compute_position([tracked, unknown])

    assert pos.quantity_remaining == 10
    assert pos.quantity_unknown_cost == 8
    assert pos.known_cost_basis == Decimal("10.00")

    pnl = compute_unrealized_pnl(pos, Decimal("6.00"))

    assert pnl.known_quantity == 2
    assert pnl.unknown_quantity == 8
    assert pnl.known_cost_basis == Decimal("10.00")
    assert pnl.current_net_realizable_value == Decimal("11.40")
    assert pnl.unrealized_pnl == Decimal("1.40")


def test_no_realized_pnl_calculation():
    """Realized P&L is not calculated by this module."""
    lot = make_tracked_lot("Test Item", 5, "10.00")
    pos = compute_position([lot])

    pnl = compute_unrealized_pnl(pos, Decimal("12.00"))

    assert not hasattr(pnl, "realized_pnl")
    assert not hasattr(pnl, "realized_profit")


def test_unknown_cost_never_fabricated():
    """No acquisition cost is fabricated from current market price."""
    tracked = make_tracked_lot("Test Item", 2, "8.00")
    unknown = make_unknown_lot("Test Item", 3)
    pos = compute_position([tracked, unknown])

    assert pos.known_cost_basis == Decimal("16.00")
    assert pos.quantity_unknown_cost == 3

    pnl = compute_unrealized_pnl(pos, Decimal("999.00"))
    assert pnl.known_cost_basis == Decimal("16.00")
    assert pnl.unknown_quantity == 3


def test_no_sell_inference():
    """No SELL transaction is inferred from position data."""
    tracked = make_tracked_lot("Test Item", 5, "10.00")
    pos = compute_position([tracked])

    assert pos.quantity_acquired == 5
    assert pos.quantity_remaining == 5
    assert pos.quantity_unknown_cost == 0


def test_decimal_only_arithmetic():
    """All monetary calculations use Decimal, not float."""
    lot = make_tracked_lot("Test Item", 3, "3.33")
    pos = compute_position([lot])

    assert isinstance(pos.known_cost_basis, Decimal)

    pnl = compute_unrealized_pnl(pos, Decimal("5.55"))

    assert isinstance(pnl.current_net_realizable_value, Decimal)
    assert isinstance(pnl.unrealized_pnl, Decimal)
    assert not isinstance(pnl.current_net_realizable_value, float)
    assert not isinstance(pnl.unrealized_pnl, float)


def test_none_current_price():
    """None current price yields None net realizable value and unrealized P&L."""
    lot = make_tracked_lot("Test Item", 2, "10.00")
    pos = compute_position([lot])

    pnl = compute_unrealized_pnl(pos, None)

    assert pnl.current_net_realizable_value is None
    assert pnl.unrealized_pnl is None
    assert pnl.known_cost_basis == Decimal("20.00")
    assert pnl.known_quantity == 2
    assert pnl.unknown_quantity == 0


def test_empty_position_raises():
    """Empty position raises ValueError."""
    # Cannot construct a zero-quantity TRACKED lot (contract requires qty > 0),
    # so build an empty PositionState directly for this guard test.
    empty_position = PositionState(
        market_hash_name="Test Item",
        quantity_acquired=0,
        quantity_remaining=0,
        quantity_unknown_cost=0,
        known_cost_basis=None,
        tracked_lot_count=0,
        unknown_lot_count=0,
    )
    with pytest.raises(ValueError, match="empty position"):
        compute_unrealized_pnl(empty_position, Decimal("10.00"))
