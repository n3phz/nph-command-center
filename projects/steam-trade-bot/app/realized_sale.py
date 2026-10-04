"""
Phase 7A — Read-Only Realized Sale Accounting

Recognizes completed Steam Market sales and calculates REALIZED profit/loss
by matching authoritative sale events against tracked acquisition lots.

READ-ONLY:
- No database writes (unless explicitly persisted by caller)
- No Steam Market write operations
- No trade execution
- No automatic selling or listing

Accounting semantics:
- AcquisitionLot.unit_cost = all-in cost per unit (includes fees)
- Realized cost basis = sum(unit_cost * quantity_allocated) for each lot
- Realized profit = authoritative sale proceeds - realized cost basis
- Realized margin = realized profit / realized cost basis
- Lot consumption reduces remaining_quantity (never original_quantity)
- Idempotent: same Steam event identity processed only once
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional

from transactions import (
    AcquisitionLot,
    CostStatus,
    Transaction,
    TransactionType,
)


# ============================================================
# ENUMS
# ============================================================

class RealizedSaleClassification(str, Enum):
    """Classification of a realized sale event."""

    PROFITABLE = "PROFITABLE"
    LOSS = "LOSS"
    BREAK_EVEN = "BREAK_EVEN"
    UNVERIFIED = "UNVERIFIED"


class AllocationPolicy(str, Enum):
    """Lot allocation policy for sale matching."""

    FIFO = "FIFO"


# ============================================================
# DATA CLASSES
# ============================================================

@dataclass(frozen=True, slots=True)
class RealizedSale:
    """A single realized sale event matched against acquisition lots."""

    event_type: str
    market_hash_name: str
    appid: Optional[int]
    classid: Optional[str]
    listingid: Optional[str]
    purchaseid: Optional[str]
    transactionid: Optional[int]

    quantity: int
    sale_unit_price: Optional[Decimal]
    sale_fees: Optional[Decimal]
    total_sale_proceeds: Optional[Decimal]
    timestamp: str
    bot_name: str
    external_ref: str

    allocated_lots: list["AllocatedLot"] = field(default_factory=list)
    realized_cost_basis: Decimal = Decimal("0")

    realized_profit: Optional[Decimal] = None
    realized_margin: Optional[Decimal] = None

    classification: RealizedSaleClassification = RealizedSaleClassification.UNVERIFIED
    reason: str = ""

    sale_proceeds_verified: bool = False
    acquisition_cost_verified: bool = False

    @property
    def is_profitable(self) -> Optional[bool]:
        if self.realized_profit is None:
            return None
        return self.realized_profit > 0

    @property
    def is_loss(self) -> Optional[bool]:
        if self.realized_profit is None:
            return None
        return self.realized_profit < 0

    @property
    def is_break_even(self) -> Optional[bool]:
        if self.realized_profit is None:
            return None
        return self.realized_profit == 0


@dataclass(frozen=True, slots=True)
class AllocatedLot:
    """A portion of an acquisition lot allocated to a sale."""

    lot_id: int
    lot_source_transaction_id: int
    market_hash_name: str
    bot_name: str
    unit_cost: Optional[Decimal]
    cost_status: CostStatus
    quantity_allocated: int
    remaining_before: int
    remaining_after: int

    @property
    def cost_for_allocated(self) -> Optional[Decimal]:
        """Total cost for the allocated quantity."""
        if self.unit_cost is not None and self.quantity_allocated > 0:
            return self.unit_cost * Decimal(str(self.quantity_allocated))
        return None


# ============================================================
# ALLOCATION ENGINE
# ============================================================

class LotAllocationEngine:
    """Allocates sale quantities to acquisition lots using FIFO policy."""

    def __init__(self, policy: AllocationPolicy = AllocationPolicy.FIFO):
        self.policy = policy

    def allocate(
        self,
        lots: list[AcquisitionLot],
        sale_quantity: int,
    ) -> list[AllocatedLot]:
        """Allocate sale quantity to lots using FIFO policy."""
        if not lots:
            raise ValueError("no lots available for allocation")

        if sale_quantity <= 0:
            raise ValueError("sale_quantity must be positive")

        first = lots[0]
        for lot in lots:
            if lot.market_hash_name != first.market_hash_name:
                raise ValueError("all lots must have same market_hash_name")
            if lot.bot_name != first.bot_name:
                raise ValueError("all lots must have same bot_name")

        sorted_lots = sorted(lots, key=lambda l: l.acquired_at)

        total_remaining = sum(l.remaining_quantity for l in sorted_lots)
        if total_remaining < sale_quantity:
            raise ValueError(f"insufficient quantity: need {sale_quantity}, have {total_remaining}")

        allocated = []
        remaining = sale_quantity

        for lot in sorted_lots:
            if remaining <= 0:
                break

            allocatable = min(lot.remaining_quantity, remaining)
            if allocatable > 0:
                allocated.append(AllocatedLot(
                    lot_id=lot.id or 0,
                    lot_source_transaction_id=lot.source_transaction_id,
                    market_hash_name=lot.market_hash_name,
                    bot_name=lot.bot_name,
                    unit_cost=lot.unit_cost,
                    cost_status=lot.cost_status,
                    quantity_allocated=allocatable,
                    remaining_before=lot.remaining_quantity,
                    remaining_after=lot.remaining_quantity - allocatable,
                ))
                remaining -= allocatable

        if remaining > 0:
            raise ValueError("allocation failed: insufficient remaining quantity")

        return allocated


# ============================================================
# REALIZED SALE PROCESSOR
# ============================================================

class RealizedSaleProcessor:
    """Processes completed Steam Market sale events and calculates realized P&L."""

    def __init__(
        self,
        allocation_engine: Optional[LotAllocationEngine] = None,
    ):
        self.allocation_engine = allocation_engine or LotAllocationEngine()

    def process_sale(
        self,
        sale_transaction: Transaction,
        available_lots: list[AcquisitionLot],
    ) -> RealizedSale:
        """Process a completed SELL transaction against available acquisition lots."""
        if sale_transaction.type != TransactionType.SELL:
            raise ValueError(f"expected SELL transaction, got {sale_transaction.type}")

        matching_lots = [
            lot for lot in available_lots
            if lot.market_hash_name == sale_transaction.market_hash_name
            and lot.bot_name == sale_transaction.bot_name
            and lot.remaining_quantity > 0
        ]

        if not matching_lots:
            return RealizedSale(
                event_type="SELL",
                market_hash_name=sale_transaction.market_hash_name,
                appid=None,
                classid=None,
                listingid=None,
                purchaseid=None,
                transactionid=None,
                quantity=sale_transaction.quantity,
                sale_unit_price=sale_transaction.unit_price,
                sale_fees=sale_transaction.fees,
                total_sale_proceeds=sale_transaction.total_value,
                timestamp=sale_transaction.timestamp,
                bot_name=sale_transaction.bot_name,
                external_ref=sale_transaction.external_ref,
                classification=RealizedSaleClassification.UNVERIFIED,
                reason="No matching acquisition lots available",
                sale_proceeds_verified=sale_transaction.unit_price is not None
                    and sale_transaction.total_value is not None,
                acquisition_cost_verified=False,
            )

        try:
            allocated_lots = self.allocation_engine.allocate(
                matching_lots,
                sale_transaction.quantity,
            )
        except ValueError as exc:
            return RealizedSale(
                event_type="SELL",
                market_hash_name=sale_transaction.market_hash_name,
                appid=None,
                classid=None,
                listingid=None,
                purchaseid=None,
                transactionid=None,
                quantity=sale_transaction.quantity,
                sale_unit_price=sale_transaction.unit_price,
                sale_fees=sale_transaction.fees,
                total_sale_proceeds=sale_transaction.total_value,
                timestamp=sale_transaction.timestamp,
                bot_name=sale_transaction.bot_name,
                external_ref=sale_transaction.external_ref,
                classification=RealizedSaleClassification.UNVERIFIED,
                reason=f"Allocation failed: {exc}",
                sale_proceeds_verified=sale_transaction.unit_price is not None
                    and sale_transaction.total_value is not None,
                acquisition_cost_verified=False,
            )

        # Calculate realized cost basis
        realized_cost_basis = Decimal("0")
        acquisition_cost_verified = True

        for alloc in allocated_lots:
            cost = alloc.cost_for_allocated
            if cost is not None:
                realized_cost_basis += cost
            else:
                acquisition_cost_verified = False

        # Calculate realized profit
        total_sale_proceeds = sale_transaction.total_value or Decimal("0")
        realized_profit = total_sale_proceeds - realized_cost_basis
        realized_margin = None
        if realized_cost_basis > 0:
            realized_margin = (realized_profit / realized_cost_basis).quantize(Decimal("0.0001"))

        classification, reason = self._classify(
            realized_profit=realized_profit,
            sale_proceeds_verified=sale_transaction.unit_price is not None
                and sale_transaction.total_value is not None,
            acquisition_cost_verified=acquisition_cost_verified,
        )

        listingid = None
        purchaseid = None
        if sale_transaction.external_ref and ":" in sale_transaction.external_ref:
            parts = sale_transaction.external_ref.split(":")
            listingid = parts[0] if parts[0] else None
            purchaseid = parts[1] if len(parts) > 1 and parts[1] else None

        return RealizedSale(
            event_type="SELL",
            market_hash_name=sale_transaction.market_hash_name,
            appid=None,
            classid=None,
            listingid=listingid,
            purchaseid=purchaseid,
            transactionid=None,
            quantity=sale_transaction.quantity,
            sale_unit_price=sale_transaction.unit_price,
            sale_fees=sale_transaction.fees,
            total_sale_proceeds=sale_transaction.total_value,
            timestamp=sale_transaction.timestamp,
            bot_name=sale_transaction.bot_name,
            external_ref=sale_transaction.external_ref,
            allocated_lots=allocated_lots,
            realized_cost_basis=realized_cost_basis,
            realized_profit=realized_profit,
            realized_margin=realized_margin,
            classification=classification,
            reason=reason,
            sale_proceeds_verified=sale_transaction.unit_price is not None
                and sale_transaction.total_value is not None,
            acquisition_cost_verified=acquisition_cost_verified,
        )

    def _classify(
        self,
        realized_profit: Optional[Decimal],
        sale_proceeds_verified: bool,
        acquisition_cost_verified: bool,
    ) -> tuple:
        """Classify the realized sale."""
        if not sale_proceeds_verified:
            return (
                RealizedSaleClassification.UNVERIFIED,
                "Sale proceeds not authoritatively verified",
            )

        if not acquisition_cost_verified:
            return (
                RealizedSaleClassification.UNVERIFIED,
                "Acquisition cost not fully verified for all allocated lots",
            )

        if realized_profit is None:
            return (
                RealizedSaleClassification.UNVERIFIED,
                "Profit calculation failed",
            )

        if realized_profit > 0:
            return (
                RealizedSaleClassification.PROFITABLE,
                f"Realized profit: {realized_profit:.2f} EUR",
            )
        elif realized_profit < 0:
            return (
                RealizedSaleClassification.LOSS,
                f"Realized loss: {abs(realized_profit):.2f} EUR",
            )
        else:
            return (
                RealizedSaleClassification.BREAK_EVEN,
                "Break-even sale",
            )


# ============================================================
# RECONCILIATION SERVICE
# ============================================================

@dataclass(frozen=True, slots=True)
class LotUpdate:
    """Instruction to update an acquisition lot's remaining quantity."""
    lot_id: int
    new_remaining_quantity: int


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    """Result of sale reconciliation."""
    realized_sale: RealizedSale
    lot_updates: list[LotUpdate]
    is_new: bool


class SaleReconciliationService:
    """High-level service for sale reconciliation."""

    def __init__(
        self,
        processor: Optional[RealizedSaleProcessor] = None,
    ):
        self.processor = processor or RealizedSaleProcessor()

    def reconcile_sale(
        self,
        sale_transaction: Transaction,
        available_lots: list[AcquisitionLot],
    ) -> ReconciliationResult:
        """Reconcile a sale event against acquisition lots."""
        realized_sale = self.processor.process_sale(sale_transaction, available_lots)

        lot_updates = [
            LotUpdate(
                lot_id=alloc.lot_id,
                new_remaining_quantity=alloc.remaining_after,
            )
            for alloc in realized_sale.allocated_lots
        ]

        return ReconciliationResult(
            realized_sale=realized_sale,
            lot_updates=lot_updates,
            is_new=realized_sale.classification != RealizedSaleClassification.UNVERIFIED
                or realized_sale.acquisition_cost_verified,
        )


# ============================================================
# FACTORY
# ============================================================

def create_realized_sale_processor(
    allocation_policy: AllocationPolicy = AllocationPolicy.FIFO,
) -> RealizedSaleProcessor:
    """Factory function to create a RealizedSaleProcessor."""
    engine = LotAllocationEngine(policy=allocation_policy)
    return RealizedSaleProcessor(allocation_engine=engine)


def create_sale_reconciliation_service(
    allocation_policy: AllocationPolicy = AllocationPolicy.FIFO,
) -> SaleReconciliationService:
    """Factory function to create a SaleReconciliationService."""
    processor = create_realized_sale_processor(allocation_policy=allocation_policy)
    return SaleReconciliationService(processor=processor)
