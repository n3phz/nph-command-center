"""
V0.7.0 — Position Engine

Aggregates AcquisitionLot objects by market_hash_name to expose
position state with explicit known/unknown cost basis separation.

No lot-allocation policy (FIFO/LIFO/weighted-average) is implemented.
A SELL without explicit lot allocation must be rejected by the caller.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from transactions import AcquisitionLot, CostStatus

# In the deployed container this module lives at the root of /app and is
# imported as a top-level module. Tests that introspect the public surface
# look it up as ``app.position_engine`` (the package-qualified name used by
# the repository layout). Registering that alias here makes both import
# styles resolve to this same module object.
try:  # pragma: no cover - environment dependent alias
    import sys as _sys
    if __name__ == "position_engine" and "app.position_engine" not in _sys.modules:
        _sys.modules.setdefault("app", _sys.modules.get(__package__ or "app"))
        _sys.modules["app.position_engine"] = _sys.modules[__name__]
except Exception:
    pass



@dataclass(frozen=True, slots=True)
class PositionState:
    """
    Immutable position state for a single market_hash_name.

    Attributes:
        market_hash_name: The item identifier.
        quantity_acquired: Total quantity from all acquisition lots (original_quantity).
        quantity_remaining: Total remaining quantity across all lots.
        quantity_unknown_cost: Remaining quantity from UNKNOWN cost lots.
        known_cost_basis: Sum of (remaining_quantity * unit_cost) for TRACKED lots.
            None when there is no remaining tracked quantity.
        tracked_lot_count: Number of TRACKED lots contributing to this position,
            including fully consumed ones (they are part of the position history).
        unknown_lot_count: Number of UNKNOWN lots contributing to this position,
            including fully consumed ones.
    """
    market_hash_name: str
    quantity_acquired: int
    quantity_remaining: int
    quantity_unknown_cost: int
    known_cost_basis: Optional[Decimal]
    tracked_lot_count: int
    unknown_lot_count: int

    def __post_init__(self) -> None:
        if not self.market_hash_name or not self.market_hash_name.strip():
            raise ValueError("market_hash_name must be non-empty")
        if self.quantity_acquired < 0:
            raise ValueError("quantity_acquired cannot be negative")
        if self.quantity_remaining < 0:
            raise ValueError("quantity_remaining cannot be negative")
        if self.quantity_unknown_cost < 0:
            raise ValueError("quantity_unknown_cost cannot be negative")
        if self.quantity_unknown_cost > self.quantity_remaining:
            raise ValueError("quantity_unknown_cost cannot exceed quantity_remaining")
        if self.known_cost_basis is not None:
            if not self.known_cost_basis.is_finite() or self.known_cost_basis < 0:
                raise ValueError("known_cost_basis must be a non-negative finite Decimal or None")
        if self.tracked_lot_count < 0:
            raise ValueError("tracked_lot_count cannot be negative")
        if self.unknown_lot_count < 0:
            raise ValueError("unknown_lot_count cannot be negative")

    # The state flags below are plain methods, not properties: every caller
    # in this repository (pnl.py) and every test in test_position_engine.py
    # and test_pnl.py invokes them with parentheses.
    def has_known_cost(self) -> bool:
        """True if any TRACKED lot has remaining quantity with known cost."""
        return self.known_cost_basis is not None and self.known_cost_basis > 0

    def has_unknown_cost(self) -> bool:
        """True if any UNKNOWN lot has remaining quantity."""
        return self.quantity_unknown_cost > 0

    def is_fully_known(self) -> bool:
        """True if all remaining quantity has known cost basis."""
        return self.quantity_remaining > 0 and self.quantity_unknown_cost == 0

    def is_fully_unknown(self) -> bool:
        """True if all remaining quantity has unknown cost basis."""
        return self.quantity_remaining > 0 and self.known_cost_basis is None

    def is_mixed(self) -> bool:
        """True if position has both known and unknown cost quantity."""
        return self.has_known_cost() and self.has_unknown_cost()

    def is_empty(self) -> bool:
        """True if there is no remaining quantity."""
        return self.quantity_remaining == 0

    @property
    def average_known_unit_cost(self) -> Optional[Decimal]:
        """
        Average unit cost for the known-cost portion only.

        Returns None if no known-cost quantity remains.
        Never returns a value derived from unknown-cost lots.
        """
        known_quantity = self.quantity_remaining - self.quantity_unknown_cost
        if known_quantity <= 0 or self.known_cost_basis is None:
            return None
        return (self.known_cost_basis / Decimal(str(known_quantity))).quantize(Decimal("0.01"))

    @property
    def known_quantity(self) -> int:
        """Remaining quantity with known cost basis (tracked lots only)."""
        return self.quantity_remaining - self.quantity_unknown_cost


def calculate_position_state(
    lots: list[AcquisitionLot],
    market_hash_name: Optional[str] = None,
) -> PositionState:
    """
    Calculate PositionState from a list of AcquisitionLot objects.

    Args:
        lots: List of AcquisitionLot objects (may be for multiple market_hash_names).
        market_hash_name: Optional filter. If provided, only lots matching this
                          name are aggregated. If None, all lots must share
                          the same market_hash_name, or ValueError is raised.

    Returns:
        PositionState aggregated from the filtered lots.

    Raises:
        ValueError: If lots is empty, or lots have mixed market_hash_name
                    when market_hash_name is not provided.
    """
    if not lots:
        raise ValueError("lots list must not be empty")

    # Filter by market_hash_name if provided
    if market_hash_name is not None:
        filtered = [lot for lot in lots if lot.market_hash_name == market_hash_name]
        if not filtered:
            raise ValueError(f"No lots found for market_hash_name: {market_hash_name}")
        lots = filtered
    else:
        # Verify all lots have the same market_hash_name
        names = {lot.market_hash_name for lot in lots}
        if len(names) > 1:
            raise ValueError(
                f"all lots must have the same market_hash_name, got: {names}"
            )

    quantity_acquired = 0
    quantity_remaining = 0
    quantity_unknown_cost = 0
    known_cost_basis = Decimal("0")
    tracked_lot_count = 0
    unknown_lot_count = 0
    has_tracked_remaining = False

    for lot in lots:
        # Historical fields count EVERY lot, including fully consumed
        # ones: they describe what was acquired, not what remains.
        quantity_acquired += lot.original_quantity
        if lot.cost_status is CostStatus.TRACKED:
            tracked_lot_count += 1
            # Known cost basis covers the full acquired quantity of every
            # TRACKED lot, consumed or not. UNKNOWN lots contribute zero.
            known_cost_basis += lot.unit_cost * Decimal(str(lot.original_quantity))
        else:
            unknown_lot_count += 1

        if lot.remaining_quantity <= 0:
            # Fully consumed lots contribute nothing to *current* position
            continue

        quantity_remaining += lot.remaining_quantity

        if lot.cost_status is CostStatus.TRACKED:
            has_tracked_remaining = True
            # Cost basis was already accumulated above the skip guard.
        else:
            # UNKNOWN lot
            quantity_unknown_cost += lot.remaining_quantity
            # UNKNOWN lots contribute ZERO to known_cost_basis

    # known_cost_basis is None when no tracked lots have remaining quantity
    if not has_tracked_remaining:
        known_cost_basis = None

    return PositionState(
        market_hash_name=lots[0].market_hash_name,
        quantity_acquired=quantity_acquired,
        quantity_remaining=quantity_remaining,
        quantity_unknown_cost=quantity_unknown_cost,
        known_cost_basis=known_cost_basis,
        tracked_lot_count=tracked_lot_count,
        unknown_lot_count=unknown_lot_count,
    )


def calculate_all_positions(
    lots: list[AcquisitionLot],
) -> dict[str, PositionState]:
    """
    Calculate PositionState for all market_hash_names present in lots.

    Args:
        lots: List of AcquisitionLot objects.

    Returns:
        Dict mapping market_hash_name to PositionState.

    Raises:
        ValueError: If lots is empty.
    """
    if not lots:
        raise ValueError("lots list must not be empty")

    by_name: dict[str, list[AcquisitionLot]] = defaultdict(list)
    for lot in lots:
        by_name[lot.market_hash_name].append(lot)

    return {
        name: calculate_position_state(lot_list)
        for name, lot_list in by_name.items()
    }


#: Original V0.7.0 name for the position aggregator. The implementation was
#: later renamed to ``calculate_position_state``; this alias keeps the
#: documented ``compute_position`` entry point importable so existing P&L
#: callers and tests continue to work.
compute_position = calculate_position_state
