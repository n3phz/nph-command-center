"""
Transaction and acquisition lot domain primitives.

This module provides pure domain helpers for creating and validating
transaction records and acquisition lots. It does not perform I/O;
callers are responsible for persistence.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Optional


class TransactionType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class CostStatus(str, Enum):
    TRACKED = "TRACKED"
    UNKNOWN = "UNKNOWN"


class SourceType(str, Enum):
    STEAM_MARKET_PURCHASE = "STEAM_MARKET_PURCHASE"
    MANUAL_ENTRY = "MANUAL_ENTRY"
    TRADE_RECEIVED = "TRADE_RECEIVED"
    UNKNOWN = "UNKNOWN"


class EvidenceType(str, Enum):
    STEAM_MARKET_HISTORY = "STEAM_MARKET_HISTORY"
    MANUAL = "MANUAL"
    TRADE_OFFER = "TRADE_OFFER"
    EXTERNAL_RECEIPT = "EXTERNAL_RECEIPT"


class Provenance:
    """Evidence of acquisition provenance."""

    def __init__(
        self,
        evidence_type: EvidenceType,
        evidence_id: str,
        evidence_data: Optional[dict] = None,
    ):
        self.evidence_type = evidence_type
        self.evidence_id = evidence_id
        self.evidence_data = evidence_data or {}

    def __repr__(self):
        return f"Provenance(evidence_type={self.evidence_type}, evidence_id={self.evidence_id})"


class TransactionError(ValueError):
    """Raised when a transaction is invalid."""


class TransactionValidationError(TransactionError):
    """Raised when a transaction fails validation."""


class AcquisitionLotError(ValueError):
    """Raised when an acquisition lot is invalid."""


def _require_positive_int(value: int, field: str) -> int:
    if not isinstance(value, int) or value <= 0:
        raise TransactionError(f"{field} must be a positive integer")
    return value


def _require_non_negative_int(value: int, field: str) -> int:
    if not isinstance(value, int) or value < 0:
        raise TransactionError(f"{field} must be a non-negative integer")
    return value


def _require_non_negative_decimal(value: Decimal, field: str) -> Decimal:
    if not value.is_finite() or value < 0:
        raise TransactionError(f"{field} must be a non-negative Decimal")
    return value


def _parse_decimal(value: str, field: str) -> Decimal:
    try:
        result = Decimal(value)
    except (InvalidOperation, TypeError) as exc:
        raise TransactionError(f"{field} must be a valid decimal string") from exc
    if not result.is_finite():
        raise TransactionError(f"{field} must be a finite decimal")
    return result


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_decimal(value, field: str) -> Decimal:
    """Convert value to Decimal, accepting str, int, or Decimal."""
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise TransactionError(f"{field} must be a valid decimal string") from exc


def create_transaction(
    type: str,
    market_hash_name: str,
    quantity: int,
    unit_price,
    fees,
    total_value=None,
    timestamp: str = "",
    bot_name: str = "",
    external_ref: Optional[str] = None,
) -> Transaction:
    """Create and validate a Transaction.

    This is a thin validation wrapper that ensures all Transaction
    invariants are checked at creation time.

    Accepts str, int, or Decimal for monetary fields and converts to
    Decimal internally. When total_value is None, it is derived as
    unit_price * quantity. When timestamp is empty, the current UTC
    time is used.
    """
    unit_price_dec = _to_decimal(unit_price, "unit_price")
    fees_dec = _to_decimal(fees, "fees")

    if total_value is None:
        total = unit_price_dec * quantity
    else:
        total = _to_decimal(total_value, "total_value")
        if not total.is_finite() or total < 0:
            raise TransactionError("total_value must be a non-negative Decimal")

    return Transaction(
        type=TransactionType(type),
        market_hash_name=market_hash_name,
        quantity=quantity,
        unit_price=unit_price_dec,
        fees=fees_dec,
        total_value=total,
        timestamp=timestamp or _utc_now_iso(),
        bot_name=bot_name,
        external_ref=external_ref,
    )


@dataclass(frozen=True, slots=True)
class Transaction:
    """
    An immutable economic event record.

    Persistence callers should map these fields to the `transactions` table.
    """

    type: TransactionType
    market_hash_name: str
    quantity: int
    unit_price: Decimal
    fees: Decimal
    total_value: Decimal
    timestamp: str
    bot_name: str
    external_ref: Optional[str] = None
    id: Optional[int] = None  # assigned on insert

    def __post_init__(self) -> None:
        if not isinstance(self.type, TransactionType):
            raise TransactionValidationError("type must be a TransactionType")
        if not self.market_hash_name or not self.market_hash_name.strip():
            raise TransactionValidationError("market_hash_name must be a non-empty string")
        _require_positive_int(self.quantity, "quantity")
        _require_non_negative_decimal(self.unit_price, "unit_price")
        _require_non_negative_decimal(self.fees, "fees")
        _require_non_negative_decimal(self.total_value, "total_value")
        if not self.timestamp or not self.timestamp.strip():
            raise TransactionValidationError("timestamp must be a non-empty ISO-8601 string")
        if not self.bot_name or not self.bot_name.strip():
            raise TransactionValidationError("bot_name must be a non-empty string")

    @classmethod
    def create_buy(
        cls,
        market_hash_name: str,
        quantity: int,
        unit_price: Decimal,
        fees: Decimal,
        bot_name: str,
        timestamp: Optional[str] = None,
        external_ref: Optional[str] = None,
        total_value: Optional[Decimal] = None,
    ) -> "Transaction":
        if total_value is None:
            total = unit_price * quantity
        else:
            if not total_value.is_finite() or total_value < 0:
                raise TransactionError("total_value must be a non-negative Decimal")
            total = total_value
        return cls(
            type=TransactionType.BUY,
            market_hash_name=market_hash_name.strip(),
            quantity=quantity,
            unit_price=unit_price,
            fees=fees,
            total_value=total,
            timestamp=timestamp or _utc_now_iso(),
            bot_name=bot_name.strip(),
            external_ref=external_ref.strip() if external_ref else None,
        )

    @classmethod
    def create_sell(
        cls,
        market_hash_name: str,
        quantity: int,
        unit_price: Decimal,
        fees: Decimal,
        bot_name: str,
        timestamp: Optional[str] = None,
        external_ref: Optional[str] = None,
        total_value: Optional[Decimal] = None,
    ) -> "Transaction":
        if total_value is None:
            total = unit_price * quantity
        else:
            if not total_value.is_finite() or total_value < 0:
                raise TransactionError("total_value must be a non-negative Decimal")
            total = total_value
        return cls(
            type=TransactionType.SELL,
            market_hash_name=market_hash_name.strip(),
            quantity=quantity,
            unit_price=unit_price,
            fees=fees,
            total_value=total,
            timestamp=timestamp or _utc_now_iso(),
            bot_name=bot_name.strip(),
            external_ref=external_ref.strip() if external_ref else None,
        )

    def to_db_params(self) -> tuple:
        """Return parameters for INSERT into transactions table."""
        return (
            self.type.value,
            self.market_hash_name,
            self.quantity,
            str(self.unit_price),
            str(self.fees),
            str(self.total_value),
            self.timestamp,
            self.bot_name,
            self.external_ref,
        )


@dataclass(frozen=True, slots=True)
class AcquisitionLot:
    """
    An immutable acquisition lot representing cost basis from a BUY transaction.

    Persistence callers should map these fields to the `acquisition_lots` table.
    """

    source_transaction_id: int
    market_hash_name: str
    bot_name: str
    original_quantity: int
    remaining_quantity: int
    unit_cost: Optional[Decimal]
    acquired_at: str
    cost_status: CostStatus
    id: Optional[int] = None  # assigned on insert

    def __post_init__(self) -> None:
        if not isinstance(self.cost_status, CostStatus):
            raise AcquisitionLotError("cost_status must be a CostStatus")
        _require_positive_int(self.original_quantity, "original_quantity")
        _require_non_negative_int(self.remaining_quantity, "remaining_quantity")
        if self.remaining_quantity > self.original_quantity:
            raise AcquisitionLotError("remaining_quantity cannot exceed original_quantity")
        if self.cost_status is CostStatus.TRACKED:
            if self.unit_cost is None:
                raise AcquisitionLotError("TRACKED lots require a non-negative unit_cost")
            _require_non_negative_decimal(self.unit_cost, "unit_cost")
        else:
            if self.unit_cost is not None:
                raise AcquisitionLotError("UNKNOWN lots must have unit_cost = None")
        if not self.market_hash_name or not self.market_hash_name.strip():
            raise AcquisitionLotError("market_hash_name must be a non-empty string")
        if not self.bot_name or not self.bot_name.strip():
            raise AcquisitionLotError("bot_name must be a non-empty string")
        if not self.acquired_at or not self.acquired_at.strip():
            raise AcquisitionLotError("acquired_at must be a non-empty ISO-8601 string")
        if not isinstance(self.source_transaction_id, int) or self.source_transaction_id <= 0:
            raise AcquisitionLotError("source_transaction_id must be a positive integer")

    @classmethod
    def from_buy_transaction(
        cls,
        transaction: Transaction,
        cost_status: CostStatus = CostStatus.TRACKED,
        unit_cost: Optional[Decimal] = None,
    ) -> "AcquisitionLot":
        """
        Create an acquisition lot from a BUY transaction.

        For TRACKED cost status, unit_cost defaults to the transaction's unit_price.
        For UNKNOWN cost status, unit_cost must be None.

        Raises:
            ValueError: If the transaction has not been persisted (id is None).
                        Use a persisted transaction or assign a valid positive
                        source_transaction_id manually for dry-run projections.
        """
        if transaction.type is not TransactionType.BUY:
            raise AcquisitionLotError("only BUY transactions can create acquisition lots")

        if cost_status is CostStatus.TRACKED:
            if unit_cost is None:
                unit_cost = transaction.unit_price
        else:
            if unit_cost is not None:
                raise AcquisitionLotError("UNKNOWN cost status requires unit_cost = None")

        source_id = transaction.id
        if source_id is None:
            raise ValueError("Transaction must be persisted (id is None); cannot create lot with unknown source_transaction_id")

        return cls(
            source_transaction_id=source_id,
            market_hash_name=transaction.market_hash_name,
            bot_name=transaction.bot_name,
            original_quantity=transaction.quantity,
            remaining_quantity=transaction.quantity,
            unit_cost=unit_cost,
            acquired_at=transaction.timestamp,
            cost_status=cost_status,
        )

    def to_db_params(self) -> tuple:
        """Return parameters for INSERT into acquisition_lots table."""
        return (
            self.source_transaction_id,
            self.market_hash_name,
            self.bot_name,
            self.original_quantity,
            self.remaining_quantity,
            str(self.unit_cost) if self.unit_cost is not None else None,
            self.acquired_at,
            self.cost_status.value,
        )

    def consume(self, quantity: int) -> "AcquisitionLot":
        """
        Return a new lot with reduced remaining_quantity.

        This is a pure function; it does not mutate the original lot.
        The caller is responsible for persisting the new state.
        """
        _require_positive_int(quantity, "quantity")
        if quantity > self.remaining_quantity:
            raise AcquisitionLotError("cannot consume more than remaining_quantity")
        return AcquisitionLot(
            source_transaction_id=self.source_transaction_id,
            market_hash_name=self.market_hash_name,
            bot_name=self.bot_name,
            original_quantity=self.original_quantity,
            remaining_quantity=self.remaining_quantity - quantity,
            unit_cost=self.unit_cost,
            acquired_at=self.acquired_at,
            cost_status=self.cost_status,
            id=self.id,
        )

    def is_fully_consumed(self) -> bool:
        return self.remaining_quantity == 0
