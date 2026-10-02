"""
V0.7.0 — P&L Module

Unrealized P&L for known-cost inventory only.

Does NOT:
- Choose FIFO/LIFO/weighted-average allocation policy
- Infer SELL transactions
- Fabricate acquisition costs
- Use floats for monetary calculations
- Calculate realized P&L

Uses existing app.economic.py for fee/proceeds calculations where applicable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

from economic import calculate_total_fees, calculate_net
from position_engine import PositionState


@dataclass(frozen=True, slots=True)
class UnrealizedPnL:
    """
    Unrealized P&L for known-cost inventory only.

    If a position contains both known-cost and unknown-cost inventory,
    only the known-cost portion is reported here. Unknown-cost exposure
    is reported separately via PositionState.
    """

    market_hash_name: str
    known_cost_basis: Optional[Decimal]  # None if no known-cost inventory
    current_net_realizable_value: Optional[Decimal]  # net proceeds after fees
    unrealized_pnl: Optional[Decimal]  # net_realizable_value - known_cost_basis
    known_quantity: int  # remaining quantity with known cost
    unknown_quantity: int  # remaining quantity with unknown cost

    def has_known_cost(self) -> bool:
        return self.known_cost_basis is not None and self.known_cost_basis > 0

    def has_unknown_cost(self) -> bool:
        return self.unknown_quantity > 0

    def is_profitable(self) -> Optional[bool]:
        """True if unrealized P&L is positive. False if negative. None if unknown."""
        if self.unrealized_pnl is None:
            return None
        return self.unrealized_pnl > 0


def _to_decimal(value) -> Optional[Decimal]:
    """Convert value to Decimal, treating None as None."""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def compute_unrealized_pnl(
    position: PositionState,
    current_unit_price,
    game_fee_rate=None,
) -> UnrealizedPnL:
    """
    Compute unrealized P&L for known-cost inventory only.

    Args:
        position: PositionState from position_engine.
        current_unit_price: Current market unit price (Decimal, int, str, or None).
        game_fee_rate: Optional game-specific fee rate (float, Decimal, or None).

    Returns:
        UnrealizedPnL with known-cost P&L and unknown-cost exposure.

    Raises:
        ValueError: If position is empty.
    """
    # The lots themselves may be empty (nothing acquired) or fully consumed
    # (nothing remaining); both are reported with the same wording so
    # callers can rely on "empty position" as the contract.
    if position.is_empty():
        raise ValueError("cannot compute P&L for empty position")

    known_quantity = position.quantity_remaining - position.quantity_unknown_cost

    # If no known-cost inventory, return zero-cost P&L
    if not position.has_known_cost():
        return UnrealizedPnL(
            market_hash_name=position.market_hash_name,
            known_cost_basis=None,
            current_net_realizable_value=None,
            unrealized_pnl=None,
            known_quantity=0,
            unknown_quantity=position.quantity_unknown_cost,
        )

    # Calculate gross proceeds for known-cost quantity only
    unit_price = _to_decimal(current_unit_price)
    if unit_price is None:
        return UnrealizedPnL(
            market_hash_name=position.market_hash_name,
            known_cost_basis=position.known_cost_basis,
            current_net_realizable_value=None,
            unrealized_pnl=None,
            known_quantity=known_quantity,
            unknown_quantity=position.quantity_unknown_cost,
        )

    # Gross proceeds = unit_price * known_quantity
    gross_proceeds = unit_price * Decimal(str(known_quantity))

    # Net realizable value = gross - total fees
    total_fees = calculate_total_fees(gross_proceeds, game_fee_rate)
    if total_fees is None:
        net_realizable = None
    else:
        net_realizable = gross_proceeds - total_fees

    # Unrealized P&L = net_realizable - known_cost_basis
    if net_realizable is None or position.known_cost_basis is None:
        unrealized_pnl = None
    else:
        unrealized_pnl = net_realizable - position.known_cost_basis

    return UnrealizedPnL(
        market_hash_name=position.market_hash_name,
        known_cost_basis=position.known_cost_basis,
        current_net_realizable_value=net_realizable,
        unrealized_pnl=unrealized_pnl,
        known_quantity=known_quantity,
        unknown_quantity=position.quantity_unknown_cost,
    )


def compute_unrealized_pnl_for_all_positions(
    positions: dict[str, PositionState],
    current_unit_prices: dict[str, Decimal],
    game_fee_rate=None,
) -> dict[str, UnrealizedPnL]:
    """
    Compute unrealized P&L for all positions.

    Args:
        positions: Dict mapping market_hash_name -> PositionState.
        current_unit_prices: Dict mapping market_hash_name -> current unit price.
        game_fee_rate: Optional game-specific fee rate.

    Returns:
        Dict mapping market_hash_name -> UnrealizedPnL.
    """
    result: dict[str, UnrealizedPnL] = {}
    for name, position in positions.items():
        price = current_unit_prices.get(name)
        result[name] = compute_unrealized_pnl(position, price, game_fee_rate)
    return result


__all__ = [
    "UnrealizedPnL",
    "compute_unrealized_pnl",
    "compute_unrealized_pnl_for_all_positions",
]
