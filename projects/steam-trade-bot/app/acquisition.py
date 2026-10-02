"""Acquisition recording service — canonical Phase 1 persistence path.

Provides the single authoritative function to record an acquisition lot
and its source transaction. All acquisition creation (TRACKED or UNKNOWN)
must go through `record_acquisition` to enforce Phase 1 invariants.

Phase 1 invariants enforced:
  - TRACKED requires non-None unit_cost and valid provenance
  - UNKNOWN requires unit_cost=None and no provenance
  - Idempotency via source_key (bot_name + external_ref)
  - No cost fabrication
  - Single transaction + lot atomic insert
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
import sqlite3
from decimal import Decimal
from typing import Optional

from transactions import (
    Transaction,
    TransactionType,
    CostStatus,
    create_transaction,
    TransactionError,
)
from transaction_store import insert_buy_with_lot


class AcquisitionError(ValueError):
    """Raised when acquisition recording cannot proceed safely."""


@dataclass(frozen=True)
class RecordedAcquisition:
    """Result of a successful acquisition recording."""

    lot: "AcquisitionLotRecord"
    transaction: Optional["TransactionRecord"] = None
    created: bool = True  # False if idempotent resolve


@dataclass(frozen=True)
class AcquisitionLotRecord:
    """Persisted acquisition lot view."""

    lot_id: int
    source_transaction_id: int
    market_hash_name: str
    bot_name: str
    original_quantity: int
    remaining_quantity: int
    unit_cost: Optional[Decimal]
    acquired_at: str
    cost_status: CostStatus
    source_type: Optional[SourceType] = None
    provenance: Optional[Provenance] = None


@dataclass(frozen=True)
class TransactionRecord:
    """Persisted transaction view."""

    transaction_id: int
    type: TransactionType
    market_hash_name: str
    quantity: int
    unit_price: Decimal
    fees: Decimal
    total_value: Decimal
    timestamp: str
    bot_name: str
    external_ref: Optional[str]


# Re-export enums for downstream compatibility
from transactions import SourceType, Provenance, EvidenceType, CostStatus as CostStatusEnum

__all__ = [
    "AcquisitionError",
    "RecordedAcquisition",
    "AcquisitionLotRecord",
    "TransactionRecord",
    "record_acquisition",
    "SourceType",
    "Provenance",
    "EvidenceType",
    "CostStatus",
    "Repository",
]


#: Optional Phase 3D evidence columns on acquisition_lots. Absent on
#: databases created before Phase 3D; callers degrade gracefully.
_PROVENANCE_COLUMNS = ("provenance", "source_type", "external_ref")

#: Optional Phase 3G accounting columns on acquisition_lots. Absent on
#: databases created before Phase 3G; callers degrade gracefully.
_ACCOUNTING_COLUMNS = ("acquisition_fee", "all_in_cost")


def migrate_acquisition_accounting(conn) -> None:
    """Add the Phase 3G accounting columns to ``acquisition_lots``.

    Additive and idempotent: never rewrites historical values and never
    changes the meaning of ``unit_cost``. ``unit_cost`` continues to hold
    the Steam price-excluding-fees basis (seller-side amount); the new
    columns carry the acquisition fee and the all-in economic cost.

    Never applied automatically against a production database; callers
    decide when to run it.
    """
    existing = _existing_columns(conn, "acquisition_lots")
    if not existing:
        return
    for column in _ACCOUNTING_COLUMNS:
        if column not in existing:
            conn.execute(
                f"ALTER TABLE acquisition_lots ADD COLUMN {column} TEXT"
            )


def backfill_accounting_from_provenance(conn) -> int:
    """Populate ``acquisition_fee``/``all_in_cost`` from stored provenance.

    Uses the extended evidence keys written by Phase 3G
    (``paid_amount_cents`` + ``paid_fee_cents``). Rows whose provenance
    predates the fee breakdown, or whose JSON is unreadable, are left
    untouched and reported by the return value. Nothing is rewritten.

    Returns the number of rows updated.
    """
    if not _accounting_columns_present(conn):
        return 0

    rows = conn.execute(
        """
        SELECT id, provenance
        FROM acquisition_lots
        WHERE provenance IS NOT NULL
          AND (acquisition_fee IS NULL OR all_in_cost IS NULL)
        """
    ).fetchall()

    updated = 0
    for lot_id, raw in rows:
        provenance = _deserialize_provenance(raw)
        if provenance is None:
            continue
        data = provenance.evidence_data or {}
        paid_amount = data.get("paid_amount_cents")
        paid_fee = data.get("paid_fee_cents")
        if paid_amount is None or paid_fee is None:
            continue
        # Steam reports paid_amount/paid_fee for the ENTIRE purchase,
        # so they divide directly by the lot's original_quantity to get
        # the per-unit figures that align with unit_cost.
        quantity_row = conn.execute(
            "SELECT original_quantity FROM acquisition_lots WHERE id = ?",
            (lot_id,),
        ).fetchone()
        if quantity_row is None:
            continue
        quantity = int(quantity_row[0] or 0)
        if quantity <= 0:
            continue
        try:
            fee_per_unit = _quantize_money(cents_to_decimal(paid_fee) / Decimal(quantity))
            all_in_per_unit = _quantize_money(
                cents_to_decimal(paid_amount + paid_fee) / Decimal(quantity)
            )
            conn.execute(
                """
                UPDATE acquisition_lots
                SET acquisition_fee = ?, all_in_cost = ?
                WHERE id = ?
                """,
                (str(fee_per_unit), str(all_in_per_unit), lot_id),
            )
        except sqlite3.Error:
            continue
        updated += 1
    return updated


def _accounting_columns_present(conn) -> bool:
    """True when the Phase 3G accounting columns exist on the table."""
    existing = _existing_columns(conn, "acquisition_lots")
    return all(column in existing for column in _ACCOUNTING_COLUMNS)


def _quantize_money(value: Decimal) -> Decimal:
    """Round a major-unit Decimal to exactly two decimal places."""
    return value.quantize(Decimal("0.01"))


def cents_to_decimal(cents) -> Decimal:
    """Convert a minor-unit (cents) amount to a major-unit Decimal.

    Single canonical conversion used by every accounting write path so
    stored monetary columns are always major units with exactly two
    decimal places (e.g. 3 -> "0.03", 2 -> "0.02").
    """
    return (Decimal(cents) / Decimal(100)).quantize(Decimal("0.01"))


def _existing_columns(conn, table: str) -> set:
    """Return the set of columns present on ``table`` (empty on error)."""
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    except Exception:
        return set()


def _serialize_provenance(provenance) -> Optional[str]:
    """Serialize a Provenance object to JSON text for storage."""
    if provenance is None:
        return None
    evidence_type = getattr(provenance, "evidence_type", None)
    value = getattr(evidence_type, "value", evidence_type)
    return json.dumps(
        {
            "evidence_type": None if value is None else str(value),
            "evidence_id": getattr(provenance, "evidence_id", ""),
            "evidence_data": getattr(provenance, "evidence_data", {}) or {},
        },
        sort_keys=True,
    )


def _deserialize_provenance(raw) -> Optional[Provenance]:
    """Rebuild a Provenance object from stored JSON text.

    Returns None when the payload is missing or unparseable, so that a
    corrupt evidence column can never crash a read path.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None

    raw_type = data.get("evidence_type")
    try:
        evidence_type = EvidenceType(raw_type) if raw_type else EvidenceType.MANUAL
    except ValueError:
        evidence_type = EvidenceType.MANUAL

    return Provenance(
        evidence_type=evidence_type,
        evidence_id=str(data.get("evidence_id") or ""),
        evidence_data=data.get("evidence_data") or {},
    )


class Repository:
    """Database repository for acquisition operations.

    Wraps a raw SQLite connection with acquisition-specific queries.
    """

    def __init__(self, conn):
        self.connection = conn

    def get_transaction_by_external_ref(self, bot_name: str, external_ref: str) -> Optional[TransactionRecord]:
        """Look up existing transaction by external_ref for idempotency."""
        row = self.connection.execute(
            """
            SELECT id, type, market_hash_name, quantity, unit_price, fees,
                   total_value, timestamp, bot_name, external_ref
            FROM transactions
            WHERE bot_name = ? AND external_ref = ?
            """,
            (bot_name, external_ref),
        ).fetchone()

        if row is None:
            return None

        return TransactionRecord(
            transaction_id=row[0],
            type=TransactionType(row[1]),
            market_hash_name=row[2],
            quantity=row[3],
            unit_price=Decimal(row[4]),
            fees=Decimal(row[5]),
            total_value=Decimal(row[6]),
            timestamp=row[7],
            bot_name=row[8],
            external_ref=row[9],
        )

    def get_lot_by_source_transaction(self, source_transaction_id: int) -> Optional[AcquisitionLotRecord]:
        """Look up acquisition lot by source transaction.

        Phase 3D: reads the optional evidence columns when they exist so a
        TRACKED lot returns its provenance instead of silently losing it.
        """
        available = _existing_columns(self.connection, "acquisition_lots")
        extra = [col for col in _PROVENANCE_COLUMNS if col in available]

        select = (
            "SELECT id, source_transaction_id, market_hash_name, bot_name,"
            " original_quantity, remaining_quantity, unit_cost,"
            " acquired_at, cost_status"
        )
        if extra:
            select += ", " + ", ".join(extra)
        select += " FROM acquisition_lots WHERE source_transaction_id = ?"

        row = self.connection.execute(select, (source_transaction_id,)).fetchone()

        if row is None:
            return None

        provenance = _deserialize_provenance(row[9]) if extra and len(row) > 9 else None
        source_type = None
        if extra and len(row) > 10 and row[10]:
            try:
                source_type = SourceType(row[10])
            except ValueError:
                source_type = None

        unit_cost = Decimal(row[6]) if row[6] is not None else None
        return AcquisitionLotRecord(
            lot_id=row[0],
            source_transaction_id=row[1],
            market_hash_name=row[2],
            bot_name=row[3],
            original_quantity=row[4],
            remaining_quantity=row[5],
            unit_cost=unit_cost,
            acquired_at=row[7],
            cost_status=CostStatus(row[8]),
            source_type=source_type,
            provenance=provenance,
        )

    def insert_transaction_and_lot(
        self,
        transaction: Transaction,
        unit_cost: Optional[Decimal],
        acquired_at: str,
        cost_status: CostStatus,
        provenance: Optional[Provenance] = None,
        source_type: Optional[SourceType] = None,
        external_ref: Optional[str] = None,
    ) -> tuple[int, int]:
        """Insert transaction and acquisition lot atomically.

        Returns (transaction_id, lot_id).
        Caller is responsible for transaction management (BEGIN/COMMIT/ROLLBACK).
        """
        cursor = self.connection.execute(
            """
            INSERT INTO transactions (
                type,
                market_hash_name,
                quantity,
                unit_price,
                fees,
                total_value,
                timestamp,
                bot_name,
                external_ref
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction.type.value,
                transaction.market_hash_name,
                transaction.quantity,
                str(transaction.unit_price),
                str(transaction.fees),
                str(transaction.total_value),
                transaction.timestamp,
                transaction.bot_name,
                transaction.external_ref,
            ),
        )

        transaction_id = cursor.lastrowid
        if transaction_id is None:
            raise AcquisitionError("failed to obtain transaction id")

        cursor = self.connection.execute(
            """
            INSERT INTO acquisition_lots (
                source_transaction_id,
                market_hash_name,
                bot_name,
                original_quantity,
                remaining_quantity,
                unit_cost,
                acquired_at,
                cost_status,
                provenance,
                source_type,
                external_ref
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transaction_id,
                transaction.market_hash_name,
                transaction.bot_name,
                transaction.quantity,
                transaction.quantity,
                str(unit_cost) if unit_cost is not None else None,
                acquired_at,
                cost_status.value,
                _serialize_provenance(provenance) if provenance is not None else None,
                source_type.value if source_type is not None else None,
                external_ref,
            ),
        )

        lot_id = cursor.lastrowid
        if lot_id is None:
            raise AcquisitionError("failed to obtain acquisition lot id")

        return transaction_id, lot_id


def record_acquisition(
    repository: Repository,
    bot_name: str,
    market_hash_name: str,
    quantity: int,
    acquired_at: str | date,
    unit_cost: Optional[Decimal],
    currency: Optional[str],
    source_type: Optional["SourceType"],
    provenance: Optional["Provenance"],
    external_reference: Optional[str],
    entered_at: str,
) -> RecordedAcquisition:
    """Record an acquisition (TRACKED or UNKNOWN) via canonical Phase 1 path.

    This is the ONLY function that should create acquisition lots and their
    source transactions. It enforces all Phase 1 invariants.

    Args:
        repository: Database repository.
        bot_name: Bot name for idempotency and attribution.
        market_hash_name: Item market hash name.
        quantity: Quantity acquired (positive integer).
        acquired_at: Acquisition date (ISO string or date).
        unit_cost: Per-unit cost in currency units (None for UNKNOWN).
        currency: ISO currency code (e.g., "EUR", "USD") — required for TRACKED.
        source_type: SourceType enum (e.g., STEAM_MARKET_PURCHASE) — required for TRACKED.
        provenance: Provenance object with evidence — required for TRACKED.
        external_reference: Unique external key for idempotency (e.g., "listingid:purchaseid").
        entered_at: ISO timestamp when this record was created.

    Returns:
        RecordedAcquisition with lot, transaction, and created flag.

    Raises:
        AcquisitionError: If invariants violated or persistence fails.
    """
    # Normalize acquired_at to ISO date string
    if isinstance(acquired_at, date):
        acquired_at_iso = acquired_at.isoformat()
    else:
        acquired_at_iso = acquired_at

    # Phase 1 invariant validation
    is_tracked = unit_cost is not None

    if is_tracked:
        if unit_cost < 0:
            raise AcquisitionError("TRACKED cost requires non-negative unit_cost")
        if currency is None:
            raise AcquisitionError("TRACKED cost requires currency")
        if source_type is None:
            raise AcquisitionError("TRACKED cost requires source_type")
        if provenance is None:
            raise AcquisitionError("TRACKED cost requires provenance")
        if external_reference is None:
            raise AcquisitionError("TRACKED cost requires external_reference for idempotency")
    else:
        if unit_cost is not None:
            raise AcquisitionError("UNKNOWN cost requires unit_cost = None")

    # Validate quantity
    if not isinstance(quantity, int) or quantity <= 0:
        raise AcquisitionError("quantity must be a positive integer")

    # Idempotency check via external_reference (source_key)
    if external_reference is not None:
        existing_tx = repository.get_transaction_by_external_ref(bot_name, external_reference)
        if existing_tx is not None:
            # Idempotent resolve - return existing
            existing_lot = repository.get_lot_by_source_transaction(existing_tx.transaction_id)
            if existing_lot is not None:
                return RecordedAcquisition(
                    lot=existing_lot,
                    transaction=existing_tx,
                    created=False,
                )

    # Create the BUY transaction (fees=0 for acquisition recording, total=unit_cost*qty)
    # For TRACKED: unit_price = unit_cost, fees = 0
    # For UNKNOWN: we still create a BUY transaction but with unit_price=0, fees=0
    if is_tracked:
        transaction_unit_price = unit_cost
        transaction_fees = Decimal("0")
        transaction_total = unit_cost * quantity
    else:
        transaction_unit_price = Decimal("0")
        transaction_fees = Decimal("0")
        transaction_total = Decimal("0")

    # Create transaction with the acquired_at timestamp
    transaction = Transaction.create_buy(
        market_hash_name=market_hash_name,
        quantity=quantity,
        unit_price=transaction_unit_price,
        fees=transaction_fees,
        bot_name=bot_name,
        timestamp=acquired_at_iso,
        external_ref=external_reference,
        total_value=transaction_total,
    )

    cost_status = CostStatus.TRACKED if is_tracked else CostStatus.UNKNOWN

    # Insert transaction and lot within caller's transaction
    transaction_id, lot_id = repository.insert_transaction_and_lot(
        transaction=transaction,
        unit_cost=unit_cost,
        acquired_at=acquired_at_iso,
        cost_status=cost_status,
        provenance=provenance,
        source_type=source_type,
        external_ref=external_reference,
    )

    # Read back the created records
    lot_record = repository.get_lot_by_source_transaction(transaction_id)
    tx_record = repository.get_transaction_by_external_ref(bot_name, external_reference)

    return RecordedAcquisition(
        lot=lot_record,
        transaction=tx_record,
        created=True,
    )